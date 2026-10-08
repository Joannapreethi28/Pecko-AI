"""Vosk small en-in backend -- the T3 "Survival" tier ASR (docs/CONTRACT.md
tier table: "Vosk small en-in"). Not streaming in the Moonshine/Zipformer
sense (no partial-token events mid-chunk beyond Vosk's own JSON partial
result), but the lightest-weight option: no ONNX runtime involved at all.

Same duck-typed interface as the other ASR backends (start, begin_utterance,
accept_frame, force_update, finish, current_text, stable_prefix,
set_keyterms) so `ears/stage.py` can swap engines per tier transparently.
"""
import json
import pathlib
from dataclasses import dataclass, field

import numpy as np
import vosk

vosk.SetLogLevel(-1)  # Vosk's C++ layer logs to stderr by default; silence it.

SAMPLE_RATE = 16000
_MODEL_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "models" / "vosk" / "vosk-model-small-en-in-0.4"
)


@dataclass
class _UtteranceState:
    text: str = ""
    prev_text: str = ""
    words: list = field(default_factory=list)


class VoskASR:
    def __init__(self, model_dir: pathlib.Path | str = _MODEL_DIR):
        self._model_dir = str(model_dir)
        self._model: vosk.Model | None = None
        self._rec: vosk.KaldiRecognizer | None = None
        self._state = _UtteranceState()

    def start(self) -> None:
        self._model = vosk.Model(self._model_dir)
        # O4 warm-up: push 0.5s of silence through the real decode path.
        warm = vosk.KaldiRecognizer(self._model, SAMPLE_RATE)
        warm.AcceptWaveform(np.zeros(SAMPLE_RATE // 2, dtype=np.int16).tobytes())
        warm.FinalResult()

    def set_keyterms(self, hotwords: list[str]) -> None:
        # Vosk supports a constrained-grammar mode (SetGrammar), not
        # additive decoder bias like Moonshine's keyterms -- a closed
        # vocabulary would break open-domain recognition, so this is
        # intentionally a no-op, not a faked feature.
        pass

    def begin_utterance(self) -> None:
        self._state = _UtteranceState()
        self._rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE)

    @staticmethod
    def _to_pcm16_bytes(frame: np.ndarray) -> bytes:
        return (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

    def accept_frame(self, frame: np.ndarray) -> None:
        self._rec.AcceptWaveform(self._to_pcm16_bytes(frame))
        partial = json.loads(self._rec.PartialResult())
        self._state.prev_text = self._state.text
        self._state.text = partial.get("partial", "")

    def force_update(self) -> None:
        pass  # AcceptWaveform already decodes incrementally; no separate "force a pass" call exists.

    def finish(self) -> tuple[str, list]:
        result = json.loads(self._rec.FinalResult())
        self._state.text = result.get("text", "")
        return self._state.text, self._state.words

    def current_text(self) -> str:
        return self._state.text

    def stable_prefix(self) -> str:
        cur = self._state.text.split()
        prev = self._state.prev_text.split()
        n = 0
        for a, b in zip(cur, prev):
            if a != b:
                break
            n += 1
        return " ".join(cur[:n])
