"""Bounded, event-driven v2 routing. Stage feed() must enqueue work and return.

Adapters publish their outputs via publish(source, message). One owner calls
dispatch_one(); inference and audio callbacks must not run on that owner.
Brain registers preparations and final prompt tokens using the internal callback
methods. These share the event queue with the frozen v2/v2.1 messages.
"""

from copy import deepcopy
from queue import Full, Queue
from threading import Lock
from typing import Protocol

from common.log import EventLog
from spine.turns import TurnController
from spine.report import finite


class Stage(Protocol):
    def start(self) -> None: ...
    def feed(self, msg: dict) -> None: ...
    def stop(self) -> None: ...
    def set_tier(self, n: int) -> None: ...


ROUTES = {
    ("ears", "partial"): ("brain",),
    ("ears", "tentative_final"): ("brain",),
    ("ears", "final"): ("brain",),
    ("ears", "cancel"): ("brain", "voice"),
    ("ears", "barge_in"): ("brain", "voice"),
    ("ears", "intent_hint"): ("voice",),
    ("brain", "chunk"): ("voice",),
    ("brain", "cached"): ("voice",),
    ("voice", "playback_state"): ("ears",),
    ("voice", "cancel"): ("brain",),
}


class EventBus:
    def __init__(self, stages: dict[str, Stage], log: EventLog, capacity: int = 256):
        if set(stages) != {"ears", "brain", "voice"}:
            raise ValueError("Expected ears, brain and voice adapters")
        if capacity < 1:
            raise ValueError("Queue capacity must be positive")
        self.stages = stages
        self.log = log
        self.queue = Queue(maxsize=capacity)
        self._started: list[Stage] = []
        self.turns = TurnController(log)
        self._used = False
        self._active = False
        self.tier = 0
        self._requested_tier = None
        self.outcomes: dict[int, dict] = {}
        self._failure = None
        self._failure_lock = Lock()
        self.tier_guard = None
        self.tier_revision = 0

    def start(self) -> None:
        if self._used:
            raise RuntimeError("Create a fresh bus for each run")
        self._used = True
        try:
            # Consumers warm before producers can emit input.
            for name in ("voice", "brain", "ears"):
                stage = self.stages[name]
                self._started.append(stage)
                stage.start()
                self.log.emit(name, "ready")
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        # One cleanup failure must not leave the other engines running.
        while self._started:
            stage = self._started.pop()
            try:
                stage.stop()
            except Exception as exc:
                self.log.emit("spine", "stop_error", error=repr(exc))

    def publish(self, source: str, msg: dict) -> None:
        key = (source, msg.get("type"))
        if key not in ROUTES:
            raise ValueError(f"Unsupported v2 route: {key}")
        if type(msg.get("turn")) is not int or msg["turn"] < 0:
            raise ValueError("Messages need a nonnegative integer turn")
        if source == "brain":
            if type(msg.get("gen")) is not int or msg["gen"] < 0:
                raise ValueError("Brain output needs a nonnegative integer gen")
            if "held" in msg and type(msg["held"]) is not bool:
                raise ValueError("held must be a boolean")
        if key == ("voice", "playback_state") and type(msg.get("playing")) is not bool:
            raise ValueError("playback_state needs boolean playing")
        # Fail visibly on overload; never silently lose cancellation or audio.
        # Callers must handle queue.Full as a fatal pipeline overload.
        self._enqueue(source, deepcopy(msg))

    def fail(self, source: str, reason: str) -> None:
        """Worker callback: wake the owner and abort on a fatal engine error.

        The failure flag works even when the ordinary queue is already full.
        Worker adapters must catch their errors and call this callback.
        """
        if source not in ("ears", "brain", "voice", "spine") or not isinstance(reason, str):
            raise ValueError("Expected stage name and error text")
        with self._failure_lock:
            if self._failure is None:
                self._failure = (source, reason)
        try:
            self.queue.put_nowait(("supervisor", {"type": "fatal"}))
        except Full:
            pass  # Existing queued work already guarantees the owner can wake.

    def _raise_failure(self) -> None:
        with self._failure_lock:
            failure = self._failure
        if failure is not None:
            raise RuntimeError(f"{failure[0]} worker failed: {failure[1]}")

    def _enqueue(self, source: str, msg: dict) -> None:
        try:
            self.queue.put_nowait((source, msg))
        except Full:
            stage = source if source in ("ears", "brain", "voice") else "spine"
            self.fail(stage, "Event queue capacity exceeded")
            raise

    def _tokens(self, kind: str, turn: int, gen: int, tokens: list[int]) -> None:
        if any(type(n) is not int or n < 0 for n in (turn, gen)):
            raise ValueError("turn and gen must be nonnegative integers")
        if not tokens or any(type(n) is not int or n < 0 for n in tokens):
            raise ValueError("Expected a nonempty sequence of nonnegative token IDs")
        self._enqueue("adapter", {"type": kind, "turn": turn,
                                  "gen": gen, "tokens": list(tokens)})

    def prepared(self, turn: int, gen: int, prompt_tokens: list[int]) -> None:
        """Brain callback: register tokens BEFORE publishing this gen's chunks."""
        self._tokens("prepared", turn, gen, prompt_tokens)

    def validate_final(self, turn: int, gen: int, final_tokens: list[int]) -> None:
        """Brain callback: serialize the Ears final's full prompt, then submit."""
        self._tokens("final_tokens", turn, gen, final_tokens)

    def request_tier(self, tier: int) -> None:
        """Supervisor callback after checking model availability/transition budget."""
        if type(tier) is not int or not 0 <= tier <= 3:
            raise ValueError("Tier must be 0..3")
        self._enqueue("supervisor", {"type": "tier", "tier": tier})

    def finish_turn(self, turn: int) -> None:
        """Supervisor callback AFTER all playback/work has stopped for this turn.

        playback_state:false alone is insufficient: it can mean a temporary gap.
        This closes the turn to late callbacks, then applies a queued tier.
        """
        if type(turn) is not int or turn < 0:
            raise ValueError("turn must be a nonnegative integer")
        self._enqueue("supervisor", {"type": "finish", "turn": turn})

    def complete_turn(self, turn: int, gen: int, *, success: bool,
                      reason: str | None = None, gap_s: float | None = None) -> None:
        """Adapter/supervisor callback after all work/audio stops and scoring ends.

        This is a Python callback, not a change to the wire contract. Worker
        completions must carry their generation so old callbacks cannot finish
        a newer generation's turn. Stage errors should propagate to the runner.
        """
        if any(type(n) is not int or n < 0 for n in (turn, gen)) or type(success) is not bool:
            raise ValueError("Expected integer turn/gen and boolean success")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("reason must be text or None")
        if gap_s is not None:
            finite(gap_s, "gap_s", minimum=0)
        self._enqueue("supervisor", {"type": "outcome", "turn": turn,
                      "gen": gen, "success": success, "reason": reason,
                      "gap_s": gap_s})

    def _apply_tier(self) -> None:
        if self._active or self._requested_tier is None:
            return
        requested = self._requested_tier
        self._requested_tier = None
        if requested == self.tier:
            return
        old = self.tier
        if self.tier_guard is not None and not self.tier_guard(old, requested):
            self.tier_revision += 1
            self.log.emit("spine", "tier_rejected", old=old, tier=requested,
                          reason="transition profile or current resource limit")
            return
        # Any stage failure propagates: supervisor must stop all stages. A
        # partially switched stack must never resume as though it succeeded.
        for name in ("brain", "voice", "ears"):
            self.stages[name].set_tier(requested)
        self.tier = requested
        self.tier_revision += 1
        self.log.emit("spine", "tier_switch", old=old, tier=requested)

    def _controls(self, messages: list[dict]) -> None:
        for msg in messages:
            # Voice stops/releases first; Brain's feed cannot block on inference.
            for name in ("voice", "brain"):
                self.stages[name].feed(deepcopy(msg))

    def dispatch_one(self, timeout: float | None = None) -> None:
        if not self._started:
            raise RuntimeError("Start stages before dispatch")
        self._raise_failure()
        source, msg = self.queue.get(timeout=timeout)
        try:
            self._raise_failure()
            if source == "supervisor":
                if msg["type"] == "tier":
                    self._requested_tier = msg["tier"]
                elif msg["type"] == "outcome":
                    if ((msg["turn"], msg["gen"]) != (self.turns.turn, self.turns.gen)
                            or self.turns.closed or not self.turns.valid
                            or (msg["success"] and not self.turns.committed)):
                        self.log.emit("spine", "stale_completion", msg["turn"], gen=msg["gen"])
                        return
                    self.outcomes[msg["turn"]] = msg
                    self.log.emit("spine", "turn_end", msg["turn"], gen=msg["gen"],
                                  success=msg["success"], reason=msg["reason"], gap_s=msg["gap_s"])
                    self.turns.complete(msg["turn"])
                    self._active = False
                elif self.turns.complete(msg["turn"]):
                    self._active = False
                self._apply_tier()
                return
            if source == "adapter":
                handler = (self.turns.prepared if msg["type"] == "prepared"
                           else self.turns.validate)
                self._controls(handler(msg["turn"], msg["gen"], msg["tokens"]))
                return
            accepted, controls = self.turns.accept(source, msg)
            self._controls(controls)
            if not accepted:
                self.log.emit("spine", "dropped", msg["turn"], source=source,
                              message_type=msg["type"], gen=msg.get("gen"))
                return
            if source == "ears" and msg["type"] not in ("cancel", "barge_in"):
                self._active = True
                if msg["type"] in ("partial", "final") and "text" in msg:
                    self.log.emit("spine", "transcript", msg["turn"], text=msg["text"], final=msg["type"] == "final")
            for destination in ROUTES[source, msg["type"]]:
                self.stages[destination].feed(deepcopy(msg))
            self.log.emit("spine", "routed", msg["turn"],
                          source=source, message_type=msg["type"], playing=msg.get("playing"))
        finally:
            self.queue.task_done()
