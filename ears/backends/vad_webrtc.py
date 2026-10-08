"""WebRTC VAD -- the T3 "Survival" tier VAD (docs/CONTRACT.md tier table).
No ML model, no ONNX session: this is the cheapest possible speech/silence
detector, which is exactly the point of the bottom tier.

webrtcvad only accepts 10/20/30 ms frames (not our pipeline's 32 ms frame
size), so each call uses the first 20 ms (320 samples) of the frame and
drops the trailing 12 ms -- a deliberate, said-plainly approximation, not a
precision VAD at this tier. Hangover/triggered state machine is hand-rolled
here (webrtcvad itself is a single is_speech() call, no streaming iterator
like Silero's), mirroring SileroVAD's start/end event interface so
`ears/stage.py` doesn't need to know which VAD is live.
"""
import numpy as np
import webrtcvad

SAMPLE_RATE = 16000
SUBFRAME_MS = 20
SUBFRAME_SAMPLES = SAMPLE_RATE * SUBFRAME_MS // 1000  # 320


class WebRTCVAD:
    def __init__(self, mode: int = 2, min_silence_ms: int = 200):
        self._mode = mode
        self._vad = webrtcvad.Vad(mode)
        self._min_silence_frames = max(1, min_silence_ms // SUBFRAME_MS)
        self._triggered = False
        self._silence_count = 0
        self._sample_pos = 0

    def process(self, frame: np.ndarray) -> dict | None:
        sub = frame[:SUBFRAME_SAMPLES]
        pcm16 = (np.clip(sub, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        is_speech = self._vad.is_speech(pcm16, SAMPLE_RATE)

        event = None
        if is_speech:
            self._silence_count = 0
            if not self._triggered:
                self._triggered = True
                event = {"start": self._sample_pos}
        elif self._triggered:
            self._silence_count += 1
            if self._silence_count >= self._min_silence_frames:
                self._triggered = False
                self._silence_count = 0
                event = {"end": self._sample_pos}
        self._sample_pos += len(frame)
        return event

    def set_threshold(self, _threshold: float) -> None:
        # webrtcvad has no continuous sensitivity knob like Silero's
        # probability threshold -- only the discrete 0-3 "mode" set at
        # construction. Not supported at runtime, said honestly.
        pass

    def reset(self) -> None:
        self._triggered = False
        self._silence_count = 0
