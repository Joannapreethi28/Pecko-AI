"""Convert downloaded accent-archive MP3s to 16 kHz mono WAV (the format
ears/audio_io.py's WavFrameSource expects, matching the mic's native rate)."""
import pathlib
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

CLIPS_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "clips"
TARGET_SR = 16000


def convert(mp3_path: pathlib.Path) -> pathlib.Path:
    data, sr = sf.read(mp3_path)
    if data.ndim > 1:
        data = data.mean(axis=1)  # mono
    if sr != TARGET_SR:
        g = np.gcd(sr, TARGET_SR)
        up, down = TARGET_SR // g, sr // g
        data = resample_poly(data, up, down)
    wav_path = mp3_path.with_suffix(".wav")
    sf.write(wav_path, data.astype(np.float32), TARGET_SR, subtype="PCM_16")
    return wav_path


def main() -> None:
    mp3s = sorted(CLIPS_DIR.glob("*.mp3"))
    print(f"converting {len(mp3s)} clips to {TARGET_SR} Hz mono wav...")
    for mp3 in mp3s:
        wav = convert(mp3)
        print(f"  {mp3.name} -> {wav.name}")


if __name__ == "__main__":
    main()
