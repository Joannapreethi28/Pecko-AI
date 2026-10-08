"""Pecko, the real loop in one process: mic (or WAV) -> Ears -> Brain -> Voice -> speaker.

    python -m spine.app --mic                      # live: say "hey Pecko, ..."
    python -m spine.app --wav data/clips/q1.wav    # recorded input at real-time speed, then exit
    python -m spine.app --wav q1.wav --no-wake --no-audio   # headless test run (no speaker)

Run it under the cap with scripts/run_pecko.sh. Every stage keeps its own threads; this file only routes
contract messages (docs/CONTRACT.md) and owns the commit gate C (v2.1 hold-and-release): when Brain
logs `final_valid{gen}` (final transcript validated; `gen` is the generation that answers it: the
held gen if the transcript matched what Brain prepared, else a fresh or cached gen), Spine sends
`commit` and Voice may release that gen's audio. Every answered turn gets exactly this one gate, and
it fires before Brain emits any audible chunk of that gen. Nothing held is audible before it.
All stages log into one events.jsonl (contract log lines), and bus.jsonl records every routed message.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from common.clock import now
from common.log import EventLog

ROOT = Path(__file__).resolve().parents[1]

# who receives each message type (docs/CONTRACT.md)
FROM_EARS = {"partial": ("brain",), "tentative_final": ("brain",), "final": ("brain",),
             "cancel": ("brain",), "barge_in": ("voice", "brain"), "intent_hint": ("voice",)}
FROM_BRAIN = {"chunk": ("voice",), "cached": ("voice",), "cancel": ("voice",)}


class StageLog(EventLog):
    """A stage-bound view of the shared run log (Brain-style `.event()`), with an optional hook."""

    def __init__(self, stage: str, shared: EventLog, hook: Optional[Callable[[dict], None]] = None):
        super().__init__(stage)
        self.stream, self._lock, self._shared, self._hook = shared.stream, shared._lock, shared, hook

    def emit(self, stage, event, turn=None, *, t=None, **extra):
        rec = super().emit(stage, event, turn, t=t, **extra)
        if self._hook is not None:
            self._hook(rec)
        return rec


class LineSink:
    """File-like object for Ears: it writes one JSON message per line; we route each line."""

    def __init__(self, on_msg: Callable[[dict], None]):
        self._on_msg, self._buf = on_msg, ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._on_msg(json.loads(line))
        return len(s)

    def flush(self) -> None:
        pass


class Pecko:
    """Routes contract messages between stages. Stages are injected so tests can use fakes:
    ears.feed(frame, t)/on_playback_state(bool); brain/voice .start/.feed/.stop/.set_tier."""

    def __init__(self, log: EventLog, bus_path: Optional[Path] = None):
        self.log = log
        self.ears: Any = None
        self.brain: Any = None
        self.voice: Any = None
        self._bus = open(bus_path, "a", encoding="utf-8", buffering=1) if bus_path else None
        self._bus_lock = threading.Lock()
        self.turns_done: set[int] = set()
        self.turn_done = threading.Condition()

    # ---- routing -----------------------------------------------------------------------------
    def _record(self, src: str, dsts: tuple, msg: dict) -> None:
        if self._bus is not None:
            with self._bus_lock:
                self._bus.write(json.dumps({"t": now(), "src": src, "dst": list(dsts), "msg": msg}) + "\n")

    def _deliver(self, dst: str, msg: dict) -> None:
        stage = getattr(self, dst)
        if stage is not None:
            stage.feed(msg)

    def from_ears(self, msg: dict) -> None:
        dsts = FROM_EARS.get(msg.get("type"), ())
        self._record("ears", dsts, msg)
        for d in dsts:
            self._deliver(d, msg)

    def from_brain(self, msg: dict) -> None:
        dsts = FROM_BRAIN.get(msg.get("type"), ())
        self._record("brain", dsts, msg)
        for d in dsts:
            self._deliver(d, msg)

    def from_voice(self, msg: dict) -> None:
        typ = msg.get("type")
        if typ == "playback_state":
            self._record("voice", ("ears",), msg)
            if self.ears is not None:
                self.ears.on_playback_state(bool(msg.get("playing")))
            if not msg.get("playing"):
                with self.turn_done:
                    self.turns_done.add(int(msg.get("turn", -1)))
                    self.turn_done.notify_all()
        elif typ == "turn_summary":
            self._record("voice", (), msg)

    def on_brain_log(self, rec: dict) -> None:
        """Commit gate C: Brain validated the final transcript and named the gen that answers it."""
        if rec.get("event") == "final_valid":
            msg = {"type": "commit", "turn": rec["turn"], "gen": rec["extra"]["gen"], "t": now()}
            self.log.emit("spine", "commit", rec["turn"], t=msg["t"], gen=msg["gen"])
            self._record("spine", ("voice",), msg)
            self._deliver("voice", msg)

    def set_tier(self, n: int) -> None:
        """Between turns only (contract): every stage maps the number to its own ladder."""
        self.log.emit("spine", "tier_switch", None, to=n)
        for s in (self.ears, self.brain, self.voice):
            if s is not None:
                s.set_tier(n)

    def wait_turn(self, turn: int, timeout: float) -> bool:
        with self.turn_done:
            return self.turn_done.wait_for(lambda: turn in self.turns_done, timeout=timeout)

    def close(self) -> None:
        if self._bus is not None:
            self._bus.close()
            self._bus = None


# ---- real stages ---------------------------------------------------------------------------------
def build(args, out_dir: Path) -> tuple[Pecko, Any]:
    from brain.llama_client import LlamaClient
    from brain.llama_server import LlamaServer
    from brain.router import Router
    from brain.stage import BrainStage
    from ears.stage import Ears
    from voice import vlog
    from voice.stage import VoiceStage

    events = open(out_dir / "events.jsonl", "a", encoding="utf-8", buffering=1)
    shared = EventLog(events)
    app = Pecko(shared, out_dir / "bus.jsonl")

    def server_factory(tier):
        return LlamaServer(ROOT / "models" / tier.model, ctx=tier.ctx, threads=tier.threads,
                           threads_batch=tier.threads_batch, port=args.port,
                           log_path=out_dir / "llama-server.log")

    app.brain = BrainStage(app.from_brain, StageLog("brain", shared, app.on_brain_log),
                           LlamaClient(port=args.port), tier=args.tier, router=Router.load(),
                           server_factory=server_factory, hold_release=not args.no_hold)
    app.voice = VoiceStage(on_event=app.from_voice, tier=args.tier, audio=not args.no_audio,
                           barge_in=not args.half_duplex)
    vlog.add_sink(lambda rec: shared.stream.write(json.dumps(rec) + "\n"))   # Voice lines into the run log
    ears_tier = args.tier if args.ears_tier is None else args.ears_tier
    app.ears = Ears(tier=ears_tier, out_stream=LineSink(app.from_ears))   # never loads Moonshine at T2/T3
    app.ears._elog = EventLog(events)   # Ears diagnostics (t_eos, endpoint, asr_final) into the run log
    return app, events


def sample_resources(log: EventLog, stop: threading.Event, period: float = 0.5) -> None:
    """Live proof of the cap for the dashboard: cgroup limits + usage every `period` s (off the
    first-audio path; a sleeping thread). Logs `spine resources` lines; silent off Linux."""
    from spine.resources import own_cgroup, read_snapshot, usage_delta

    try:
        path = own_cgroup()
    except OSError as e:
        log.emit("spine", "resources_unavailable", None, error=str(e))
        return
    def mem_split() -> dict:   # anon (process memory) vs file (page cache: model reads, logs) in the cgroup
        try:
            st = dict(line.split() for line in (path / "memory.stat").read_text().splitlines())
            return {"memory_anon": int(st["anon"]), "memory_file": int(st["file"])}
        except (OSError, KeyError, ValueError):
            return {}

    before = read_snapshot(path)
    while not stop.wait(period):
        snap = read_snapshot(path)
        d = usage_delta(before, snap)
        log.emit("spine", "resources", None, t=snap.t, mean_cores=d["mean_cores"], cpu_max=snap.cpu_max,
                 memory_current=snap.memory_current, memory_peak=snap.memory_peak,
                 memory_max=snap.memory_max, swap_max=snap.swap_max, oom_kill=snap.oom_kill,
                 cgroup=path.name, **mem_split())
        before = snap


def start_all(app: Pecko, tier: int, ears_tier: Optional[int] = None) -> None:
    t0 = now()
    et = tier if ears_tier is None else ears_tier
    app.ears.start()
    if getattr(app.ears, "tier", et) != et:   # build() already constructs Ears at et; only fix a mismatch
        app.ears.set_tier(et)
    app.brain.start()
    app.voice.start()
    app.log.emit("spine", "ready", None, startup_s=round(now() - t0, 2), tier=tier, ears_tier=et,
                 pid=os.getpid())


def stop_all(app: Pecko) -> None:
    for s in (app.voice, app.brain, app.ears):
        try:
            s.stop()
        except Exception as e:   # keep stopping the rest; report it
            app.log.emit("spine", "stop_error", None, error=repr(e)[:200])
    app.close()


def run_wav(app: Pecko, path: Path, tail_s: float, wake: bool) -> None:
    """Feed a WAV at real-time speed, then silence so the endpointer fires, then wait for playback."""
    import numpy as np
    from ears.audio_io import FRAME_SAMPLES, WavFrameSource
    from ears.clock import Clock
    from ears.config import FRAME_MS

    if not wake:
        app.ears.push_to_talk()
    clock = Clock()
    for frame, t in WavFrameSource(str(path), clock, realtime=True).frames():
        app.ears.feed(frame, t)
    silence = np.zeros(FRAME_SAMPLES, dtype=np.float32)
    end = time.monotonic() + tail_s
    while time.monotonic() < end:
        time.sleep(FRAME_MS / 1000)
        app.ears.feed(silence, clock.now())
        if app.ears.turn and app.ears.turn in app.turns_done:
            break


def run_mic(app: Pecko) -> None:
    """Live loop. The audio callback only copies + stamps; the Ears thread does the model work."""
    from ears.audio_io import open_mic_stream
    from ears.clock import Clock

    frames: queue.Queue = queue.Queue(maxsize=200)

    def on_frame(frame, t):
        try:
            frames.put_nowait((frame, t))
        except queue.Full:
            pass   # Ears fell behind; dropping is better than unbounded RAM

    with open_mic_stream(on_frame, Clock()):
        print('Pecko is listening. Say "hey Pecko, ..." (Ctrl-C to quit).', flush=True)
        while True:
            frame, t = frames.get()
            app.ears.feed(frame, t)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--mic", action="store_true", help="live microphone")
    src.add_argument("--wav", type=Path, nargs="+", help="16 kHz mono WAV(s), played at real-time speed")
    ap.add_argument("--tier", type=int, default=0, help="start tier T0-T3 (docs/CONTRACT.md)")
    ap.add_argument("--ears-tier", type=int, default=None,
                    help="Ears ASR tier if different (2 = Zipformer 20M, much lighter than Moonshine)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--no-wake", action="store_true", help="WAV runs: skip the wake word (push-to-talk)")
    ap.add_argument("--no-audio", action="store_true", help="no speaker (Voice still synthesizes)")
    ap.add_argument("--no-hold", action="store_true", help="disable hold-and-release (ablation)")
    ap.add_argument("--half-duplex", action="store_true", help="ignore barge-in (if echo stops Pecko)")
    ap.add_argument("--tail", type=float, default=15.0, help="seconds of silence after each WAV")
    ap.add_argument("--out", type=Path, default=None, help="run folder (default data/results/run-<time>)")
    args = ap.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    out = args.out or ROOT / "data" / "results" / time.strftime("run-%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    app, events = build(args, out)
    stop = threading.Event()
    threading.Thread(target=sample_resources, args=(app.log, stop), name="spine-resources", daemon=True).start()
    try:
        start_all(app, args.tier, args.ears_tier)
        if args.mic:
            run_mic(app)
        else:
            for wav in args.wav:
                run_wav(app, wav, args.tail, wake=not args.no_wake)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        stop_all(app)
        events.close()
        print(f"run log: {out}/events.jsonl  bus: {out}/bus.jsonl", flush=True)


if __name__ == "__main__":
    main()
