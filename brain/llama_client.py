"""Minimal llama-server client (stdlib only, so it also runs in Termux).

Brain talks to llama-server over HTTP: /completion (SSE streaming), /tokenize, /health.
Cancelling a stream = closing the connection; llama-server stops generating on disconnect.
"""
import http.client
import json
from dataclasses import dataclass
from typing import Iterator, Optional

DEFAULT_PREFILL_N_PREDICT = 1   # probe (windows-dev) showed n_predict=0 returns no timings; 1 token is the fix


class LlamaError(RuntimeError):
    pass


@dataclass
class Timings:
    prompt_n: int = 0        # prompt tokens actually computed this request
    cache_n: int = 0         # prompt tokens reused from the KV cache
    prompt_ms: float = 0.0
    predicted_n: int = 0
    predicted_ms: float = 0.0

    @property
    def decode_tps(self) -> float:
        return self.predicted_n / (self.predicted_ms / 1000.0) if self.predicted_ms > 0 else 0.0

    @classmethod
    def from_json(cls, d) -> "Timings":
        d = d or {}
        return cls(int(d.get("prompt_n", 0)), int(d.get("cache_n", 0)), float(d.get("prompt_ms", 0.0)),
                   int(d.get("predicted_n", 0)), float(d.get("predicted_ms", 0.0)))


@dataclass
class Piece:
    text: str
    timings: Optional[Timings] = None


def iter_sse(lines) -> Iterator[dict]:
    for raw in lines:
        line = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw).strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        yield json.loads(payload)


class LlamaClient:
    def __init__(self, host="127.0.0.1", port=8080, timeout=120.0,
                 prefill_n_predict=DEFAULT_PREFILL_N_PREDICT):
        self.host, self.port, self.timeout = host, port, timeout
        self.prefill_n_predict = prefill_n_predict

    def _request(self, method, path, body=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            data = json.dumps(body).encode() if body is not None else None
            conn.request(method, path, body=data, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise LlamaError(f"{method} {path} failed: {e!r}") from e
        if resp.status != 200:
            detail = resp.read(300)
            conn.close()
            raise LlamaError(f"{method} {path} -> HTTP {resp.status} {detail!r}")
        return conn, resp

    def health(self) -> bool:
        try:
            conn, resp = self._request("GET", "/health")
        except LlamaError:
            return False
        try:
            resp.read()
            return True
        finally:
            conn.close()

    def tokenize(self, text) -> list:
        conn, resp = self._request("POST", "/tokenize", {"content": text})
        try:
            return json.loads(resp.read())["tokens"]
        finally:
            conn.close()

    def prefill(self, prompt, *, cache_prompt=True) -> Timings:
        body = {"prompt": prompt, "n_predict": self.prefill_n_predict, "stream": False,
                "cache_prompt": cache_prompt, "id_slot": 0}
        conn, resp = self._request("POST", "/completion", body)
        try:
            return Timings.from_json(json.loads(resp.read()).get("timings"))
        finally:
            conn.close()

    def stream(self, prompt, *, n_predict, temperature=0.4, cancel=None, cache_prompt=True) -> Iterator[Piece]:
        body = {"prompt": prompt, "n_predict": n_predict, "stream": True, "cache_prompt": cache_prompt,
                "temperature": temperature, "stop": ["<|im_end|>"], "id_slot": 0}
        conn, resp = self._request("POST", "/completion", body)
        try:
            for ev in iter_sse(resp):
                if cancel is not None and cancel.is_set():
                    return
                text = ev.get("content", "")
                if ev.get("stop"):
                    if text:
                        yield Piece(text)
                    yield Piece("", Timings.from_json(ev.get("timings")))
                    return
                if text:
                    yield Piece(text)
        finally:
            conn.close()   # closing mid-stream is the cancel: llama-server stops on client disconnect
