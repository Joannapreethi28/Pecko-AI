"""Contract-faithful synthetic adapters. No speech engines, tokenizer or speaker."""

import json
from threading import Event, Thread

from common.clock import now
from spine.hold import HoldBuffer
from spine.report import finite


class PlaceholderStage:
    placeholder = True

    def __init__(self, context, config):
        self.context, self.config = context, config
        self.tier = 0

    def start(self):
        self.context.log("placeholder_start", engine=False)

    def stop(self):
        pass

    def set_tier(self, n):
        self.tier = n


class PlaceholderEars(PlaceholderStage):
    def __init__(self, context, config):
        super().__init__(context, config)
        self.shutdown = Event()
        self.worker = None

    def feed(self, msg):
        if msg["type"] == "playback_state":
            self.context.log("placeholder_playback_feedback", msg["turn"], playing=msg["playing"])

    def replay(self, case, turn):
        script = case.get("script", [{"at_s": 0, "type": "final", "text": case.get("text", "Hello Pecko")}])
        if not isinstance(script, list) or not script:
            raise ValueError("Script must contain events")
        previous = -1
        for item in script:
            offset = finite(item.get("at_s"), "script offset", minimum=0)
            if offset < previous or item.get("type") not in ("partial", "tentative_final", "cancel", "final", "barge_in"):
                raise ValueError("Script events need ordered offsets and supported Ears types")
            if item["type"] in ("partial", "tentative_final", "final") and not isinstance(item.get("text"), str):
                raise ValueError("Transcript events need text")
            previous = offset
        eos_offset = finite(case.get("eos_offset_s", 0), "EOS offset", minimum=0)
        start = now()
        eos = start + eos_offset
        def replay():
            try:
                for item in script:
                    if self.shutdown.wait(max(0, start + item["at_s"] - now())):
                        return
                    msg = {k: v for k, v in item.items() if k != "at_s"}
                    msg.update(turn=turn, t=now())
                    if msg["type"] == "partial":
                        msg.setdefault("stable", "")
                    if msg["type"] in ("tentative_final", "final"):
                        msg["t_eos"] = eos
                    if msg["type"] == "tentative_final":
                        msg.setdefault("p_done", 0.8)
                    if msg["type"] == "final":
                        msg.update(norm=msg["text"].lower(), t_endpoint=now())
                        self.context.log("endpoint", turn)
                        self.context.log("asr_final", turn, text=msg["text"])
                    self.context.publish(msg)
            except Exception as exc:
                self.context.fail(str(exc))
        self.worker = Thread(target=replay, name="placeholder-replay")
        self.worker.start()
        return eos

    def stop(self):
        self.shutdown.set()
        if self.worker:
            self.worker.join(timeout=2)
            if self.worker.is_alive():
                raise RuntimeError("Placeholder replay failed to stop")


class PlaceholderBrain(PlaceholderStage):
    def __init__(self, context, config):
        super().__init__(context, config)
        self.current = None
        self.next_gen = {}

    def tokens(self, text):
        # Exact serialized synthetic prompt, not a real model tokenizer.
        prompt = json.dumps({"system": "Pecko placeholder", "history": [], "user": text}, sort_keys=True)
        return [1, *prompt.encode("utf-8")]

    def prepare(self, msg):
        turn = msg["turn"]
        gen = self.next_gen.get(turn, 0)
        self.next_gen[turn] = gen + 1
        tokens = self.tokens(msg["text"])
        self.current = (turn, gen, tokens)
        self.context.prepared(turn, gen, tokens)
        self.context.log("prompt_ready", turn, gen=gen)
        self.context.log("first_token", turn, gen=gen, tokenizer="synthetic-byte-IDs")
        self.context.publish({"type": "chunk", "turn": turn, "gen": gen, "seq": 0,
                              "text": "The Pecko placeholder received your request.", "held": True, "last": True})
        self.context.log("first_chunk", turn, gen=gen)

    def feed(self, msg):
        kind, turn = msg["type"], msg["turn"]
        if kind == "tentative_final":
            self.prepare(msg)
        elif kind == "final":
            final_tokens = self.tokens(msg["text"])
            if self.current is None or self.current[0] != turn or self.current[2] != final_tokens:
                if self.current is not None and self.current[0] == turn:
                    self.context.log("prompt_mismatch", turn, gen=self.current[1])
                self.prepare(msg)
            self.context.validate(turn, self.current[1], final_tokens)
        elif kind in ("cancel", "barge_in"):
            if self.current and self.current[0] == turn and msg.get("gen", self.current[1]) == self.current[1]:
                self.current = None


class PlaceholderVoice(PlaceholderStage):
    def __init__(self, context, config):
        super().__init__(context, config)
        self.hold = HoldBuffer(config.get("max_held_bytes", 1_048_576))

    def release(self, msg, blocks):
        if not blocks:
            return
        self.context.log("placeholder_release", msg["turn"], gen=msg["gen"], audio=False)
        self.context.publish({"type": "playback_state", "turn": msg["turn"], "playing": False, "t": now()})
        self.context.complete(msg["turn"], msg["gen"], success=True)

    def feed(self, msg):
        kind = msg["type"]
        if kind == "chunk":
            self.context.log("chunk_recv", msg["turn"], gen=msg["gen"], seq=msg["seq"])
            self.context.log("pcm_ready", msg["turn"], gen=msg["gen"], seq=msg["seq"], pcm="synthetic bytes")
            self.release(msg, self.hold.ready(msg["turn"], msg["gen"], msg["seq"], b"placeholder PCM"))
        elif kind == "commit":
            self.release(msg, self.hold.commit(msg["turn"], msg["gen"]))
        elif kind in ("cancel", "barge_in"):
            if "gen" in msg:
                self.hold.cancel(msg["turn"], msg["gen"])
            elif self.hold.key[0] == msg["turn"]:
                self.hold.cancel(*self.hold.key)


FACTORIES = {"ears:placeholder": PlaceholderEars, "brain:placeholder": PlaceholderBrain,
             "voice:placeholder": PlaceholderVoice}
