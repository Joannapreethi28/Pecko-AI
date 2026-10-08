"""Test doubles for Brain: a llama-server stand-in that needs no model."""
import time

from brain.llama_client import Piece, Timings

DEFAULT_PIECES = ["Paris", " is", " the", " capital", ",", " and", " its", " largest", " city", "."]


class FakeClient:
    """Answers like LlamaClient. `replies` maps a substring of the current user turn to pieces."""

    def __init__(self, replies=None, fail=False, delay=0.0):
        self.replies = replies or {}
        self.fail = fail
        self.delay = delay
        self.healthy = True
        self.calls = []

    def health(self):
        return self.healthy

    def prefill(self, prompt, *, cache_prompt=True):
        self.calls.append(("prefill", prompt))
        if self.fail:
            raise ConnectionResetError("fake server died")
        return Timings(prompt_n=5, cache_n=50)

    def stream(self, prompt, *, n_predict, temperature=0.4, cancel=None, cache_prompt=True):
        self.calls.append(("stream", prompt))
        if self.fail:
            raise ConnectionResetError("fake server died")
        user = prompt.rsplit("<|im_start|>user\n", 1)[-1]
        pieces = next((v for k, v in self.replies.items() if k in user), DEFAULT_PIECES)
        for p in pieces[:n_predict]:
            if cancel is not None and cancel.is_set():
                return
            if self.delay:
                time.sleep(self.delay)
            yield Piece(p)
        yield Piece("", Timings(prompt_n=8, cache_n=60, predicted_n=len(pieces), predicted_ms=100.0))


def wait_until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return bool(pred())
