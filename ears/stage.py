"""The Ears stage: start()/feed()/stop()/set_tier(n) + the state machine
IDLE -> LISTENING -> PAUSED -> (final) -> FOLLOWUP -> IDLE, per
ears/research/01_EARS_research_v2.md §11 and docs/CONTRACT.md.

Wake word: sherpa-onnx KWS (`ears/backends/kws_sherpa.py`) is the primary
detector, loaded best-effort in `start()`. If its model files aren't on this
checkout, `_maybe_check_wake` falls back to matching "pecko" in the ASR's
own running transcript -- a real degrade path, not silently broken -- plus
an explicit `push_to_talk()` escape hatch (the spec's own "demo safety
net").

Endpointer deadline (said plainly): the research doc's skeleton arms a
wall-clock timer for the next threshold crossing. We check a deadline
against `self.clock` on every frame instead -- a real `threading.Timer`
only measures wall time, which breaks VirtualClock's fast (non-realtime)
bake-off mode. Checking once per 32 ms frame is still finer-grained than the
smallest threshold we use (150 ms), so nothing is lost in real-time mode.

Smart Turn (O2, real p_done): `ears/backends/turn_smartturn.py` wraps the real
model. Loading it needs its ~11 MB ONNX file in `models/smart_turn/`, which
may not exist on every checkout, so it's loaded best-effort at start() --
missing weights fall back to `endpointer.NEUTRAL_P_DONE` exactly as before,
logged once, rather than crashing a build that hasn't fetched the model yet.

Arming debounce + pre-roll (filled gaps, both spec'd in
ears/research/01_EARS_research_v2.md section 4 but previously unwired): a
VAD 'start' moves IDLE -> ARMING, not straight to LISTENING. ARMING only
promotes to LISTENING once MIN_SPEECH_MS of unbroken speech has accrued
(a short blip that VAD itself later calls 'end' on is dropped as noise,
back to IDLE); on promotion, the pre-roll buffer's last PREROLL_MS plus the
buffered arming frames are fed into the ASR so the attack of the first
word -- or "hey" of "hey pecko" -- isn't clipped.

Noise floor (filled gap): `ears/noise.py`'s EWMA of silence-frame RMS
selects the VAD threshold's "0.6 in noise" tier from the same research
section, applied only while IDLE (never mid-utterance) so it can't disturb
Silero's internal hangover state, and only when not already overridden by
O9's 0.8-during-playback tier.
"""
import collections
import re

import numpy as np

from common.jsonl import emit
from common.log import EventLog
from ears import contract
from ears.clock import Clock
from ears.audio_io import PreRollBuffer
from ears.backends.asr_moonshine import MoonshineASR
from ears.backends.asr_vosk import VoskASR
from ears.backends.asr_zipformer import ZipformerASR
from ears.backends.kws_sherpa import SherpaKWS
from ears.backends.turn_smartturn import WINDOW_SAMPLES, SmartTurn
from ears.backends.vad_silero_ort import SileroVADOrt as SileroVAD  # torch-free, same events
from ears.backends.vad_webrtc import WebRTCVAD
from ears.config import (
    FOLLOWUP_WINDOW_S,
    HOTWORDS,
    INTENT_OPENERS,
    MIN_SPEECH_MS,
    NEUTRAL_P_DONE,
    PARTIAL_THROTTLE_S,
    VAD_THRESHOLD_NOISY,
    VAD_THRESHOLD_NORMAL,
    VAD_THRESHOLD_PLAYING,
    WAKE_PHRASE,
)
from ears.endpointer import Endpointer
from ears.noise import NoiseFloorEstimator
from ears.normalize import normalize

BARGE_IN_FRAMES_NEEDED = 250 // 32  # O9: ~250 ms of continuous speech
FRAME_SAMPLES = 512  # 32 ms @ 16 kHz
MIN_SPEECH_FRAMES = max(1, MIN_SPEECH_MS // 32)


_WAKE_LIKE = re.compile(r"^[\s,.]*((hey|hi|hay|a|okay|y|o)[\s,]+)?a?pe[ck]\w*[\s,.!?]+|^[\s,.]*(o|y)\s+(?=\w)", re.IGNORECASE)


class Ears:
    def __init__(self, tier: int = 0, clock: Clock | None = None, out_stream=None,
                 endpointer_mode: str = "fusion"):
        import sys

        self.clock = clock or Clock()
        self.out_stream = out_stream or sys.stdout
        self._elog = EventLog(sys.stderr)
        self.tier = tier
        # Build the requested tier's backends directly (no load here; start() loads). Constructing
        # T0 and then set_tier(2) used to load Moonshine Small (~217 MiB anon, measured) only to
        # throw it away -- it inflated startup RAM and was never used at T2/T3.
        self.vad = WebRTCVAD() if tier == 3 else SileroVAD(threshold=0.5)
        self.asr = VoskASR() if tier == 3 else ZipformerASR() if tier == 2 else MoonshineASR(tier=tier)
        self.endpointer = Endpointer(mode=endpointer_mode)
        self.smart_turn: SmartTurn | None = None  # loaded best-effort in start()
        self.kws: SherpaKWS | None = None  # loaded best-effort in start()
        self.preroll = PreRollBuffer()
        self.noise = NoiseFloorEstimator()

        self.state = "IDLE"
        self.turn = 0
        self._armed = False
        self._wake_disabled = False  # set by disable_wake(): every utterance counts, no "hey pecko"
        self._playing = False
        self._is_noisy = False
        self._barge_in_frame_count = 0
        self._t_eos = 0.0
        self._pause_deadline: float | None = None
        self._sent_tentative_final = False
        self._sent_intent_hint = False
        self._last_partial_text = ""
        self._last_partial_t = -1.0
        self._followup_start = 0.0
        self._arming_frames: list = []
        self._turn_audio: collections.deque = collections.deque(maxlen=WINDOW_SAMPLES // FRAME_SAMPLES)
        # Endpoint fix: the ASR stream is finalized ONCE at pause start (VAD
        # end), not again at the deadline. These hold the whole turn's audio
        # (so a resume can rebuild the stream) and the finalized text.
        self._full_turn_audio: list = []
        self._paused_frames: list = []
        self._pause_text: str | None = None

    # --- stage interface -------------------------------------------------
    def start(self) -> None:
        self.asr.start()  # O4: warm up at start, not on the first real turn
        self.asr.set_keyterms(HOTWORDS)  # O10: decoder-level bias, not just post-hoc text replace
        try:
            self.smart_turn = SmartTurn()
        except Exception as e:
            self.smart_turn = None
            self._elog.emit("ears", "smart_turn_unavailable", t=self.clock.now(), error=str(e))
        try:
            self.kws = SherpaKWS()
        except Exception as e:
            self.kws = None
            self._elog.emit("ears", "kws_unavailable", t=self.clock.now(), error=str(e))
        self._elog.emit("ears", "ready", t=self.clock.now())

    def stop(self) -> None:
        self._pause_deadline = None

    def reset_session(self) -> None:
        """Back to a clean slate for a new clip/session, without reloading
        the ASR model (used by scripts/measure.py between clips, and
        logically what happens on a fresh wake word)."""
        self.state = "IDLE"
        self.turn = 0
        self._armed = False
        self._playing = False
        self._is_noisy = False
        self._barge_in_frame_count = 0
        self._pause_deadline = None
        self._sent_tentative_final = False
        self._sent_intent_hint = False
        self._last_partial_text = ""
        self._last_partial_t = -1.0
        self._arming_frames = []
        self._turn_audio.clear()
        self._full_turn_audio = []
        self._paused_frames = []
        self._pause_text = None
        self.vad.reset()
        self.vad.set_threshold(VAD_THRESHOLD_NORMAL)
        self.noise.reset()
        self.endpointer.reset_session()
        if self.kws is not None:
            self.kws.reset()

    def set_tier(self, tier: int) -> None:
        """T0/T1 use MoonshineASR (Small/Tiny) + Silero VAD. T2 switches ASR
        to the lighter ZipformerASR, still with Silero VAD. T3 switches both
        ASR and VAD to Vosk + WebRTC VAD -- the cheapest possible pair, no
        ONNX at all (docs/CONTRACT.md tier table). Model-family changes
        reload from scratch -- Spine's own rule is to call this between
        turns only.

        Known simplification, said plainly: T3's wake path still tries KWS
        first (same as every other tier) rather than being push-to-talk-only
        as the spec's T3 row implies; `push_to_talk()` still works as the
        demo-safety fallback regardless of tier."""
        t0 = self.clock.now()
        if tier == 3:
            if not isinstance(self.asr, VoskASR):
                self.asr = VoskASR()
                self.asr.start()
            if not isinstance(self.vad, WebRTCVAD):
                self.vad = WebRTCVAD()
        elif tier == 2:
            if not isinstance(self.asr, ZipformerASR):
                self.asr = ZipformerASR()
                self.asr.start()
            if not isinstance(self.vad, SileroVAD):
                self.vad = SileroVAD(threshold=VAD_THRESHOLD_NORMAL)
        else:
            if not isinstance(self.asr, MoonshineASR):
                self.asr = MoonshineASR(tier=tier)
                self.asr.start()
            else:
                self.asr.set_tier(tier)
            self.asr.set_keyterms(HOTWORDS)
            if not isinstance(self.vad, SileroVAD):
                self.vad = SileroVAD(threshold=VAD_THRESHOLD_NORMAL)
        self.tier = tier
        self._elog.emit("ears", "tier_switch", t=self.clock.now(),
                         tier=tier, switch_time_s=self.clock.now() - t0)

    def push_to_talk(self) -> None:
        """Demo-safety fallback: force-arm regardless of the wake phrase."""
        self._armed = True

    def disable_wake(self) -> None:
        """Live demo fallback when the wake word won't trigger (e.g. a weak VM
        mic): treat every utterance as addressed to Pecko, not just the next one."""
        self._wake_disabled = True
        self._armed = True

    def on_playback_state(self, playing: bool) -> None:
        """O9: echo-safe barge-in -- raise the VAD threshold and require
        sustained speech while Voice is speaking. Playing always wins over
        the noise-floor tier; on stop, fall back to whatever the noise
        floor currently says (0.5 or 0.6), not blindly to 0.5."""
        self._playing = playing
        if playing:
            self.vad.set_threshold(VAD_THRESHOLD_PLAYING)
        else:
            self.vad.set_threshold(VAD_THRESHOLD_NOISY if self._is_noisy else VAD_THRESHOLD_NORMAL)
        self._barge_in_frame_count = 0

    # --- per-frame feed (audio callback only copies + stamps, O5) -------
    def feed(self, frame, t_cap: float) -> None:
        vad_event = self.vad.process(frame)

        if self._playing and self.state == "IDLE":
            self._check_barge_in(vad_event)
            return

        if self.state == "IDLE":
            self.preroll.push(frame)
            if not self._playing:
                self._update_noise_tier(vad_event, frame)
            if vad_event and "start" in vad_event:
                self.state = "ARMING"
                self._arming_frames = [frame]
            return

        if self.state == "ARMING":
            self._arming_frames.append(frame)
            if vad_event and "end" in vad_event:
                self.state = "IDLE"  # too short to be real speech: a noise blip, not a turn
                self._arming_frames = []
                return
            if len(self._arming_frames) >= MIN_SPEECH_FRAMES:
                self._begin_utterance()
            return

        if self.state == "FOLLOWUP":
            if t_cap - self._followup_start > FOLLOWUP_WINDOW_S:
                self.state = "IDLE"
                return
            if vad_event and "start" in vad_event:
                self._armed = True  # inside the follow-up window: no wake check needed
                self._begin_utterance()
            return

        if self.state == "LISTENING":
            self.asr.accept_frame(frame)
            self._turn_audio.append(frame)
            self._full_turn_audio.append(frame)
            self._maybe_check_wake(frame)
            self._maybe_emit_partial(t_cap)
            if vad_event and "end" in vad_event:
                self._t_eos = self._eos_time(vad_event, t_cap)
                self.state = "PAUSED"
                self._on_pause_start()
                # The deadline may already have passed (VAD's own min-silence
                # hangover, or the decode above): fire now, not a frame later.
                if self.state == "PAUSED" and self._pause_deadline is not None \
                        and self.clock.now() >= self._pause_deadline:
                    self._finalize()
            return

        if self.state == "PAUSED":
            # The ASR stream was already finalized at pause start: don't feed
            # it (each fed frame could trigger another full decode on the
            # critical path). Keep the frames so a resume loses nothing.
            self._paused_frames.append(frame)
            self._turn_audio.append(frame)
            if vad_event and "start" in vad_event:
                self._on_speech_resume(t_cap)
            elif self._pause_deadline is not None and t_cap >= self._pause_deadline:
                self._finalize()
            return

    def _eos_time(self, vad_event, t_cap: float) -> float:
        """t_eos = when speech actually ended, not when VAD *noticed*. Silero's
        'end' fires only after min_silence_ms (200 ms) of silence; its event
        carries the real end sample. Convert it back to the capture clock."""
        end = vad_event.get("end")
        it = getattr(self.vad, "_iterator", None)
        cur = getattr(it, "current_sample", None) if it is not None else getattr(self.vad, "_sample_pos", None)
        if not isinstance(end, (int, float)) or cur is None:
            return t_cap
        lag_s = (cur - end) / 16000
        return t_cap - lag_s if 0 <= lag_s < 2.0 else t_cap

    def _update_noise_tier(self, vad_event, frame) -> None:
        if vad_event and "start" in vad_event:
            return  # this frame is speech onset, not ambient noise
        self.noise.update(frame)
        noisy_now = self.noise.is_noisy()
        if noisy_now != self._is_noisy:
            self._is_noisy = noisy_now
            self.vad.set_threshold(VAD_THRESHOLD_NOISY if noisy_now else VAD_THRESHOLD_NORMAL)
            self._elog.emit("ears", "noise_tier_changed", t=self.clock.now(),
                             noisy=noisy_now, floor_rms=self.noise.floor_rms())

    def _check_barge_in(self, vad_event) -> None:
        if vad_event and "start" in vad_event:
            self._barge_in_frame_count = 1
        elif vad_event and "end" in vad_event:
            self._barge_in_frame_count = 0
        elif self._barge_in_frame_count:
            self._barge_in_frame_count += 1
        if self._barge_in_frame_count == BARGE_IN_FRAMES_NEEDED:
            emit(self.out_stream, **contract.barge_in(self.turn, self.clock.now()))
            self._elog.emit("ears", "barge_in", turn=self.turn, t=self.clock.now())

    # --- utterance lifecycle ---------------------------------------------
    def _begin_utterance(self) -> None:
        self.turn += 1
        if self._wake_disabled:
            self._armed = True
        self.asr.begin_utterance()
        self._sent_tentative_final = False
        self._sent_intent_hint = False
        self._last_partial_text = ""
        self._last_partial_t = -1.0
        self._turn_audio.clear()
        self._full_turn_audio = []
        self._paused_frames = []
        self._pause_text = None
        if self.kws is not None:
            self.kws.reset()
        # Pre-roll (one concatenated chunk) + the buffered arming frames, so
        # the attack of the first word (or "hey" of "hey pecko") isn't
        # clipped by the debounce wait.
        preroll_audio = self.preroll.drain()
        if preroll_audio.size:
            self.asr.accept_frame(preroll_audio)
            self._turn_audio.append(preroll_audio)
            self._full_turn_audio.append(preroll_audio)
            self._maybe_check_wake(preroll_audio)   # KWS must hear "hey" too, not only ASR
        for lead_frame in self._arming_frames:
            self.asr.accept_frame(lead_frame)
            self._turn_audio.append(lead_frame)
            self._full_turn_audio.append(lead_frame)
            self._maybe_check_wake(lead_frame)
        self._arming_frames = []
        self.state = "LISTENING"

    def _maybe_check_wake(self, frame) -> None:
        if self._armed:
            return
        if self.kws is not None:
            if self.kws.detect(frame):
                self._armed = True
                self._elog.emit("ears", "wake_detected", turn=self.turn, t=self.clock.now(), via="kws")
            return
        text = self.asr.current_text().lower()  # fallback: no KWS model on this checkout
        if WAKE_PHRASE.replace(" ", "") in text.replace(" ", ""):
            self._armed = True
            self._elog.emit("ears", "wake_detected", turn=self.turn, t=self.clock.now(), via="asr_text_fallback")

    def _visible_text(self, text: str) -> str:
        """Strip the wake phrase prefix so Brain never sees "hey pecko"."""
        low = text.lower()
        idx = low.find(WAKE_PHRASE.split()[-1])  # "pecko"
        if idx != -1:
            return text[idx + len(WAKE_PHRASE.split()[-1]):].strip(" ,.!?")
        # ASR often misspells the name ("hey peckle", "hey pecker"): drop "hey/hi <one word>"
        # that starts with "pe" at the very start of the utterance
        return _WAKE_LIKE.sub("", text).strip(" ,.!?")

    def _maybe_emit_partial(self, t_cap: float) -> None:
        if not self._armed:
            return
        text = self._visible_text(self.asr.current_text())
        if not text or text == self._last_partial_text:
            return
        if t_cap - self._last_partial_t < PARTIAL_THROTTLE_S:  # O7
            return
        stable = self._visible_text(self.asr.stable_prefix())
        emit(self.out_stream, **contract.partial(self.turn, text, stable, t_cap))
        self._last_partial_text, self._last_partial_t = text, t_cap
        self._maybe_emit_intent_hint(text, t_cap)

    def _maybe_emit_intent_hint(self, text: str, t_cap: float) -> None:
        """O: cached-TTS hint -- tell Voice early when a partial matches a
        common opener, so it can preload a cached clip (docs/CONTRACT.md)."""
        if self._sent_intent_hint:
            return
        low = text.lower()
        for opener, intent in INTENT_OPENERS.items():
            if low.startswith(opener):
                emit(self.out_stream, **contract.intent_hint(self.turn, intent, t_cap))
                self._sent_intent_hint = True
                return

    def _on_pause_start(self) -> None:
        if not self._armed:
            self.state = "IDLE"  # unarmed speech ended: drop it, nothing was sent
            return
        # O1, endpoint fix (measured): finalize the ASR stream NOW, once.
        # Before, force_update() here was often a no-op (stale/truncated text)
        # and the real decode happened in finish() at the deadline (0.6-0.9 s
        # for Moonshine Small), stacked on top of the silence threshold. Now
        # that decode overlaps the threshold wait, tentative_final carries
        # the same text final will, and the deadline fires with no work left.
        t0 = self.clock.now()
        text_raw, _words = self.asr.finish()
        self._pause_text = self._visible_text(text_raw) or self._visible_text(self.asr.current_text())
        self._paused_frames = []
        self._elog.emit("ears", "asr_pause_finish", turn=self.turn, t=self.clock.now(),
                         ms=round(1000 * (self.clock.now() - t0), 1))
        # O2: only the "fusion" mode pays for Smart Turn -- the fixed-timer
        # ablation baselines (scripts/ablation.py) ignore p_done entirely,
        # so scoring it would just be wasted CPU, skewing the cost comparison.
        p_done = self._score_smart_turn() if self.endpointer.mode == "fusion" else NEUTRAL_P_DONE
        text = self._pause_text
        if self.endpointer.should_send_tentative_final(text, p_done):
            emit(self.out_stream, **contract.tentative_final(self.turn, text, self._t_eos, p_done))
            self._sent_tentative_final = True
            self._elog.emit("ears", "t_eos", turn=self.turn, t=self._t_eos)
        threshold_s = self.endpointer.threshold_ms(text, p_done) / 1000
        self._pause_deadline = self._t_eos + threshold_s
        self._elog.emit("ears", "smart_turn_score", turn=self.turn, t=self.clock.now(), p_done=p_done)

    def _score_smart_turn(self) -> float:
        if self.smart_turn is None or not self._turn_audio:
            return NEUTRAL_P_DONE
        audio = np.concatenate(list(self._turn_audio))
        return self.smart_turn.score(audio)

    def _on_speech_resume(self, t_cap: float) -> None:
        self._pause_deadline = None
        self.endpointer.record_mid_sentence_pause(t_cap - self._t_eos)  # O6
        if self._sent_tentative_final:
            emit(self.out_stream, **contract.cancel(self.turn, t_cap))
            self._sent_tentative_final = False
        # The stream was finalized at pause start: rebuild it from the turn's
        # audio so the transcript continues where it left off (rare path).
        self.asr.begin_utterance()
        for f in self._full_turn_audio:
            self.asr.accept_frame(f)
        for f in self._paused_frames:
            self.asr.accept_frame(f)
        self._full_turn_audio.extend(self._paused_frames)
        self._paused_frames = []
        self._pause_text = None
        self.state = "LISTENING"

    def _finalize(self) -> None:
        text = self._pause_text  # decoded once at pause start; nothing heavy here
        if text is None:
            text_raw, _words = self.asr.finish()
            text = self._visible_text(text_raw) or self._visible_text(self.asr.current_text())
        self._pause_text = None
        self._elog.emit("ears", "asr_final", turn=self.turn, t=self.clock.now(), text=text)
        norm = normalize(text)
        t_endpoint = self.clock.now()
        emit(self.out_stream, **contract.final(self.turn, text, norm, self._t_eos, t_endpoint))
        self._elog.emit("ears", "endpoint", turn=self.turn, t=t_endpoint, delay_s=t_endpoint - self._t_eos)
        self._pause_deadline = None
        self.state = "FOLLOWUP"
        self._followup_start = t_endpoint
        self._armed = False
