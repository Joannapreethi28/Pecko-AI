"""Smart Turn v3.2 int8 backend (picked in ears/SPEC.md and
research/01_EARS_research_v2.md section 5: 8 MB, raw audio in, ~37-65 ms CPU,
23 languages, BSD-2-Clause, 93% on its 1,000-clip test set). This wraps the
ONNX export from huggingface `soniqo/Smart-Turn-v3.2-ONNX`
(smart-turn-v3.2-int8.onnx, re-exported from pipecat-ai/smart-turn-v3,
revision f766f81d3cfd). The ONNX takes Whisper log-mel features (batch, 80, 800), NOT raw audio,
so this module computes them in numpy (see log_mel_features).

O3: intra_op/inter_op threads pinned to 1 and spinning turned off, same as
every other model session in Ears, so idle CPU does not creep up from
Smart Turn's worker threads busy-waiting between calls.

ears/endpointer.py already accepts a `p_done` float with a neutral default
(ears.config.NEUTRAL_P_DONE) -- this class is the thing that produces a real
p_done; wiring it into ears/stage.py is left to whoever owns that file.
"""
import logging

import numpy as np
import onnxruntime as ort

from ears.config import NEUTRAL_P_DONE

SAMPLE_RATE = 16000
WINDOW_SAMPLES = 128000  # 8 s at 16 kHz
N_FFT, HOP, N_MELS = 400, 160, 80

_log = logging.getLogger(__name__)
_MEL = None


def _mel_filters() -> np.ndarray:
    """Slaney-scale, slaney-normalised mel filterbank, shape (80, 201)."""
    global _MEL
    if _MEL is not None:
        return _MEL
    f_sp = 200.0 / 3
    min_log_hz, logstep = 1000.0, np.log(6.4) / 27.0
    min_log_mel = min_log_hz / f_sp

    def hz2mel(f):
        f = np.asarray(f, dtype=np.float64)
        return np.where(f >= min_log_hz,
                        min_log_mel + np.log(np.maximum(f, 1e-9) / min_log_hz) / logstep,
                        f / f_sp)

    def mel2hz(m):
        m = np.asarray(m, dtype=np.float64)
        return np.where(m >= min_log_mel,
                        min_log_hz * np.exp(logstep * (m - min_log_mel)), f_sp * m)

    fft_freqs = np.linspace(0, SAMPLE_RATE / 2, N_FFT // 2 + 1)
    pts = mel2hz(np.linspace(hz2mel(0.0), hz2mel(8000.0), N_MELS + 2))
    fdiff = np.diff(pts)
    ramps = pts[:, None] - fft_freqs[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    fb = np.maximum(0, np.minimum(lower, upper))
    fb *= (2.0 / (pts[2:N_MELS + 2] - pts[:N_MELS]))[:, None]
    _MEL = fb.astype(np.float32)
    return _MEL


_WIN = np.hanning(N_FFT + 1)[:-1].astype(np.float32)  # periodic Hann


def log_mel_features(audio: np.ndarray) -> np.ndarray:
    """Whisper log-mel for the last 8 s of `audio` -> (1, 80, 800) float32.

    Mirrors HF WhisperFeatureExtractor(do_normalize=True) as used by
    pipecat smart-turn predict.py: left-pad/keep END, zero-mean/unit-var,
    centred reflect-padded STFT, drop last frame, log10 clamp, (x+4)/4.
    """
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    window = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
    tail = audio[-WINDOW_SAMPLES:]
    window[WINDOW_SAMPLES - len(tail):] = tail
    window = (window - window.mean()) / np.sqrt(window.var() + 1e-7)

    x = np.pad(window, N_FFT // 2, mode="reflect")
    n_frames = 1 + (len(x) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    spec = np.fft.rfft(x[idx] * _WIN, axis=1)
    power = (spec.real ** 2 + spec.imag ** 2)[:-1].T  # (201, 800)
    mel = _mel_filters() @ power.astype(np.float32)
    logm = np.log10(np.maximum(mel, 1e-10))
    logm = np.maximum(logm, logm.max() - 8.0)
    return ((logm + 4.0) / 4.0).astype(np.float32)[None]


class SmartTurn:
    def __init__(self, model_path: str | None = None):
        if model_path is None:
            model_path = "models/smart_turn/smart-turn-v3.2-int8.onnx"

        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        so.enable_cpu_mem_arena = False   # arena kept ~7 MiB extra for no speed gain (measured)
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        so.add_session_config_entry("session.inter_op.allow_spinning", "0")

        self._session = ort.InferenceSession(
            model_path, sess_options=so, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        self._warned = False

    def score(self, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
        """p(turn done) in [0, 1] for the last 8 s of turn audio.

        Never raises: on any error logs once and returns NEUTRAL_P_DONE.
        """
        try:
            if sample_rate != SAMPLE_RATE:
                raise ValueError(
                    f"SmartTurn expects {SAMPLE_RATE} Hz audio, got {sample_rate}"
                )
            feats = log_mel_features(audio)
            out = float(np.asarray(
                self._session.run(None, {self._input_name: feats})[0]).reshape(-1)[0])
            if not np.isfinite(out):
                raise ValueError("non-finite model output")
            if not 0.0 <= out <= 1.0:  # raw logit -> probability
                out = 1.0 / (1.0 + np.exp(-out))
            return float(out)
        except Exception as e:  # noqa: BLE001
            if not self._warned:
                self._warned = True
                _log.warning("SmartTurn.score failed (%r); returning neutral", e)
            return NEUTRAL_P_DONE
