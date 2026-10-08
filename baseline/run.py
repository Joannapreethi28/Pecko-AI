"""B0 default stack: what a typical naive offline voice assistant does. Fully serial, nothing early.

    VAD (Silero, fixed 800 ms silence timer) -> whole-utterance ASR after the endpoint (same Zipformer
    20M int8 files Pecko's Ears T2 uses, fed the whole clip at once) -> full prompt to the SAME llama-server
    model/flags as Pecko Brain T0 with cache_prompt=False (no KV reuse, no early prefill, no speculation)
    -> wait for the FULL reply -> Piper lessac-medium (same engine as Voice T0) on the whole reply -> audio.
    No wake-word model, no router, no cached answers, no fillers.

    python -m baseline.run --wav data/clips/synthetic/q1.wav ...   # run under scripts/run_baseline.sh

Fairness choices (said plainly):
  * t_eos is the SAME definition as Pecko's Ears: Silero's own end sample converted back to the capture
    clock (ears/stage.py::_eos_time). Only the silence hangover differs (800 ms here vs Pecko's endpointer).
  * Same system prompt, same 3-turn history, same temperature 0.4, same n_predict 60 and the same
    2-sentence cap as Brain T0, so both stacks speak answers of the same shape.
  * The wake phrase is stripped from the transcript with the same regex idea as Ears (B0 has no KWS model).
  * No speaker: first_audio_out = the moment the whole-reply PCM exists (Pecko --no-audio uses NullPlayer,
    which stamps the first non-silent write; same meaning, 0 ms device latency on both).
Logs one JSON line per event into <out>/events.jsonl (contract shape, time.monotonic()).
"""
from __future__ import annotations

import argparse
import os
import queue
import re
import threading
import time
from pathlib import Path

import numpy as np

from common.clock import now
from common.log import EventLog

ROOT = Path(__file__).resolve().parents[1]
FRAME_MS = 32
SR = 16000
HANGOVER_MS = 800        # the naive fixed silence timer
PREROLL_FRAMES = 400 // FRAME_MS
MIN_SPEECH_S = 0.15
TTS_PACK = "vits-piper-en_US-lessac-medium"   # Voice T0 engine
_SENT_END = re.compile(r"[.?!](?=\s|$)")
# same wake-strip idea as ears/stage.py (_visible_text / _WAKE_LIKE), copied so B0 never imports Ears' models
_WAKE_LIKE = re.compile(r"^[\s,.]*((hey|hi|hay|a|okay|y|o)[\s,]+)?a?pe[ck]\w*[\s,.!?]+|^[\s,.]*(o|y)\s+(?=\w)",
                        re.IGNORECASE)


def strip_wake(text: str) -> str:
    low = text.lower()
    idx = low.find("pecko")
    if idx != -1:
        return text[idx + 5:].strip(" ,.!?")
    return _WAKE_LIKE.sub("", text).strip(" ,.!?")


class Cgroup:
    """Read-only cgroup v2 counters for this process's scope (llama-server child included)."""

    def __init__(self):
        try:
            from spine.resources import own_cgroup
            self.path = own_cgroup()
        except Exception:
            self.path = None

    def snap(self):
        if self.path is None:
            return None
        from spine.resources import read_snapshot
        return read_snapshot(self.path)

    def cpu_usec(self):
        s = self.snap()
        return None if s is None else s.cpu_usage_usec


def sample_resources(log: EventLog, cg: Cgroup, stop: threading.Event, period: float = 0.5) -> None:
    """Same `spine resources` line shape as spine/app.py, plus RAPL package energy if readable."""
    from spine.energy import RaplMeter
    from spine.resources import usage_delta

    rapl = RaplMeter()
    rapl.sample()
    if not rapl.valid:
        log.emit("baseline", "energy_unavailable", None, errors=rapl.errors)
    before = cg.snap()
    if before is None:
        log.emit("spine", "resources_unavailable", None, error="no cgroup v2")
        return
    while not stop.wait(period):
        snap = cg.snap()
        d = usage_delta(before, snap)
        log.emit("spine", "resources", None, t=snap.t, mean_cores=d["mean_cores"], cpu_max=snap.cpu_max,
                 memory_current=snap.memory_current, memory_peak=snap.memory_peak,
                 memory_max=snap.memory_max, swap_max=snap.swap_max, oom_kill=snap.oom_kill,
                 cgroup=cg.path.name)
        if rapl.valid:
            e = rapl.sample()
            log.emit("baseline", "energy", None, gross_j=e["gross_j"], scope=e["scope"])
        before = snap


class Baseline:
    def __init__(self, log: EventLog, out: Path, port: int, cg: Cgroup):
        self.log, self.out, self.port, self.cg = log, out, port, cg
        self.jobs: queue.Queue = queue.Queue()
        self.pending = 0
        self.lock = threading.Condition()

    # ---- load + warm up (B0 is a *warm* stack; we only measure turns) --------------------------------
    def start(self) -> None:
        from brain.llama_client import LlamaClient
        from brain.llama_server import LlamaServer
        from brain.prompt import PromptBuilder
        from brain.tiers import TIERS
        from ears.backends.asr_zipformer import ZipformerASR
        from ears.backends.vad_silero import SileroVAD
        from voice.engine import TTSEngine

        t0 = now()
        self.tier = TIERS[0]   # Pecko ran Brain T0: same model file, ctx, threads, n_predict
        self.vad = SileroVAD(threshold=0.5, min_silence_ms=HANGOVER_MS)
        self.asr = ZipformerASR()
        self.asr.start()
        self.server = LlamaServer(ROOT / "models" / self.tier.model, ctx=self.tier.ctx, threads=self.tier.threads,
                                  threads_batch=self.tier.threads_batch, port=self.port,
                                  log_path=self.out / "llama-server.log")
        self.server.start()
        self.client = LlamaClient(port=self.port)
        self.prompt = PromptBuilder(self.tier.family, max_turns=3)
        for _ in self.client.stream(self.prompt.final("hello"), n_predict=4, cache_prompt=False):
            pass
        self.tts = TTSEngine(TTS_PACK, threads=1)
        threading.Thread(target=self._worker, name="b0-worker", daemon=True).start()
        self.log.emit("baseline", "ready", None, startup_s=round(now() - t0, 2), model=self.tier.model,
                      ctx=self.tier.ctx, n_predict=self.tier.n_predict, hangover_ms=HANGOVER_MS,
                      asr="zipformer-20m-int8 (whole utterance)", tts=TTS_PACK, cache_prompt=False, pid=os.getpid())

    def stop(self) -> None:
        self.server.stop()

    # ---- audio front end: VAD + fixed silence timer ---------------------------------------------------
    def run_wav(self, path: Path, tail_s: float) -> None:
        from ears.audio_io import FRAME_SAMPLES, PreRollBuffer, WavFrameSource
        from ears.clock import Clock

        clock, preroll = Clock(), PreRollBuffer()
        st = {"speech": None, "t_start": None, "cpu0": None}
        self.turn = getattr(self, "turn", 0)
        turn0 = self.turn

        def on_frame(frame, t_cap):
            ev = self.vad.process(frame)
            if st["speech"] is None:
                preroll.push(frame)
                if ev and "start" in ev:
                    st["speech"] = [preroll.drain()]
                    st["t_start"], st["cpu0"] = t_cap, self.cg.cpu_usec()
                return
            st["speech"].append(frame)
            if ev and "end" in ev:   # Silero fired 'end' after HANGOVER_MS of silence: that IS the endpoint
                t_endpoint = now()
                it = self.vad._iterator
                lag = (it.current_sample - ev["end"]) / SR
                t_eos = t_cap - lag if 0 <= lag < 2.0 else t_cap   # same rule as ears/stage.py::_eos_time
                audio = np.concatenate(st["speech"])
                if t_eos - st["t_start"] >= MIN_SPEECH_S:
                    self.turn += 1
                    self.log.emit("ears", "t_eos", self.turn, t=t_eos)
                    self.log.emit("ears", "endpoint", self.turn, t=t_endpoint, delay_s=t_endpoint - t_eos)
                    with self.lock:
                        self.pending += 1
                    self.jobs.put((self.turn, audio, t_eos, st["cpu0"]))
                st["speech"] = None

        self.vad.reset()
        for frame, t in WavFrameSource(str(path), clock, realtime=True).frames():
            on_frame(frame, t)
        silence = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        end = time.monotonic() + tail_s
        while time.monotonic() < end:
            time.sleep(FRAME_MS / 1000)
            on_frame(silence, clock.now())
            with self.lock:
                if st["speech"] is None and self.pending == 0 and self.turn > turn0:
                    break   # like spine/app.py::run_wav: stop the tail once this WAV's turn is answered
        with self.lock:   # never drop a turn: wait for the pipeline to finish what was endpointed
            self.lock.wait_for(lambda: self.pending == 0, timeout=120)

    # ---- serial back end: ASR -> full LLM reply -> whole-reply TTS ------------------------------------
    def _worker(self) -> None:
        while True:
            turn, audio, t_eos, cpu0 = self.jobs.get()
            try:
                self._turn(turn, audio, t_eos, cpu0)
            except Exception as e:
                self.log.emit("baseline", "turn_error", turn, error=repr(e)[:300])
            finally:
                with self.lock:
                    self.pending -= 1
                    self.lock.notify_all()

    def _turn(self, turn: int, audio: np.ndarray, t_eos: float, cpu0) -> None:
        from brain.speakable import ThinkFilter, clean
        from voice.engine import finish_clip

        L = self.log
        t0 = now()
        self.asr.begin_utterance()
        self.asr.accept_frame(audio)
        raw, _ = self.asr.finish()
        text = strip_wake(raw)
        L.emit("ears", "asr_final", turn, text=text, raw=raw, ms=round((now() - t0) * 1000, 1),
               audio_s=round(len(audio) / SR, 2))
        if not text:
            L.emit("baseline", "turn_failed", turn, reason="empty transcript")
            return
        prompt = self.prompt.final(text)
        L.emit("brain", "prompt_ready", turn, chars=len(prompt))
        think, pieces, reply, timings, got = ThinkFilter(), [], "", None, False
        for piece in self.client.stream(prompt, n_predict=self.tier.n_predict, temperature=0.4, cache_prompt=False):
            if piece.timings is not None:
                timings = piece.timings
                break
            if not got:
                got = True
                L.emit("brain", "first_token", turn)
            pieces.append(piece.text)
            reply += think.feed(piece.text)
            if len(_SENT_END.findall(reply.strip())) >= self.tier.max_sentences:   # same 2-sentence cap as Brain
                break
        reply = clean(reply + think.flush())
        tm = timings.__dict__ if timings else {}
        L.emit("brain", "llm_done", turn, reply=reply, **tm)
        self.prompt.add_turn(text, "".join(pieces))
        if not reply:
            L.emit("baseline", "turn_failed", turn, reason="empty reply")
            return
        L.emit("voice", "synth_start", turn, chars=len(reply))
        ts = now()
        pcm = finish_clip(self.tts.synth(reply), reply)
        t_end = now()
        L.emit("voice", "synth_end", turn, t=t_end, ms=round((t_end - ts) * 1000, 1), audio_s=round(len(pcm) / 22050, 2))
        L.emit("voice", "first_audio_out", turn, t=t_end, content=True, layer="whole_reply")
        cpu1, snap = self.cg.cpu_usec(), self.cg.snap()
        L.emit("baseline", "turn_done", turn, first_audio_ms=round((t_end - t_eos) * 1000),
               cpu_s=None if cpu0 is None or cpu1 is None else round((cpu1 - cpu0) / 1e6, 3),
               memory_peak=None if snap is None else snap.memory_peak)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wav", type=Path, nargs="+", required=True, help="16 kHz mono WAV(s), real-time speed")
    ap.add_argument("--port", type=int, default=8090, help="llama-server port (not Pecko's 8080)")
    ap.add_argument("--tail", type=float, default=15.0, help="max seconds of silence fed after each WAV")
    ap.add_argument("--out", type=Path, default=None, help="run folder (default data/results/baseline-<time>)")
    args = ap.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    out = args.out or ROOT / "data" / "results" / time.strftime("baseline-%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    events = open(out / "events.jsonl", "a", encoding="utf-8", buffering=1)
    log, cg = EventLog(events), Cgroup()
    stop = threading.Event()
    threading.Thread(target=sample_resources, args=(log, cg, stop), name="b0-resources", daemon=True).start()
    b0 = Baseline(log, out, args.port, cg)
    try:
        b0.start()
        for wav in args.wav:
            log.emit("baseline", "wav", None, path=str(wav))
            b0.run_wav(wav, args.tail)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        time.sleep(0.6)
        try:
            b0.stop()
        except Exception:
            pass
        events.close()
        print(f"run log: {out}/events.jsonl", flush=True)


if __name__ == "__main__":
    main()
