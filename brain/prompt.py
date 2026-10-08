"""Byte-stable prompts. The KV cache is reused only for an identical byte prefix, so: the system
prompt never changes, history is append-only between block trims, and a past reply is rendered exactly as generated
(including the empty think block) so the next turn's prompt extends the previous one."""
from __future__ import annotations

import re
from dataclasses import dataclass

SYSTEM_PROMPT = (
    "You are Pecko, an offline voice assistant running on this device. "
    "Answer in one or two short spoken sentences. Give the answer first, then at most one short reason. "
    "No lists, no markdown, no symbols, no emoji. Spell out numbers in words. "
    "If you don't know, say so in one sentence. "
    "You are offline and cannot browse, check live data or open apps."
)
# keep letters/digits/apostrophes; Devanagari and Tamil blocks kept whole (their vowel signs are not \w)
_PUNCT = re.compile(r"[^\w\s'ऀ-ॿ஀-௿]")


def normalize(text: str) -> str:
    return " ".join(_PUNCT.sub(" ", text.lower()).split())


@dataclass(frozen=True)
class Template:
    system: str
    user_open: str
    user_close: str
    assistant_open: str
    assistant_close: str


TEMPLATES = {
    # Qwen3 non-thinking: pre-fill an empty think block so no silent "thinking" seconds
    "qwen3": Template("<|im_start|>system\n{sys}<|im_end|>\n", "<|im_start|>user\n", "<|im_end|>\n",
                      "<|im_start|>assistant\n<think>\n\n</think>\n\n", "<|im_end|>\n"),
    # LFM2: BOS <|startoftext|> is added by llama-server's tokenizer, not written here
    "lfm2": Template("<|im_start|>system\n{sys}<|im_end|>\n", "<|im_start|>user\n", "<|im_end|>\n",
                     "<|im_start|>assistant\n", "<|im_end|>\n"),
}


class PromptBuilder:
    def __init__(self, family: str = "qwen3", system: str = SYSTEM_PROMPT, max_turns: int = 3,
                 keep_after_trim: int = 1):
        self.family, self.max_turns, self._system_text = family, max_turns, system
        self.keep_after_trim = keep_after_trim
        self.t = TEMPLATES[family]
        self._system = self.t.system.format(sys=system)
        self._turns: list[tuple[str, str]] = []

    def base(self) -> str:
        parts = [self._system]
        for user, reply in self._turns:
            parts += [self.t.user_open, user, self.t.user_close, self.t.assistant_open, reply, self.t.assistant_close]
        return "".join(parts)

    def partial(self, user: str) -> str:
        """Early-prefill prompt: the user turn is still open, so this is a byte prefix of final()."""
        return self.base() + self.t.user_open + user

    def final(self, user: str) -> str:
        return self.partial(user) + self.t.user_close + self.t.assistant_open

    def add_turn(self, user: str, reply: str) -> bool:
        """Append a turn. On overflow cut history to the last `keep_after_trim` turns in one block and
        return True: a sliding window would shift the prefix (and miss the KV cache) on every turn."""
        self._turns.append((user, reply))
        if len(self._turns) <= self.max_turns:
            return False
        keep = min(self.keep_after_trim, self.max_turns)
        self._turns = self._turns[len(self._turns) - keep:] if keep else []
        return True

    def rebuild(self, family: str) -> "PromptBuilder":
        nb = PromptBuilder(family, self._system_text, self.max_turns, self.keep_after_trim)
        nb._turns = list(self._turns)
        return nb

    @property
    def n_turns(self) -> int:
        return len(self._turns)

    def clear(self) -> None:
        self._turns.clear()
