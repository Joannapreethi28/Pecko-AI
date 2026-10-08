"""Piper voices on sherpa-onnx: one ONNX thread, warm-up at load, fixed output rate, clip finishing."""
import time
from pathlib import Path

import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
OUT_SR = 22050          # playback stream rate (lessac medium/high native; low is resampled)
SPEED = 1.05            # slightly faster than default: shorter audio, still natural

# Voice ladder (docs/CONTRACT.md tier table). Same speaker (lessac) at every neural tier, so cached clips and
# live audio always match. T0/T1 choice is provisional until the Ubuntu-under-cap bench (voice/RESULTS.md).
#   engine: what synthesizes uncached text · cache: which voice's pre-made clips are played
TIERS = {
    0: {"engine": "vits-piper-en_US-lessac-medium", "cache": "vits-piper-en_US-lessac-medium", "note": "full"},
    1: {"engine": "vits-piper-en_US-lessac-low", "cache": "vits-piper-en_US-lessac-low", "note": "tight"},
    2: {"engine": "vits-piper-en_US-lessac-low", "cache": "vits-piper-en_US-lessac-low", "note": "starved: low + cache"},
    3: {"engine": "espeak-ng", "cache": "vits-piper-en_US-lessac-low", "note": "survival: cache + espeak-ng"},
}
PHONE_TIER = 2                                        # phone profile = laptop T2 (mobile/SPEC.md)
TIER_PACKS = {n: t["engine"] for n, t in TIERS.items()}  # backwards-compatible name


def make_engine(name: str, threads: int = 1, warmup: int = 2):
    """Engine factory: 'espeak-ng' or a Piper pack directory name under models/."""
    return EspeakEngine() if name == "espeak-ng" else TTSEngine(name, threads=threads, warmup=warmup)


class TTSEngine:
    def __init__(self, pack: str, threads: int = 1, warmup: int = 2):
        d = MODELS / pack
        onnx = next(d.glob("*.onnx"), None)
        if onnx is None:
            raise FileNotFoundError(f"{d} has no .onnx; run: python voice/get_models.py")
        self.pack = pack
        t = time.monotonic()
        self.tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(onnx), tokens=str(d / "tokens.txt"), data_dir=str(d / "espeak-ng-data")),
                num_threads=threads, provider="cpu"),
            max_num_sentences=1))
        self.native_sr = self.tts.sample_rate
        self.load_s = time.monotonic() - t
        for _ in range(warmup):  # cold start is several times slower
            self.synth("warm up the voice")

    def synth(self, text: str) -> np.ndarray:
        """Text -> float32 PCM at OUT_SR."""
        a = self.tts.generate(text, sid=0, speed=SPEED)
        x = np.asarray(a.samples, dtype=np.float32)
        if a.sample_rate != OUT_SR and len(x):
            n = int(round(len(x) * OUT_SR / a.sample_rate))
            x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
        return x


FADE_S = 0.008
LOUDNESS_PEAK = 0.8


def finish_clip(x: np.ndarray, phrase: str) -> np.ndarray:
    """Trim edge silence, one loudness target, 8 ms fades, pause sized by the final punctuation."""
    nz = np.flatnonzero(np.abs(x) > 0.01)
    if len(nz):
        x = x[max(0, nz[0] - 160): nz[-1] + 160]
    x = x.astype(np.float32, copy=True)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0:
        x *= LOUDNESS_PEAK / peak
    f = min(int(FADE_S * OUT_SR), len(x) // 2)
    if f:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
        x[:f] *= ramp
        x[-f:] *= ramp[::-1]
    end = phrase.rstrip()[-1:]
    pause = 0.22 if end in ".?!" else 0.10 if end in ",;:" else 0.04
    return np.concatenate([x, np.zeros(int(pause * OUT_SR), np.float32)])


class EspeakEngine:
    """espeak-ng formant synthesizer via its CLI (`--stdout` WAV). Robotic, but ~0 RAM, tiny CPU, no model files.
    Survival tier T3 and the per-phrase emergency fallback. Ubuntu: `sudo apt install espeak-ng`;
    Windows: `winget install eSpeak-NG.eSpeak-NG`."""

    WIN_PATHS = [r"C:\Program Files\eSpeak NG\espeak-ng.exe", r"C:\Program Files (x86)\eSpeak NG\espeak-ng.exe"]

    def __init__(self, voice="en-us", wpm=175, threads=1, warmup=1):
        import shutil
        self.exe = shutil.which("espeak-ng") or next((p for p in self.WIN_PATHS if Path(p).exists()), None)
        if self.exe is None:
            raise FileNotFoundError("espeak-ng not found (apt install espeak-ng / winget install eSpeak-NG.eSpeak-NG)")
        self.pack, self.voice, self.wpm = "espeak-ng", voice, wpm
        self.native_sr = 22050
        t = time.monotonic()
        for _ in range(warmup):
            self.synth("ok")
        self.load_s = time.monotonic() - t

    def synth(self, text: str) -> np.ndarray:
        import io
        import subprocess
        import wave
        out = subprocess.run([self.exe, "--stdout", "-v", self.voice, "-s", str(self.wpm), text],
                             capture_output=True, check=True, timeout=10).stdout
        with wave.open(io.BytesIO(out)) as w:
            sr = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        if sr != OUT_SR and len(x):
            n = int(round(len(x) * OUT_SR / sr))
            x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
        return x
