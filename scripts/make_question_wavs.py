"""Synthetic spoken questions for loop tests (Piper lessac-medium voice).
Labelled SYNTHETIC: not human speech, never use for headline numbers.

    python scripts/make_question_wavs.py   # -> data/clips/synthetic/q*.wav (16 kHz mono, 0.5 s lead silence)
"""
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "models" / "vits-piper-en_US-lessac-medium"
QUESTIONS = ["Hey Pecko, what is the capital of France?", "Hey Pecko, how many legs does a spider have?",
             "Hey Pecko, who wrote Romeo and Juliet?", "Hey Pecko, thank you."]

tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(M / "en_US-lessac-medium.onnx"),
                                               tokens=str(M / "tokens.txt"), data_dir=str(M / "espeak-ng-data")),
    num_threads=1)))
out = ROOT / "data" / "clips" / "synthetic"
out.mkdir(parents=True, exist_ok=True)
for i, q in enumerate(QUESTIONS, 1):
    a = tts.generate(q, sid=0, speed=1.0)
    pcm = resample_poly(np.asarray(a.samples, dtype=np.float32), 16000, a.sample_rate).astype(np.float32)
    pcm = np.concatenate([np.zeros(8000, np.float32), pcm])
    sf.write(out / f"q{i}.wav", pcm, 16000)
    print(out / f"q{i}.wav", f"{len(pcm) / 16000:.2f}s", q)
