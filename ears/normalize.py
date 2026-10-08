"""O10: normalized text (for cache lookup / endpointer cues) + hotword
substitution. Keeps the display `text` untouched and produces a separate
`norm` field, matching docs/CONTRACT.md's final-message shape."""
import re

from ears.config import DANGLING_WORDS, HOTWORDS

_FILLERS = {"um", "uh", "er", "ah"}
_HOTWORD_MAP = {h.replace(" ", ""): h for h in HOTWORDS}  # collapsed-form -> canonical


def normalize(text: str) -> str:
    words = re.findall(r"[a-z0-9']+", text.lower())
    words = [w for w in words if w not in _FILLERS]
    out = []
    for w in words:
        out.append(_HOTWORD_MAP.get(w, w))
    return " ".join(out)


def ends_with_dangling_word(text: str) -> bool:
    words = re.findall(r"[a-z']+", text.lower())
    return bool(words) and words[-1] in DANGLING_WORDS


def looks_sentence_complete(text: str) -> bool:
    stripped = text.strip()
    return stripped.endswith((".", "?", "!")) or (
        not ends_with_dangling_word(text) and len(stripped.split()) >= 3
    )
