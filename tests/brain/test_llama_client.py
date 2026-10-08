import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from brain.llama_client import (LlamaClient, LlamaError, Piece, Timings, iter_sse)
from brain.llama_server import LlamaServer, find_llama_server


class FakeLlama:
    """Tiny stand-in for llama-server: SSE stream on /completion, JSON when stream=false."""

    def __init__(self, n_pieces=5, delay=0.0, status=200):
        self.n_pieces, self.delay, self.status = n_pieces, delay, status
        self.last_body = None
        self.disconnected = threading.Event()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/tokenize":
                    data = json.dumps({"tokens": list(range(len(body["content"].split())))}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                outer.last_body = body
                if outer.status != 200:
                    self.send_response(outer.status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                timings = {"prompt_n": 3, "cache_n": 10, "prompt_ms": 5.0,
                           "predicted_n": outer.n_pieces, "predicted_ms": 50.0}
                if not body.get("stream"):
                    data = json.dumps({"content": "", "timings": timings}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for i in range(outer.n_pieces):
                        ev = {"content": f" w{i}", "stop": False}
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(outer.delay)
                    ev = {"content": "", "stop": True, "timings": timings}
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    outer.disconnected.set()
                    return
                # wait briefly for the client to close, to detect disconnects after the fact
                self.close_connection = True

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake():
    f = FakeLlama()
    yield f
    f.close()


def test_iter_sse_parses_data_lines_and_stops_at_done():
    lines = [b": comment\n", b'data: {"content": "a"}\n', b"\n", 'data: {"content": "b"}\n',
             b"data: [DONE]\n", b'data: {"content": "never"}\n']
    assert list(iter_sse(lines)) == [{"content": "a"}, {"content": "b"}]


def test_timings_defaults_and_tps():
    t = Timings.from_json(None)
    assert (t.prompt_n, t.cache_n, t.predicted_n) == (0, 0, 0)
    assert t.decode_tps == 0.0
    t = Timings.from_json({"prompt_n": 3, "cache_n": 10, "predicted_n": 10, "predicted_ms": 500.0})
    assert t.decode_tps == pytest.approx(20.0)


def test_stream_yields_pieces_then_timings(fake):
    c = LlamaClient(port=fake.port)
    pieces = list(c.stream("hi", n_predict=5))
    assert [p.text for p in pieces[:-1]] == [f" w{i}" for i in range(5)]
    assert pieces[-1].text == "" and pieces[-1].timings.cache_n == 10
    assert fake.last_body["stream"] is True and fake.last_body["cache_prompt"] is True
    assert fake.last_body["n_predict"] == 5


def test_cancel_stops_stream_and_disconnects():
    f = FakeLlama(n_pieces=200, delay=0.02)
    try:
        c = LlamaClient(port=f.port)
        cancel = threading.Event()
        got = []
        for p in c.stream("hi", n_predict=200, cancel=cancel):
            got.append(p)
            if len(got) == 2:
                cancel.set()
        assert len(got) == 2
        assert f.disconnected.wait(2.0)
    finally:
        f.close()


def test_prefill_returns_timings(fake):
    t = LlamaClient(port=fake.port).prefill("hello")
    assert t.cache_n == 10 and t.prompt_n == 3
    assert fake.last_body["stream"] is False
    assert fake.last_body["n_predict"] == 0


def test_http_error_raises_llama_error():
    f = FakeLlama(status=500)
    try:
        c = LlamaClient(port=f.port)
        with pytest.raises(LlamaError):
            list(c.stream("x", n_predict=3))
        with pytest.raises(LlamaError):
            c.prefill("x")
    finally:
        f.close()


def test_health_and_tokenize(fake):
    c = LlamaClient(port=fake.port)
    assert c.health() is True
    assert c.tokenize("a b c") == [0, 1, 2]
    assert LlamaClient(port=1).health() is False


def test_server_args_match_spec(tmp_path):
    s = LlamaServer(tmp_path / "m.gguf", exe=tmp_path / "llama-server.exe")
    a = " ".join(s.args())
    for part in ("-np 1", "-t 1", "-tb 2", "-ctk q8_0", "-ctv q8_0", "--host 127.0.0.1", "-c 2048",
                 "--port 8080"):
        assert part in a


def test_find_llama_server(tmp_path):
    d = tmp_path / "b1" / "x"
    d.mkdir(parents=True)
    (d / "llama-server.dll").write_text("")
    exe = d / "llama-server.exe"
    exe.write_text("")
    assert find_llama_server(tmp_path) == exe
