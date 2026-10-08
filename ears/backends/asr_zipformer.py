"""sherpa-onnx streaming Zipformer backend -- the T2 "Starved" tier engine
(docs/CONTRACT.md tier table: "Zipformer 20M int8"). Challenger ASR from
ears/SPEC.md's bake-off list; used here as the lighter fallback when Moonshine
Tiny is still too heavy for the declared cap, not because it beat Moonshine
on accuracy (we never ran that bake-off -- see ears/RESULTS.md).

Same duck-typed interface as `asr_moonshine.MoonshineASR` (start, set_tier
N/A here since this backend IS a single tier, begin_utterance, accept_frame,
force_update, finish, current_text, stable_prefix, set_keyterms) so
`ears/stage.py` can swap engines per tier without caring which one is live.

O3: num_threads=1 is the only knob sherpa-onnx's OnlineRecognizer exposes
for thread control; no explicit spinning toggle, same honest limitation
already noted for the KWS backend.
"""
import pathlib
from dataclasses import dataclass, field

import sherpa_onnx

SAMPLE_RATE = 16000
_MODEL_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "models" / "zipformer_asr" / "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17"
)


@dataclass
class _UtteranceState:
    text: str = ""
    prev_text: str = ""
    words: list = field(default_factory=list)


class ZipformerASR:
    def __init__(self, model_dir: pathlib.Path | str = _MODEL_DIR, use_int8: bool = True):
        self._model_dir = pathlib.Path(model_dir)
        self._use_int8 = use_int8
        self._recognizer: sherpa_onnx.OnlineRecognizer | None = None
        self._stream = None
        self._state = _UtteranceState()

    def start(self) -> None:
        suffix = ".int8.onnx" if self._use_int8 else ".onnx"
        self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(self._model_dir / "tokens.txt"),
            encoder=str(self._model_dir / f"encoder-epoch-99-avg-1{suffix}"),
            decoder=str(self._model_dir / f"decoder-epoch-99-avg-1{suffix}"),
            joiner=str(self._model_dir / f"joiner-epoch-99-avg-1{suffix}"),
            num_threads=1,
            sample_rate=SAMPLE_RATE,
        )
        # O4 warm-up: push 0.5s of silence through the real decode path.
        warm = self._recognizer.create_stream()
        warm.accept_waveform(SAMPLE_RATE, [0.0] * (SAMPLE_RATE // 2))
        while self._recognizer.is_ready(warm):
            self._recognizer.decode_stream(warm)

    def set_keyterms(self, hotwords: list[str]) -> None:
        # sherpa-onnx's contextual biasing (`hotwords_file`/`context_scores`)
        # is a constructor-time option, not a runtime setter -- rebuilding
        # the recognizer here would cost a full reload per turn. Not
        # supported at runtime, said honestly rather than faked.
        pass

    def begin_utterance(self) -> None:
        self._state = _UtteranceState()
        self._stream = self._recognizer.create_stream()

    def accept_frame(self, frame) -> None:
        self._stream.accept_waveform(SAMPLE_RATE, frame.tolist() if hasattr(frame, "tolist") else frame)
        self._drain()

    def force_update(self) -> None:
        self._drain()

    def _drain(self) -> None:
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)
        self._state.prev_text = self._state.text
        self._state.text = self._recognizer.get_result(self._stream)

    def finish(self) -> tuple[str, list]:
        # The streaming encoder holds back its last frames: without ~0.66 s of tail silence the last
        # word is lost ("does a spider" for "...have"). sherpa-onnx's own examples pad the same way.
        self._stream.accept_waveform(SAMPLE_RATE, [0.0] * int(SAMPLE_RATE * 0.66))
        self._stream.input_finished()
        self._drain()
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
