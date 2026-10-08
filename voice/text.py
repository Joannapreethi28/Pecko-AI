"""Text side of Voice: make Brain text speakable, then cut it into phrases.

normalize(): strip markdown/emoji/URLs, spell out numbers (Indian lakh/crore), ₹, %, times, units, abbreviations.
PhraseChunker: v1 adaptive rule (voice/SPEC.md, solution.md V8)
  - first phrase of a gen: first , . ? ! ; : after >= 2 words, else cut at 6 words  -> fast start
  - later phrases: sentence end; also a comma when the playback buffer is < 300 ms ahead; max 25 words
"""
import re

from num2words import num2words

_URL = re.compile(r"https?://\S+|www\.\S+")
_MD = re.compile(r"[*_#`>\[\]{}|~]")
_EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_NUMS = r"\d(?:[\d,]*\d)?(?:\.\d+)?"
_RUPEE = re.compile(r"(?:₹|\bRs\.?\s?|\bINR\s?)(" + _NUMS + ")")
_PCT = re.compile(r"(" + _NUMS + r")\s?%")
_NUM = re.compile(_NUMS)
_UNITS = {"km": "kilometres", "kg": "kilograms", "°C": "degrees Celsius", "°F": "degrees Fahrenheit",
          "cm": "centimetres", "mm": "millimetres", "GB": "gigabytes", "MB": "megabytes", "ms": "milliseconds"}
_UNIT = re.compile(r"(\d)\s?(" + "|".join(re.escape(u) for u in _UNITS) + r")\b")
_ABBR = [("Dr.", "Doctor"), ("Mr.", "Mister"), ("Mrs.", "Missus"), ("etc.", "et cetera"),
         ("e.g.", "for example"), ("i.e.", "that is"), ("vs.", "versus"), ("&", " and ")]


def _num(s: str) -> str:
    s = s.replace(",", "")
    try:
        w = num2words(float(s) if "." in s else int(s), lang="en_IN")  # lakh / crore
        return w.replace(",", "")  # commas inside a number would make the chunker cut mid-number
    except Exception:
        return s


def _time(m) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    if mi == 0:
        return f"{num2words(h)} o'clock"
    return f"{num2words(h)} {'oh ' + num2words(mi) if mi < 10 else num2words(mi)}"


def normalize(text: str) -> str:
    text = _URL.sub(" I'll skip the link ", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"^\s*(?:[-•]|\d+\.)\s+", "", text, flags=re.M)  # list bullets / numbering
    text = _MD.sub("", text)
    for k, v in _ABBR:
        text = text.replace(k, v)
    text = _TIME.sub(_time, text)
    text = _RUPEE.sub(lambda m: _num(m.group(1)) + " rupees", text)
    text = _PCT.sub(lambda m: _num(m.group(1)) + " percent", text)
    text = _UNIT.sub(lambda m: m.group(1) + " " + _UNITS[m.group(2)], text)
    text = _NUM.sub(lambda m: _num(m.group(0)), text)
    return re.sub(r"\s+", " ", text)


_ANY = re.compile(r"[,.?!;:]")
_SENT = re.compile(r"[.?!;:]")


class PhraseChunker:
    FIRST_MAX_WORDS = 6
    LATER_MAX_WORDS = 25
    LOW_BUFFER_MS = 300

    POLICIES = ("adaptive", "comma", "sentence", "word")

    def __init__(self, buffered_ms=lambda: 0.0, is_opener=lambda phrase: False, policy="adaptive"):
        """is_opener(phrase) -> True if a 1-word phrase is a pre-synthesized opener ("Sure.", "Okay,"),
        which may be cut on its own because it plays instantly from the cache (SPEC risk Q4).
        policy: "adaptive" (shipped v1 rule) or, for the A4 ablation only, "comma" (every , . ? ! ; :),
        "sentence" (sentence ends only) and "word" (every word: the known failure case)."""
        assert policy in self.POLICIES, policy
        self.buffered_ms = buffered_ms
        self.is_opener = is_opener
        self.policy = policy
        self.reset()

    def reset(self):
        self.buf = ""
        self.first = True

    def feed(self, text: str) -> list:
        self.buf += text
        out = []
        while (p := self._cut()) is not None:
            out.append(p)
        return out

    def flush(self) -> list:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []

    def _cut(self):
        if not self.buf.strip():
            return None
        if self.policy == "word":
            m = re.match(r"\s*\S+\s", self.buf)
            return self._take(m.end()) if m else None
        if self.policy == "comma":
            pat, max_words = _ANY, self.LATER_MAX_WORDS
        elif self.policy == "sentence":
            pat, max_words = _SENT, self.LATER_MAX_WORDS
        elif self.first:
            pat, max_words = _ANY, self.FIRST_MAX_WORDS
        else:
            low = self.buffered_ms() < self.LOW_BUFFER_MS
            pat, max_words = (_ANY if low else _SENT), self.LATER_MAX_WORDS
        for m in pat.finditer(self.buf):
            end = m.end()
            if end < len(self.buf) and not self.buf[end].isspace():
                continue  # "3.5", "4,500", "e.g": punctuation inside a token
            if end == len(self.buf) and end >= 2 and self.buf[end - 2].isdigit():
                continue  # LLMs stream digits one token at a time: "4," may become "4,500"
            head = self.buf[:end]
            if len(head.split()) >= 2 or self.is_opener(head.strip()):
                return self._take(end)
        words = list(re.finditer(r"\S+", self.buf))
        if len(words) >= max_words and (len(words) > max_words or self.buf[-1].isspace()):
            return self._take(words[max_words - 1].end())
        return None

    def _take(self, idx):
        phrase, self.buf = self.buf[:idx].strip(), self.buf[idx:]
        self.first = False
        return phrase
