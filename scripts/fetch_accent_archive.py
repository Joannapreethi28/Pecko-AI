"""Phase 1 dataset fetch: pull a small Indian-English subset from the GMU
Speech Accent Archive (CC BY-NC-SA 4.0, non-commercial research/education use,
no login required) via the public OSF API, since ai4bharat/Svarah -- the
dataset ears/research cites -- is gated on HuggingFace and needs a manual
terms-acceptance step we don't have time for.

This is a time-boxed substitute for the spec's "team's own voices" bake-off
set. It is read-speech (every speaker reads the same fixed paragraph), not
spontaneous conversation, so mid-sentence-pause coverage is weaker than the
original plan wanted. That caveat is written into data/clips/SOURCE.md, not
hidden.

Usage: python scripts/fetch_accent_archive.py
"""
import csv
import json
import pathlib
import time
import urllib.request

OSF_NODE = "yh23d"
OSF_API = "https://api.osf.io/v2"
OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "clips"

# Native languages of India represented in the archive's file-naming scheme
# (filename = <native_language><speaker_number>.mp3). A few decades-old entries
# use "panjabi"/"marathi" spelling variants; both are covered defensively.
INDIAN_LANGUAGES = [
    "hindi", "tamil", "telugu", "malayalam", "kannada", "bengali",
    "punjabi", "panjabi", "gujarati", "marathi", "urdu", "konkani",
]
CLIPS_PER_LANGUAGE = 3   # keep the whole set around ~25-30 clips, time-boxed
TRANSCRIPT_TEXT = (
    "Please call Stella. Ask her to bring these things with her from the store: "
    "Six spoons of fresh snow peas, five thick slabs of blue cheese, and maybe a "
    "snack for her brother Bob. We also need a small plastic snake and a big toy "
    "frog for the kids. She can scoop these things into three red bags, and we "
    "will go meet her Wednesday at the train station."
)


def http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode())


def find_mp3_folder_href() -> str:
    data = http_json(f"{OSF_API}/nodes/{OSF_NODE}/files/osfstorage/")
    for item in data["data"]:
        if item["attributes"]["name"] == "mp3_files":
            return item["relationships"]["files"]["links"]["related"]["href"]
    raise RuntimeError("mp3_files folder not found in OSF node")


def list_language_clips(folder_href: str, language: str, limit: int) -> list[dict]:
    url = f"{folder_href}?filter[name]={language}&page[size]={limit}"
    data = http_json(url)
    out = []
    for item in data["data"][:limit]:
        a = item["attributes"]
        out.append({
            "name": a["name"],
            "size": a["size"],
            "download": item["links"]["download"],
        })
    return out


def download(url: str, dest: pathlib.Path) -> None:
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
                f.write(r.read())
            return
        except Exception as e:
            last_err = e
            time.sleep(2 + attempt * 3)
    raise last_err


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    folder_href = find_mp3_folder_href()

    manifest_rows = []
    seen_speakers = set()
    for lang in INDIAN_LANGUAGES:
        try:
            clips = list_language_clips(folder_href, lang, CLIPS_PER_LANGUAGE)
        except Exception as e:
            print(f"  skip {lang}: {e}")
            continue
        for clip in clips:
            speaker_id = clip["name"].replace(".mp3", "")
            if speaker_id in seen_speakers:
                continue
            seen_speakers.add(speaker_id)
            dest = OUT_DIR / clip["name"]
            row = {
                "filename": clip["name"],
                "speaker_id": speaker_id,
                "native_language": lang,
                "transcript": TRANSCRIPT_TEXT,
                "last_word_time_s": "",       # filled by scripts/label_last_word.py (auto, VAD-based)
                "mid_sentence_pause": "",      # filled by scripts/label_last_word.py (auto)
                "label_method": "auto",
            }
            if dest.exists() and dest.stat().st_size == clip["size"]:
                print(f"already have {clip['name']}, skipping")
                manifest_rows.append(row)
                continue
            try:
                print(f"downloading {clip['name']} ({clip['size']} bytes)...")
                download(clip["download"], dest)
                manifest_rows.append(row)
            except Exception as e:
                print(f"  FAILED {clip['name']}: {e}")
            time.sleep(1.0)  # be polite to the OSF API

    manifest_path = OUT_DIR / "MANIFEST.csv"
    with open(manifest_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        w.writeheader()
        w.writerows(manifest_rows)

    print(f"\nDownloaded {len(manifest_rows)} clips -> {OUT_DIR}")
    print(f"Manifest -> {manifest_path}")


if __name__ == "__main__":
    main()
