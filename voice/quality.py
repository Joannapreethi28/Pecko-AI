"""Objective quality check for quantized voices: mel-cepstral distortion (MCD, dB) vs the fp32 pack of the
same size, on the sample sentence `python -m voice.bench` saved to data/results/voice_samples/.

    python -m voice.quality

Simplified MCD: 13 cepstral coefficients from a 40-band mel filterbank (c0 excluded, silent frames dropped),
DTW-aligned, 10/ln10·sqrt(2Σ) form. NOT comparable to published (SPTK mel-cepstrum) MCD values; use it only
RELATIVELY, e.g. against the medium-vs-high and medium-vs-low distance printed as a reference scale.
Pure numpy (no extra installs), so it runs the same on Windows and Ubuntu.
"""
import json
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "results" / "voice_samples"
SR, NFFT, HOP, NMEL, NCEP = 22050, 1024, 256, 40, 13


def _load(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def _mel_fb():
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)
    pts = imel(np.linspace(mel(0), mel(SR / 2), NMEL + 2))
    bins = np.floor((NFFT + 1) * pts / SR).astype(int)
    fb = np.zeros((NMEL, NFFT // 2 + 1))
    for i in range(NMEL):
        a, b, c = bins[i], bins[i + 1], bins[i + 2]
        fb[i, a:b] = (np.arange(a, b) - a) / max(1, b - a)
        fb[i, b:c] = (c - np.arange(b, c)) / max(1, c - b)
    return fb


def _mcep(x):
    nz = np.flatnonzero(np.abs(x) > 0.01)
    x = x[nz[0]:nz[-1]] if len(nz) else x
    frames = np.lib.stride_tricks.sliding_window_view(x, NFFT)[::HOP] * np.hanning(NFFT)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    mel = spec @ _mel_fb().T
    energy = mel.sum(1)
    mel = mel[energy > energy.max() * 1e-4]              # drop silent frames (< -40 dB of the loudest)
    logmel = 0.5 * np.log(mel + mel.max() * 1e-6)        # log AMPLITUDE (MCD convention), relative floor
    n = np.arange(NMEL)
    dct = np.cos(np.pi / NMEL * (n[None, :] + 0.5) * np.arange(NCEP + 1)[:, None]) * np.sqrt(2 / NMEL)  # orthonormal DCT-II
    return (logmel @ dct.T)[:, 1:]                       # drop c0 (energy)


def _dtw_cost(a, b):
    d = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    n, m = d.shape
    acc = np.full((n + 1, m + 1), np.inf)
    acc[0, 0] = 0
    steps = np.zeros((n + 1, m + 1), int)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            k = np.argmin((acc[i - 1, j - 1], acc[i - 1, j], acc[i, j - 1]))
            prev = (acc[i - 1, j - 1], acc[i - 1, j], acc[i, j - 1])[k]
            acc[i, j] = d[i - 1, j - 1] + prev
            steps[i, j] = (steps[i - 1, j - 1], steps[i - 1, j], steps[i, j - 1])[k] + 1
    return acc[n, m] / steps[n, m]


def mcd(ref, test):
    return 10 / np.log(10) * np.sqrt(2) * _dtw_cost(_mcep(ref), _mcep(test))


def main():
    out = {}
    print("Relative MCD vs fp32 of the same size (0 = identical; compare with the reference rows)")
    ref = {n: SAMPLES / f"vits-piper-en_US-lessac-{n}.wav" for n in ("low", "medium", "high")}
    if all(p.exists() for p in ref.values()):
        m = _load(ref["medium"])
        for other in ("low", "high"):
            v = round(float(mcd(m, _load(ref[other]))), 2)
            out[f"reference medium-vs-{other}"] = {"mcd_db": v}
            print(f"  reference: medium fp32 vs {other} fp32 (different model, same speaker): {v:5.2f}")
    for size in ("low", "medium", "high"):
        base = SAMPLES / f"vits-piper-en_US-lessac-{size}.wav"
        if not base.exists():
            continue
        ref = _load(base)
        for q in ("fp16", "int8"):
            p = SAMPLES / f"vits-piper-en_US-lessac-{size}-{q}.wav"
            if p.exists():
                t = _load(p)
                v = round(float(mcd(ref, t)), 2)
                out[f"{size}-{q}"] = {"mcd_db": v, "dur_ratio": round(len(t) / len(ref), 3)}
                print(f"  {size:6s} {q}: MCD {v:5.2f} dB · duration ratio {len(t) / len(ref):.3f}")
    (ROOT / "data" / "results" / "voice_quality.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
