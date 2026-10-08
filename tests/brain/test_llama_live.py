"""Live tests against a real llama-server. Run: PECKO_LLAMA_PORT=8080 pytest tests/brain/test_llama_live.py"""
import os

import pytest

from brain.llama_client import LlamaClient

PORT = os.environ.get("PECKO_LLAMA_PORT")
pytestmark = pytest.mark.skipif(not PORT, reason="PECKO_LLAMA_PORT not set")

SYSTEM = ("<|im_start|>system\nYou are Pecko, a friendly offline voice assistant. Answer in one or two "
          "short spoken sentences. No lists, no markdown.<|im_end|>\n")


def user(text):
    return f"{SYSTEM}<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


@pytest.fixture(scope="module")
def client():
    c = LlamaClient(port=int(PORT))
    assert c.health()
    return c


def test_system_prompt_base_within_150_tokens(client):
    assert len(client.tokenize(SYSTEM)) <= 150


def test_second_request_reuses_cache(client):
    base = len(client.tokenize(SYSTEM))
    list(client.stream(user("hello"), n_predict=4))
    pieces = list(client.stream(user("what is two plus two"), n_predict=4))
    assert pieces[-1].timings.cache_n >= base - 1


def test_thinking_off(client):
    pieces = list(client.stream(user("what is the capital of france"), n_predict=40))
    reply = "".join(p.text for p in pieces)
    assert reply.strip() and "<think>" not in reply
