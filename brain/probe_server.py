"""Probe a running llama-server for behaviours Brain relies on.

python -m brain.probe_server --port 8080 --label qwen3-0.6b
Writes data/results/probe_<label>.json. Standalone on purpose (own ChatML), so it works for any model.
"""
import argparse
import json
import time
from pathlib import Path

from brain.llama_client import LlamaClient

SYSTEM = ("<|im_start|>system\nYou are Pecko, a friendly offline voice assistant. Answer in one or two "
          "short spoken sentences. No lists, no markdown.<|im_end|>\n")
GEN_TAIL = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def final(text):
    return f"{SYSTEM}<|im_start|>user\n{text}{GEN_TAIL}"


def lcp(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def probe(client: LlamaClient) -> dict:
    out = {}
    # 1. does prefill with n_predict=0 work?
    try:
        t = LlamaClient(port=client.port, prefill_n_predict=0).prefill(final("hello"))
        out["n_predict_0_ok"] = t.predicted_n == 0 and t.prompt_n + t.cache_n > 0
    except Exception as e:
        out["n_predict_0_ok"] = False
        out["n_predict_0_error"] = repr(e)[:200]
    # 2. cache reuse of the system prompt
    list(client.stream(final("hello"), n_predict=2))
    p = list(client.stream(final("what is two plus two"), n_predict=2))
    out["cache_reuse_tokens"] = p[-1].timings.cache_n
    out["system_tokens"] = len(client.tokenize(SYSTEM))
    # 3. does closing the connection stop generation?
    it = client.stream(final("tell me a very long story about a dragon"), n_predict=300)
    for i, piece in enumerate(it):
        if i == 3:
            break
    it.close()
    t0 = time.monotonic()
    client.prefill(final("hi"))
    out["disconnect_prefill_ms"] = round((time.monotonic() - t0) * 1000, 1)
    out["disconnect_stops_generation"] = out["disconnect_prefill_ms"] < 500
    # 4. rewind: prefill one question, then ask a different one; how much cache is kept?
    a, b = "what is the weather in chennai today", "what is the capital of france"
    client.prefill(final(a))
    pieces = list(client.stream(final(b), n_predict=4))
    out["rewind_cache_n"] = pieces[-1].timings.cache_n
    out["rewind_lcp_tokens"] = lcp(client.tokenize(final(a)), client.tokenize(final(b)))
    # 5. thinking leak
    reply = "".join(x.text for x in client.stream(final("what is the capital of france"), n_predict=40))
    out["think_leak"] = "<think>" in reply
    out["sample_reply"] = reply.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    res = probe(LlamaClient(port=args.port))
    path = Path("data/results") / f"probe_{args.label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    print("wrote", path, "(windows-dev, not judged)")


if __name__ == "__main__":
    main()
