"""Cut a streamed reply into speakable chunks for Voice (brain/SPEC.md 'Chunking to Voice')."""
from __future__ import annotations

from typing import Optional

CUTS = ",.?!;:"
SENTENCE_END = ".?!;"
MAX_WORDS = 25


def _last_space_cut(buf: str) -> int:
    i = buf.rfind(" ")
    return len(buf) if i <= 0 else i + 1


class Chunker:
    """First chunk: first , . ? ! ; : after >= 2 words, or after 6 pieces at a word boundary.
    Later chunks: at . ? ! ; or at , : once the chunk has >= 4 words; never more than 25 words.
    Punctuation glued to the next character (3.5, 1,000, 3:45, x.y) is never a cut; a '.' ',' or ':'
    right after a digit at the end of the buffer waits one piece (it may become 3.5)."""

    def __init__(self, first_min_words: int = 2, first_max_pieces: int = 6,
                 later_comma_words: int = 4, first_done: bool = False):
        self.first_min_words = first_min_words
        self.first_max_pieces = first_max_pieces
        self.later_comma_words = later_comma_words
        self.chunks_out = 1 if first_done else 0
        self._buf = ""
        self._pieces = 0

    def push(self, piece: str) -> list[str]:
        if not piece:
            return []
        self._buf += piece
        self._pieces += 1
        out = []
        while (cut := self._find_cut()) is not None:
            out.append(self._buf[:cut])
            self._buf = self._buf[cut:]
            self.chunks_out += 1
        return out

    def flush(self) -> Optional[str]:
        rest, self._buf = self._buf, ""
        if rest.strip():
            self.chunks_out += 1
            return rest
        return None

    def _find_cut(self) -> Optional[int]:
        buf, first = self._buf, self.chunks_out == 0
        for i, ch in enumerate(buf):
            if ch not in CUTS:
                continue
            at_end = i == len(buf) - 1
            if not at_end and not buf[i + 1].isspace():
                continue
            if at_end and ch in ".,:" and i > 0 and buf[i - 1].isdigit():
                return None
            words = len(buf[:i + 1].split())
            if first:
                if words >= self.first_min_words:
                    return i + 1
            elif ch in SENTENCE_END or words >= self.later_comma_words:
                return i + 1
        n_words = len(buf.split())
        if first and self._pieces >= self.first_max_pieces and n_words >= self.first_min_words:
            cut = _last_space_cut(buf)
            return cut if len(buf[:cut].split()) >= self.first_min_words else None
        if not first and n_words > MAX_WORDS:
            return _last_space_cut(buf)
        return None
