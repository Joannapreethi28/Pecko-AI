"""Ears constants: tier ladder, endpointer starting thresholds, hotwords.
Values are the v1/v2 starting points from ears/SPEC.md and docs/CONTRACT.md's
tier table -- not yet calibrated against measured data (Phase 4 replaces the
threshold numbers once we have real endpoint-delay measurements).
"""

# docs/CONTRACT.md tier ladder, Ears column.
TIERS = {
    0: {"name": "T0 Full", "asr": "moonshine-small", "vad": "silero", "endpointer": "fusion"},
    1: {"name": "T1 Tight", "asr": "moonshine-tiny", "vad": "silero", "endpointer": "fusion"},
    2: {"name": "T2 Starved", "asr": "zipformer-20m-int8", "vad": "silero", "endpointer": "text_cues_timer"},
    3: {"name": "T3 Survival", "asr": "vosk-small-en-in", "vad": "webrtc", "endpointer": "push_to_talk"},
    "phone": {"name": "Phone profile", "asr": "zipformer-20m-int8", "vad": "silero", "endpointer": "text_cues_timer"},
}

# ears/SPEC.md v1 endpoint rule starting values (ms), keyed by the fused evidence bin.
# "confident_done": p_done>=0.7 and no dangling word.
# "mid":            p_done in [0.4, 0.7).
# "low_or_dangling": p_done<0.4 or a dangling word -- uses the adaptive cap (O6), not a fixed value.
SILENCE_THRESHOLDS_MS = {
    "confident_done": 150,
    "mid": 300,
    "low_or_dangling_cap_min_ms": 500,
    "low_or_dangling_cap_max_ms": 1200,
}
ADAPTIVE_CAP_MULTIPLIER = 1.5  # O6: cap = median(mid-sentence pause) * 1.5, clamped to [cap_min, cap_max]

# Smart Turn interface default when the real model isn't wired yet (Phase 5 stretch).
NEUTRAL_P_DONE = 0.5

DANGLING_WORDS = {"and", "the", "of", "um", "so"}

# O10: likely judge/venue words, kept in a normalized (lowercase) form.
HOTWORDS = ["coimbatore", "karunya", "chennai", "tamil nadu", "rupees", "lakh", "crore", "pecko"]

PARTIAL_THROTTLE_S = 0.150  # O7: at most one partial per 150 ms, only on change.
PREROLL_MS = 400
FRAME_MS = 32
FOLLOWUP_WINDOW_S = 8.0  # ARMED window after a final, before falling back to IDLE.
MIN_SPEECH_MS = 150  # debounce: ignore VAD 'start' blips shorter than this before arming

WAKE_PHRASE = "hey pecko"

# VAD threshold tiers (ears/research/01_EARS_research_v2.md section 4:
# "threshold 0.5 (0.6 in noise; 0.8 while Voice plays)"). Playing takes
# priority over the noise tier (set directly in Ears.on_playback_state).
VAD_THRESHOLD_NORMAL = 0.5
VAD_THRESHOLD_NOISY = 0.6
VAD_THRESHOLD_PLAYING = 0.8

# Noise floor (EWMA of frame RMS over confirmed-silence frames). Starting
# value, not calibrated against a measured noisy room -- said plainly.
NOISE_EWMA_ALPHA = 0.05
NOISE_RMS_THRESHOLD = 0.02

# O10 cached-TTS hint: common openers worth telling Voice about early so it
# can preload a cached clip (docs/CONTRACT.md's `intent_hint`).
INTENT_OPENERS = {
    "what is": "question",
    "what's": "question",
    "who is": "question",
    "can you": "request",
    "could you": "request",
    "hello": "greeting",
    "hi pecko": "greeting",
    "thank you": "thanks",
    "thanks": "thanks",
}
