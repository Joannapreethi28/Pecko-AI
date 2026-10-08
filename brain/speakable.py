"""Make LLM text safe to speak: no markdown, emoji, URLs or hidden thinking."""
import re

_URL = re.compile(r"https?://\S+|www\.\S+")
_BULLET = re.compile(r"(?m)^\s*(?:[-•*]|\d+[.)])\s+")
_MD = re.compile(r"[*_`#>|~]+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.?!;:])")
_SPACES = re.compile(r"\s+")


def clean(text: str) -> str:
    text = _URL.sub(" ", text)
    text = _BULLET.sub(" ", text)
    text = _MD.sub("", text)
    text = _EMOJI.sub("", text)
    text = text.replace("&", " and ")
    text = _SPACES.sub(" ", text).strip()
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


def _partial_tag_len(s: str, tag: str) -> int:
    for k in range(min(len(tag) - 1, len(s)), 0, -1):
        if s.endswith(tag[:k]):
            return k
    return 0


class ThinkFilter:
    """Drops everything between <think> and </think>, even when a tag is split across pieces."""
    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buf, self._inside = "", False

    def feed(self, piece: str) -> str:
        self._buf += piece
        out = []
        while True:
            if self._inside:
                j = self._buf.find(self.CLOSE)
                if j < 0:
                    self._buf = self._buf[-(len(self.CLOSE) - 1):]
                    return "".join(out)
                self._buf, self._inside = self._buf[j + len(self.CLOSE):], False
            else:
                i = self._buf.find(self.OPEN)
                if i < 0:
                    keep = _partial_tag_len(self._buf, self.OPEN)
                    out.append(self._buf[:len(self._buf) - keep])
                    self._buf = self._buf[len(self._buf) - keep:]
                    return "".join(out)
                out.append(self._buf[:i])
                self._buf, self._inside = self._buf[i + len(self.OPEN):], True

    def flush(self) -> str:
        rest = "" if self._inside else self._buf
        self._buf = ""
        return rest
