"""Download Voice models into models/ once, before going offline. Works on Windows and Ubuntu.

    python voice/get_models.py            # default set: lessac low + medium in fp32 / fp16 / int8
    python voice/get_models.py --all      # also lessac high (for the benchmark grid)
    python voice/get_models.py --list     # show what is present

Never called at runtime: VoiceStage.start() only reads from models/.
"""
import argparse
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"

DEFAULT = [f"vits-piper-en_US-lessac-{q}{v}" for q in ("low", "medium") for v in ("", "-fp16", "-int8")]
HIGH = [f"vits-piper-en_US-lessac-high{v}" for v in ("", "-fp16", "-int8")]


def fetch(name: str) -> None:
    dest = MODELS / name
    if dest.is_dir() and any(dest.glob("*.onnx")):
        print(f"  ok      {name}")
        return
    url = BASE + name + ".tar.bz2"
    print(f"  get     {name} ...", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        arc = Path(tmp) / (name + ".tar.bz2")
        with urllib.request.urlopen(url) as r, open(arc, "wb") as f:
            shutil.copyfileobj(r, f)
        with tarfile.open(arc, "r:bz2") as t:
            t.extractall(MODELS, filter="data") if sys.version_info >= (3, 12) else t.extractall(MODELS)
    print(f"  done    {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="include lessac-high variants")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    MODELS.mkdir(exist_ok=True)
    if a.list:
        for d in sorted(MODELS.glob("vits-piper-*")):
            mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6
            print(f"  {d.name:40s} {mb:7.1f} MB")
        return
    names = DEFAULT + (HIGH if a.all else [])
    print(f"Downloading {len(names)} voice packs into {MODELS}")
    for n in names:
        fetch(n)


if __name__ == "__main__":
    main()
