"""The torch-free Silero VAD must give the same events, at the same samples, as the torch one."""
import glob

import numpy as np
import pytest

sf = pytest.importorskip("soundfile")
pytest.importorskip("silero_vad")

from ears.backends.vad_silero import SileroVAD
from ears.backends.vad_silero_ort import SileroVADOrt

WAVS = sorted(glob.glob("data/clips/synthetic24/*.wav")) + sorted(glob.glob("data/clips/*.wav"))


def _run(vad, x, flip_at=None):
    evs = []
    for i, k in enumerate(range(0, len(x) - 511, 512)):
        if flip_at is not None and i == flip_at:
            vad.set_threshold(0.8)
        ev = vad.process(x[k:k + 512])
        if ev:
            evs.append((i, ev, vad._iterator.current_sample))
    return evs


@pytest.mark.skipif(not WAVS, reason="no WAVs (run scripts/make_question_set.py)")
def test_same_events_as_torch_version():
    a, b = SileroVAD(threshold=0.5), SileroVADOrt(threshold=0.5)
    n = 0
    for w in WAVS[:12]:
        x, sr = sf.read(w, dtype="float32")
        if sr != 16000 or x.ndim != 1:
            continue
        x = np.concatenate([np.zeros(8000, np.float32), x, np.zeros(16000, np.float32)])
        a.reset(), b.reset()
        ea, eb = _run(a, x, flip_at=40), _run(b, x, flip_at=40)
        assert ea == eb, w
        n += len(ea)
    assert n > 0


def test_ears_does_not_import_torch():
    import subprocess
    import sys
    code = "import sys, ears.stage; print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"
