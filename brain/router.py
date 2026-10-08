"""Intent router: answers common phrases without the LLM (cached clip or composed time/date text).

Why: a cached clip or a composed sentence has no prefill/decode cost, so first audio for these
turns is just Voice playing a ready clip. The risk is a false hit (answering a real question with
a canned clip), so fuzzy matching needs *entity agreement* and stays conservative.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import yaml

try:  # rapidfuzz is a pip dep; Termux (phone) may not have it
    from rapidfuzz import fuzz as _fuzz

    def _token_set_ratio(a: str, b: str) -> float:
        return _fuzz.token_set_ratio(a, b)
except ImportError:  # pragma: no cover - exercised on Termux only
    from difflib import SequenceMatcher

    def _token_set_ratio(a: str, b: str) -> float:
        ta, tb = set(a.split()), set(b.split())
        sect = " ".join(sorted(ta & tb))
        da = " ".join(sorted(ta - tb))
        db = " ".join(sorted(tb - ta))
        t0 = sect
        t1 = (sect + " " + da).strip()
        t2 = (sect + " " + db).strip()
        r = lambda x, y: 100.0 * SequenceMatcher(None, x, y).ratio()
        if sect:
            return max(r(t0, t1), r(t0, t2), r(t1, t2))
        return r(t1, t2)

INTENTS_PATH = Path(__file__).with_name("intents.yaml")

_LEAD = {"hey", "hi", "hello", "ok", "okay", "so", "um", "uh", "please", "pecko"}
_FILLER = {"please", "pecko", "hey", "hi", "hello", "um", "uh", "so", "okay", "ok", "oh", "well",
           "just", "the", "a", "there", "again", "now", "yeah", "very", "much"}
# share of an intent template's content words the query must cover (blocks "you" -> "thank you")
_MIN_COVERAGE = 0.75


@dataclass(frozen=True)
class Route:
    kind: str  # "cached" | "composed" | "llm"
    intent: Optional[str] = None
    clip: Optional[str] = None
    text: Optional[str] = None
    score: float = 0.0


_LLM = Route("llm")

# ---- composed answers -------------------------------------------------------------------------
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty"}
_ORD = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
        "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth",
        "seventeenth", "eighteenth", "nineteenth", "twentieth", "twenty-first", "twenty-second",
        "twenty-third", "twenty-fourth", "twenty-fifth", "twenty-sixth", "twenty-seventh",
        "twenty-eighth", "twenty-ninth", "thirtieth", "thirty-first"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _minute_words(m: int) -> str:
    if m < 20:
        return _ONES[m]
    t, o = divmod(m, 10)
    return _TENS[t] + (f"-{_ONES[o]}" if o else "")


def time_words(dt: datetime) -> str:
    h12 = dt.hour % 12 or 12
    if dt.minute == 0:
        clock = f"{_ONES[h12]} o'clock"
    elif dt.minute < 10:
        clock = f"{_ONES[h12]} oh {_ONES[dt.minute]}"
    else:
        clock = f"{_ONES[h12]} {_minute_words(dt.minute)}"
    h = dt.hour
    if h < 5:  # the plan's "(0,5) -> at night" example wins over the bare "morning < 12"
        part = "at night"
    elif h < 12:
        part = "in the morning"
    elif h < 17:
        part = "in the afternoon"
    elif h < 21:
        part = "in the evening"
    else:
        part = "at night"
    return f"It's {clock} {part}."


def date_words(dt: datetime) -> str:
    return f"Today is {_DAYS[dt.weekday()]}, {_MONTHS[dt.month - 1]} {_ORD[dt.day]}."


def day_words(dt: datetime) -> str:
    return f"It's {_DAYS[dt.weekday()]}."


_TAIL = r"(?: please| pecko)*"
_TIME_RE = re.compile(
    r"(?:what time is it(?: right now| now| currently)?|what(?:'s| is) the (?:current )?time"
    r"(?: right now| now)?|tell me the (?:current )?time|current time|time now|what time do you have)"
    + _TAIL)
_DATE_RE = re.compile(
    r"(?:what(?:'s| is) (?:the |today's )?date(?: today| is it)?|what date is it(?: today)?"
    r"|today's date|tell me (?:the |today's )?date)" + _TAIL)
_DAY_RE = re.compile(
    r"(?:what day is (?:it|today)(?: today)?|which day is (?:it|today)|what(?:'s| is) the day"
    r"(?: today)?|what day of the week is it|tell me the day)" + _TAIL)


class Router:
    def __init__(self, intents: list[dict], clock: Callable[[], datetime] = datetime.now):
        self.clock = clock
        self._intents = {i["name"]: i for i in intents}
        self._exact: dict[str, str] = {}
        for i in intents:
            for t in i["templates"]:
                if t in self._exact:
                    raise ValueError(f"template {t!r} in both {self._exact[t]} and {i['name']}")
                self._exact[t] = i["name"]
        self._fuzzy = [i for i in intents if i.get("fuzzy")]
        self._words = {i["name"]: {w for t in i["templates"] for w in t.split()} for i in intents}

    @classmethod
    def load(cls, path: Path | str = INTENTS_PATH,
             clock: Callable[[], datetime] = datetime.now) -> "Router":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        intents = data["intents"] if isinstance(data, dict) else data
        return cls(intents, clock)

    def _cached(self, name: str, score: float) -> Route:
        i = self._intents[name]
        return Route("cached", intent=name, clip=i["clip"], score=score)

    def route(self, norm: str, threshold: float = 90.0) -> Route:
        norm = norm.strip()
        if not norm:
            return self._cached("didnt_catch", 100.0)
        if norm in self._exact:
            return self._cached(self._exact[norm], 100.0)

        words = norm.split()
        while words and words[0] in _LEAD:
            words = words[1:]
        stripped = " ".join(words)

        if stripped:
            now = self.clock()
            if _TIME_RE.fullmatch(stripped):
                return Route("composed", intent="time", text=time_words(now), score=100.0)
            if _DATE_RE.fullmatch(stripped):
                return Route("composed", intent="date", text=date_words(now), score=100.0)
            if _DAY_RE.fullmatch(stripped):
                return Route("composed", intent="day", text=day_words(now), score=100.0)
            if stripped in self._exact:
                return self._cached(self._exact[stripped], 100.0)

        qwords = norm.split()
        best: tuple[float, Optional[str]] = (0.0, None)
        for i in self._fuzzy:
            name = i["name"]
            allowed = self._words[name] | _FILLER
            if any(w not in allowed for w in qwords):  # entity agreement
                continue
            for t in i["templates"]:
                twords = t.split()
                tfill = _FILLER - set(twords)  # a template's own words (e.g. "hello") count
                tcontent = {w for w in twords if w not in tfill}
                qcontent = {w for w in qwords if w not in tfill}
                if not tcontent or len(qcontent & tcontent) / len(tcontent) < _MIN_COVERAGE:
                    continue
                score = _token_set_ratio(norm, t)
                if score > best[0]:
                    best = (score, name)
        if best[1] and best[0] >= threshold:
            return self._cached(best[1], best[0])
        return _LLM
