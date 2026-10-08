import os

import numpy as np
import pytest

from ears.backends import turn_smartturn as t
from ears.config import NEUTRAL_P_DONE

MODEL = "models/smart_turn/smart-turn-v3.2-int8.onnx"


def test_features_shape_finite():
    f = t.log_mel_features(np.random.randn(16000).astype(np.float32) * 0.1)
    assert f.shape == (1, 80, 800) and f.dtype == np.float32
    assert np.isfinite(f).all()


def test_score_range_and_exception_neutral():
    if not os.path.exists(MODEL):
        pytest.skip("model missing")
    st = t.SmartTurn(MODEL)
    assert 0.0 <= st.score(np.random.randn(20000).astype(np.float32) * 0.1) <= 1.0
    assert st.score(np.zeros(100), sample_rate=8000) == NEUTRAL_P_DONE

    def boom(*a, **k):
        raise RuntimeError("x")
    st._session.run = boom
    assert st.score(np.zeros(100)) == NEUTRAL_P_DONE
