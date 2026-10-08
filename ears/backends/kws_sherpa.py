"""sherpa-onnx open-vocabulary KWS backend (ears/SPEC.md's lead pick: gigaspeech
3.3M model, any phrase, no retraining, Apache 2.0). Model downloaded to
`models/sherpa_kws/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01/`.

Custom-phrase encoding: "HEY PECKO" -> BPE pieces via the model's own
`bpe.model` (verified every piece exists in `tokens.txt`, same pattern as the
shipped example "HEY SIRI" -> "▁HE Y ▁S I RI"): `▁HE Y ▁P E CK O`, written to
`pecko_keywords.txt` next to the model files.

This is the real alternative to `ears/stage.py`'s current ASR-transcript-text
wake check -- a tiny dedicated KWS model instead of running the full ASR
during every idle-listening frame. Swap it in by constructing `SherpaKWS` in
`Ears.start()` and calling `detect()` instead of `_maybe_check_wake()`'s text
match; left to the coordinator to wire in and A/B the idle-CPU difference,
per ears/RESULTS.md's resume plan.

O3 note (honest, not glossed over): sherpa-onnx's `KeywordSpotter` exposes
`num_threads` but no explicit spinning toggle -- same limitation already
noted for moonshine-voice in asr_moonshine.py.
"""
import pathlib

import numpy as np
import sherpa_onnx

SAMPLE_RATE = 16000
_MODEL_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "models" / "sherpa_kws" / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
)


class SherpaKWS:
    def __init__(self, model_dir: pathlib.Path | str = _MODEL_DIR, num_threads: int = 1):
        model_dir = pathlib.Path(model_dir)
        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
            decoder=str(model_dir / "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
            joiner=str(model_dir / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
            keywords_file=str(model_dir / "pecko_keywords.txt"),
            num_threads=num_threads,
            sample_rate=SAMPLE_RATE,
        )
        self._stream = self._spotter.create_stream()

    def detect(self, frame: np.ndarray) -> bool:
        """Feed one 16 kHz mono float32 frame. Returns True exactly on the
        frame where the keyword is recognized."""
        self._stream.accept_waveform(SAMPLE_RATE, frame)
        hit = False
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            result = self._spotter.get_result(self._stream)  # "" if no keyword hit yet
            if result:
                hit = True
                self._spotter.reset_stream(self._stream)
        return hit

    def reset(self) -> None:
        self._stream = self._spotter.create_stream()
