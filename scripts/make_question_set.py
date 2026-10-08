"""24 synthetic spoken questions for paired Pecko vs B0 runs (Piper lessac-medium voice, same recipe as
scripts/make_question_wavs.py). Labelled SYNTHETIC: TTS speech, not human; a sanity set, not the held-out set.

    python scripts/make_question_set.py   # -> data/clips/synthetic24/q01..q24.wav (16 kHz mono, 0.5 s lead silence)
"""
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "models" / "vits-piper-en_US-lessac-medium"
QUESTIONS = [
    "What is the capital of Japan?", "How many days are in a leap year?", "Who painted the Mona Lisa?",
    "What is the boiling point of water?", "Why is the sky blue?", "How far is the moon from the earth?",
    "What is the largest planet in our solar system?", "Who invented the telephone?",
    "How many continents are there?", "What do bees make?", "What is the tallest mountain in the world?",
    "How many hours are in a week?", "What language is spoken in Brazil?", "What is photosynthesis?",
    "Who was the first person to walk on the moon?", "What is the square root of eighty one?",
    "Which ocean is the largest?", "How many players are on a cricket team?", "What is the capital of Australia?",
    "Can you suggest a quick breakfast idea?", "What gas do plants take in?", "How many legs does an insect have?",
    "What is the chemical symbol for gold?", "Tell me a fun fact about elephants.",
]

tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(M / "en_US-lessac-medium.onnx"),
                                               tokens=str(M / "tokens.txt"), data_dir=str(M / "espeak-ng-data")),
    num_threads=1)))
out = ROOT / "data" / "clips" / "synthetic24"
out.mkdir(parents=True, exist_ok=True)
for i, q in enumerate(QUESTIONS, 1):
    a = tts.generate("Hey Pecko, " + q, sid=0, speed=1.0)
    pcm = resample_poly(np.asarray(a.samples, dtype=np.float32), 16000, a.sample_rate).astype(np.float32)
    pcm = np.concatenate([np.zeros(8000, np.float32), pcm])
    sf.write(out / f"q{i:02d}.wav", pcm, 16000)
    print(out / f"q{i:02d}.wav", f"{len(pcm) / 16000:.2f}s", q)
