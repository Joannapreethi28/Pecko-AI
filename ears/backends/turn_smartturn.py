"""Smart Turn v3.2 int8 backend (picked in ears/SPEC.md and
research/01_EARS_research_v2.md section 5: 8 MB, raw audio in, ~37-65 ms CPU,
23 languages, BSD-2-Clause, 93% on its 1,000-clip test set). This wraps the
ONNX export from huggingface `soniqo/Smart-Turn-v3.2-ONNX`
(smart-turn-v3.2-int8.onnx, re-exported from pipecat-ai/smart-turn-v3,
revision f766f81d3cfd). The Whisper log-mel front end (including the
zero-mean / unit-variance waveform normalisation) is embedded in the ONNX
graph, so this wrapper only has to build the fixed 8 s / 128000-sample
window -- no manual feature extraction needed.

O3: intra_op/inter_op threads pinned to 1 and spinning turned off, same as
every other model session in Ears, so idle CPU does not creep up from
Smart Turn's worker threads busy-waiting between calls.

ears/endpointer.py already accepts a `p_done` float with a neutral default
(ears.config.NEUTRAL_P_DONE) -- this class is the thing that produces a real
p_done; wiring it into ears/stage.py is left to whoever owns that file.
"""
import numpy as np
import onnxruntime as ort

SAMPLE_RATE = 16000
WINDOW_SAMPLES = 128000  # 8 s at 16 kHz -- the model's fixed input shape


class SmartTurn:
    def __init__(self, model_path: str | None = None):
        if model_path is None:
            model_path = "models/smart_turn/smart-turn-v3.2-int8.onnx"

        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        so.add_session_config_entry("session.inter_op.allow_spinning", "0")

        self._session = ort.InferenceSession(
            model_path, sess_options=so, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name

    def score(self, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
        """Returns p(turn done) in [0, 1] for the given turn audio.

        Pass the whole current turn (up to 8 s), not just the last chunk --
        the model's own usage note. Shorter clips are zero-padded at the
        front (oldest-first padding, most recent audio ends at the last
        sample) exactly as the model card specifies; longer clips are
        truncated to the most recent 8 s.
        """
        if sample_rate != SAMPLE_RATE:
            raise ValueError(
                f"SmartTurn expects {SAMPLE_RATE} Hz audio, got {sample_rate}"
            )

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        window = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
        tail = audio[-WINDOW_SAMPLES:]
        window[WINDOW_SAMPLES - len(tail):] = tail

        outputs = self._session.run(None, {self._input_name: window[None, :]})
        return float(outputs[0][0, 0])
