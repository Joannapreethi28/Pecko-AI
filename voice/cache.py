"""Voice audio cache (voice/SPEC.md "Cache layers", solution.md §2 bonus "cached TTS").

L4  intent clips   : every `say` in brain/intents.yaml, pre-synthesized; played on {"type":"cached","clip":id}.
C   composed clock : Brain's composed time/date/day sentences rebuilt from small pre-made pieces
                     ("It's three" + "forty-five" + "in the afternoon.") so they need no synthesis.
L2  openers        : short stock phrases that often start a reply ("Sure.", "Sorry,"), exact normalized match.
L3  runtime memo   : every phrase synthesized this session (LRU, byte budget).

Clips are made with the exact live voice + settings (risk C3) and stored per pack in voice/cache/<pack>/,
with a manifest so any change of text, speed or clip finishing regenerates only what changed.

    python -m voice.cache --build [--pack vits-piper-en_US-lessac-medium]   # prebuild before going offline
"""
import hashlib
import json
import re
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import yaml

from .engine import FADE_S, LOUDNESS_PEAK, OUT_SR, SPEED, finish_clip

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(__file__).resolve().parent / "cache"
INTENTS = ROOT / "brain" / "intents.yaml"
VERSION = 1
MEMO_BUDGET_MB = 40
PIECE_GAP_S = 0.035      # silence between composed pieces

OPENERS = ["Sure.", "Sure,", "Yes.", "Yes,", "No.", "No,", "Okay.", "Okay,", "Of course.", "Sorry,",
           "I'm not sure.", "I'm not sure,", "I don't know.", "Good question.", "Well,", "Hello!",
           "I can't do that.", "Let me think."]

# Composed pieces: must match brain/router.py time_words / date_words / day_words exactly.
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty"}
_ORD = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
        "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
        "nineteenth", "twentieth", "twenty-first", "twenty-second", "twenty-third", "twenty-fourth",
        "twenty-fifth", "twenty-sixth", "twenty-seventh", "twenty-eighth", "twenty-ninth", "thirtieth",
        "thirty-first"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_PARTS = ["at night", "in the morning", "in the afternoon", "in the evening"]


def _minute(m):
    if m == 0:
        return "o'clock"
    if m < 10:
        return f"oh {_ONES[m]}"
    if m < 20:
        return _ONES[m]
    t, o = divmod(m, 10)
    return _TENS[t] + (f"-{_ONES[o]}" if o else "")


def composed_pieces() -> dict:
    """piece id -> text to synthesize."""
    p = {f"h_{h}": f"It's {_ONES[h]}" for h in range(1, 13)}
    p.update({f"m_{m}": _minute(m) for m in range(60)})
    p.update({f"part_{i}": f"{t}." for i, t in enumerate(_PARTS)})
    p.update({f"today_{d}": f"Today is {d}," for d in _DAYS})
    p.update({f"month_{m}": m for m in _MONTHS})
    p.update({f"ord_{i}": f"{_ORD[i]}." for i in range(1, 32)})
    p.update({f"day_{d}": f"It's {d}." for d in _DAYS})
    return p


_RE_TIME = re.compile(r"^It's (\w+) (o'clock|oh \w+|[\w-]+) (at night|in the morning|in the afternoon|in the evening)\.$")
_RE_DATE = re.compile(r"^Today is (\w+), (\w+) ([\w-]+)\.$")
_RE_DAY = re.compile(r"^It's (" + "|".join(_DAYS) + r")\.$")


def compose_ids(text: str):
    """Brain composed sentence -> list of piece ids, or None if it is not one of the known forms."""
    t = text.strip()
    m = _RE_DAY.match(t)
    if m:
        return [f"day_{m.group(1)}"]
    m = _RE_TIME.match(t)
    if m and m.group(1) in _ONES[1:13]:
        h = _ONES.index(m.group(1))
        mins = {_minute(i): i for i in range(60)}
        if m.group(2) in mins:
            return [f"h_{h}", f"m_{mins[m.group(2)]}", f"part_{_PARTS.index(m.group(3))}"]
    m = _RE_DATE.match(t)
    if m and m.group(1) in _DAYS and m.group(2) in _MONTHS and m.group(3) in _ORD[1:]:
        return [f"today_{m.group(1)}", f"month_{m.group(2)}", f"ord_{_ORD.index(m.group(3))}"]
    return None


def key(phrase: str) -> str:
    """Exact-match key: lowercase words + the final punctuation class (it decides the trailing pause)."""
    words = re.sub(r"[^a-z0-9' ]", "", phrase.lower().replace("-", " ")).split()
    end = phrase.rstrip()[-1:]
    return " ".join(words) + ("|." if end in ".?!" else "|," if end in ",;:" else "|")


def load_intents(path=INTENTS) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {it["clip"]: it["say"] for it in data["intents"]}


class AudioCache:
    def __init__(self, layers=("L2", "L3", "L4", "C")):
        self.layers = set(layers)
        self.intents, self.openers, self.pieces = {}, {}, {}
        self.intent_text = {}
        self.memo, self.memo_bytes = OrderedDict(), 0
        self.pack = None

    # ---- build / load ---------------------------------------------------------------
    def build(self, engine, normalize, pack=None) -> dict:
        """Load the clips of voice `pack` (default engine.pack) from disk; synthesize missing or stale ones only
        when `engine` IS that voice. T3 loads lessac-low clips while its engine is espeak-ng (clips must never be
        made by a different voice, risk C3), so missing clips are skipped there and counted in `missing`."""
        pack = pack or engine.pack
        can_make = engine is not None and engine.pack == pack
        self.pack = pack
        d = CACHE_DIR / pack
        d.mkdir(parents=True, exist_ok=True)
        fp = hashlib.sha1(f"{VERSION}|{SPEED}|{FADE_S}|{LOUDNESS_PEAK}|{OUT_SR}".encode()).hexdigest()[:10]
        man_path = d / "manifest.json"
        man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
        if man.get("fp") != fp:
            man = {"fp": fp, "clips": {}}
        t0, made, missing = time.perf_counter(), 0, 0
        self.intent_text = load_intents() if INTENTS.exists() else {}
        want = {**{f"intent__{c}": t for c, t in self.intent_text.items()},
                **{f"open__{key(t)}": t for t in OPENERS},
                **{f"piece__{p}": t for p, t in composed_pieces().items()}}
        loaded = {}
        for cid, text in want.items():
            f = d / (hashlib.sha1(cid.encode()).hexdigest()[:16] + ".npy")
            if man["clips"].get(cid) == text and f.exists():
                loaded[cid] = np.load(f)
                continue
            if not can_make:
                missing += 1
                continue
            raw = engine.synth(normalize(text))
            pcm = finish_clip(raw, text) if not cid.startswith("piece__") else _piece(raw)
            np.save(f, pcm)
            man["clips"][cid] = text
            loaded[cid] = pcm
            made += 1
        man_path.write_text(json.dumps(man, indent=0), encoding="utf-8")
        self.intents = {c[8:]: a for c, a in loaded.items() if c.startswith("intent__")}
        self.openers = {c[6:]: a for c, a in loaded.items() if c.startswith("open__")}
        self.pieces = {c[7:]: a for c, a in loaded.items() if c.startswith("piece__")}
        self.memo.clear()
        self.memo_bytes = 0
        return {"pack": pack, "clips": len(loaded), "synthesized": made, "missing": missing,
                "build_ms": round((time.perf_counter() - t0) * 1000), "mb": round(self.size_mb(), 1)}

    # ---- lookups ----------------------------------------------------------------------
    def intent(self, clip):
        return self.intents.get(clip) if "L4" in self.layers else None

    def compose(self, text):
        if "C" not in self.layers:
            return None
        ids = compose_ids(text)
        if not ids or any(i not in self.pieces for i in ids):
            return None
        gap = np.zeros(int(PIECE_GAP_S * OUT_SR), np.float32)
        out = []
        for i, pid in enumerate(ids):
            out += [self.pieces[pid]] + ([gap] if i < len(ids) - 1 else [])
        return finish_clip(np.concatenate(out), text)

    def lookup(self, phrase):
        """Return (pcm, layer) or (None, None) for a normalized phrase."""
        k = key(phrase)
        if "L2" in self.layers and k in self.openers:
            return self.openers[k], "L2"
        if "L3" in self.layers and k in self.memo:
            self.memo.move_to_end(k)
            return self.memo[k], "L3"
        return None, None

    def remember(self, phrase, pcm):
        if "L3" not in self.layers:
            return
        k = key(phrase)
        if k in self.memo:
            return
        self.memo[k] = pcm
        self.memo_bytes += pcm.nbytes
        while self.memo_bytes > MEMO_BUDGET_MB * 1e6 and self.memo:
            _, old = self.memo.popitem(last=False)
            self.memo_bytes -= old.nbytes

    def size_mb(self):
        return (sum(a.nbytes for a in self.intents.values()) + sum(a.nbytes for a in self.openers.values())
                + sum(a.nbytes for a in self.pieces.values()) + self.memo_bytes) / 1e6


def _piece(x):
    """Composed piece: trim edges and normalize loudness, but no trailing pause (pieces are joined tightly)."""
    nz = np.flatnonzero(np.abs(x) > 0.01)
    if len(nz):
        x = x[max(0, nz[0] - 80): nz[-1] + 80]
    x = x.astype(np.float32, copy=True)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0:
        x *= LOUDNESS_PEAK / peak
    f = min(int(0.004 * OUT_SR), len(x) // 2)
    if f:
        r = np.linspace(0.0, 1.0, f, dtype=np.float32)
        x[:f] *= r
        x[-f:] *= r[::-1]
    return x


if __name__ == "__main__":
    import argparse
    from .engine import TIER_PACKS, TTSEngine
    from .text import normalize
    ap = argparse.ArgumentParser(prog="python -m voice.cache")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--pack", default=TIER_PACKS[0])
    a = ap.parse_args()
    if a.build:
        print(AudioCache().build(TTSEngine(a.pack), normalize))
