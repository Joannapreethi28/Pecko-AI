"""Fast unit tests for Ears' pure-logic modules (no model loading): the
endpointer's evidence bins/thresholds/O6 adaptive cap, O10 normalization,
and the contract message builders. The full state machine against real
audio is covered by the end-to-end run in scripts/measure.py -- loading
Moonshine/Silero in a unit test would make this suite slow for no extra
confidence.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np

from ears import contract
from ears.config import NOISE_RMS_THRESHOLD, SILENCE_THRESHOLDS_MS
from ears.endpointer import Endpointer
from ears.noise import NoiseFloorEstimator
from ears.normalize import ends_with_dangling_word, looks_sentence_complete, normalize


def test_evidence_bin_confident_done():
    ep = Endpointer()
    assert ep.evidence_bin("what is the capital of france", p_done=0.8) == "confident_done"


def test_evidence_bin_dangling_word_overrides_high_p_done():
    ep = Endpointer()
    assert ep.evidence_bin("what is the capital of and", p_done=0.9) == "low_or_dangling"


def test_threshold_ms_matches_config_for_confident_and_mid_bins():
    ep = Endpointer()
    assert ep.threshold_ms("a complete sentence", p_done=0.8) == SILENCE_THRESHOLDS_MS["confident_done"]
    assert ep.threshold_ms("a complete sentence", p_done=0.5) == SILENCE_THRESHOLDS_MS["mid"]


def test_adaptive_cap_defaults_to_max_with_no_history():
    ep = Endpointer()
    assert ep.adaptive_cap_ms() == SILENCE_THRESHOLDS_MS["low_or_dangling_cap_max_ms"]


def test_adaptive_cap_tracks_median_pause_o6():
    ep = Endpointer()
    for pause_s in (0.3, 0.32, 0.28):
        ep.record_mid_sentence_pause(pause_s)
    # median ~0.3s * 1.5 = 450ms, within [500,1200] clamp -> clamps to 500
    assert ep.adaptive_cap_ms() == SILENCE_THRESHOLDS_MS["low_or_dangling_cap_min_ms"]


def test_adaptive_cap_resets_on_new_session():
    ep = Endpointer()
    ep.record_mid_sentence_pause(0.9)
    ep.reset_session()
    assert ep.adaptive_cap_ms() == SILENCE_THRESHOLDS_MS["low_or_dangling_cap_max_ms"]


def test_should_send_tentative_final_requires_p_done_and_complete_sentence():
    ep = Endpointer()
    assert ep.should_send_tentative_final("what is the weather like", p_done=0.65)
    assert not ep.should_send_tentative_final("what is the weather like", p_done=0.5)
    assert not ep.should_send_tentative_final("and", p_done=0.9)


def test_ends_with_dangling_word():
    assert ends_with_dangling_word("tell me about the")
    assert not ends_with_dangling_word("tell me about paris")


def test_looks_sentence_complete():
    assert looks_sentence_complete("what is the capital of france?")
    assert not looks_sentence_complete("tell me about the")


def test_normalize_strips_fillers_and_applies_hotwords():
    assert normalize("um so i live in coimbatore") == "so i live in coimbatore"
    assert normalize("I need five lakh rupees") == "i need five lakh rupees"


def test_contract_final_message_shape():
    msg = contract.final(turn=3, text="Hi there.", norm="hi there", t_eos=1.0, t_endpoint=1.2)
    assert msg == {
        "type": "final", "turn": 3, "text": "Hi there.", "norm": "hi there",
        "t_eos": 1.0, "t_endpoint": 1.2,
    }


def test_noise_floor_estimator_tracks_quiet_vs_loud():
    quiet = NoiseFloorEstimator()
    for _ in range(50):
        quiet.update(np.random.normal(0, 0.001, 512).astype(np.float32))
    assert not quiet.is_noisy()

    loud = NoiseFloorEstimator()
    for _ in range(50):
        loud.update(np.random.normal(0, NOISE_RMS_THRESHOLD * 3, 512).astype(np.float32))
    assert loud.is_noisy()


def test_noise_floor_estimator_resets():
    ep = NoiseFloorEstimator()
    for _ in range(50):
        ep.update(np.random.normal(0, NOISE_RMS_THRESHOLD * 3, 512).astype(np.float32))
    assert ep.is_noisy()
    ep.reset()
    assert not ep.is_noisy()


def test_contract_partial_and_cancel_shapes():
    p = contract.partial(turn=1, text="what is", stable="what", t=0.5)
    assert p["type"] == "partial" and p["stable"] == "what"
    c = contract.cancel(turn=1, t=0.6)
    assert c == {"type": "cancel", "turn": 1, "t": 0.6}
