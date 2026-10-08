"""HTTP contract checks for the evaluator demo and its bounded source access."""
from __future__ import annotations

from datetime import datetime
import http.client
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from frontend.server import DemoRuntime, INDIA_TIME, REPO_ROOT, make_server, safe_file


HAS_ROUTER_DEPS = importlib.util.find_spec("yaml") is not None


class FrontendHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pecko-presentation-")
        cls.root = Path(cls.directory.name)
        for subdir in ("frontend", "brain", "docs", "data/results/voice_samples", "spine/examples"):
            (cls.root / subdir).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / "brain/intents.yaml", cls.root / "brain/intents.yaml")
        (cls.root / "frontend/index.html").write_text("<h1>Pecko</h1>", encoding="utf-8")
        (cls.root / "frontend/server.py").write_text("not public", encoding="utf-8")
        (cls.root / "frontend/evidence.json").write_text('{"schema_version": 1}', encoding="utf-8")
        (cls.root / "docs/solution.md").write_text("<script>example</script>", encoding="utf-8")
        (cls.root / "data/results/report.json").write_text('{"p50": 1}', encoding="utf-8")
        (cls.root / "data/results/voice_samples/sample.wav").write_bytes(b"RIFFtestWAVE")
        (cls.root / "spine/examples/plan.json").write_text('{"turns": []}', encoding="utf-8")
        cls.runtime = DemoRuntime(cls.root)
        cls.health_patch = patch.object(cls.runtime, "model_available", return_value=False)
        cls.health_patch.start()
        cls.server = make_server(0, cls.runtime)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.health_patch.stop()
        cls.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        headers = dict(headers or {})
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
            headers.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), data
        conn.close()
        return result

    def test_static_and_evidence_are_available(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Pecko", body)
        self.assertIn("text/html", headers["Content-Type"])
        status, _, body = self.request("GET", "/api/evidence")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["schema_version"], 1)

    def test_status_honestly_reports_typed_demo(self):
        status, _, body = self.request("GET", "/api/status")
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(result["llm"]["available"])
        self.assertFalse(result["demo"]["audio"])
        self.assertEqual(result["router"]["available"], HAS_ROUTER_DEPS)
        self.assertEqual(result["demo"]["timezone"], "Asia/Kolkata")

    @unittest.skipUnless(HAS_ROUTER_DEPS, "Install frontend/requirements.txt for real router tests")
    def test_actual_router_normalizes_and_resolves_cached_reply(self):
        status, _, body = self.request("POST", "/api/chat", {"text": "  HELLO, Pecko!  "})
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["text"], "Hello! How can I help you?")
        self.assertEqual(result["route"], "cached")
        self.assertEqual(result["intent"], "greeting")
        self.assertEqual(result["normalized_text"], "hello pecko")
        self.assertTrue(result["available"])
        self.assertGreaterEqual(result["elapsed_ms"], 0)
        self.assertFalse(result["audio"])

    @unittest.skipUnless(HAS_ROUTER_DEPS, "Install frontend/requirements.txt for real router tests")
    def test_composed_clock_uses_repository_time_wording(self):
        with patch.object(self.runtime.router, "clock", return_value=datetime(2026, 10, 9, 9, 5, tzinfo=INDIA_TIME)):
            status, _, body = self.request("POST", "/api/chat", {"text": "What time is it?"})
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["route"], "composed")
        self.assertEqual(result["text"], "It's nine oh five in the morning.")

    @unittest.skipUnless(HAS_ROUTER_DEPS, "Install frontend/requirements.txt for real router tests")
    def test_llm_miss_does_not_fabricate_an_answer(self):
        status, _, body = self.request("POST", "/api/chat", {"text": "Explain quantum entanglement"})
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["route"], "llm")
        self.assertEqual(result["reason"], "model_unavailable")
        self.assertFalse(result["available"])
        self.assertIn("not running", result["text"])

    def test_invalid_input_always_returns_a_json_error(self):
        for body in ([], {"text": 123}, {"text": " "}, {"text": "x" * 1001}):
            with self.subTest(body_type=type(body).__name__):
                status, headers, payload = self.request("POST", "/api/chat", body)
                self.assertEqual(status, 400)
                self.assertIn("application/json", headers["Content-Type"])
                self.assertIsInstance(json.loads(payload)["error"]["message"], str)
        status, _, _ = self.request("POST", "/api/chat", "{", {"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/api/chat", "hello")
        self.assertEqual(status, 415)
        status, _, _ = self.request("POST", "/api/chat", {"text": "x" * 17000})
        self.assertEqual(status, 413)

    def test_sources_are_bounded_and_plain_documents_cannot_execute(self):
        status, headers, _ = self.request("GET", "/source/docs/solution.md")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", headers["Content-Security-Policy"])
        for path in ("/source/data/results/report.json", "/source/spine/examples/plan.json",
                     "/source/data/results/voice_samples/sample.wav"):
            self.assertEqual(self.request("GET", path)[0], 200)
        for path in ("/server.py", "/source/brain/prompt.py", "/source/.git/config",
                     "/source/docs/%2e%2e/brain/intents.yaml", "/source/docs/../../README.md",
                     "/source/docs/%5c..%5cREADME.md", "/source/docs/file.md:secret"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_untrusted_browser_origins_and_hosts_are_rejected(self):
        self.assertEqual(self.request("GET", "/api/status", headers={"Host": "example.com"})[0], 403)
        self.assertEqual(self.request("POST", "/api/chat", {"text": "hello"},
                                      {"Origin": "https://example.com"})[0], 403)

    def test_symlink_files_are_not_served(self):
        link = self.root / "docs/linked.md"
        try:
            link.symlink_to(self.root / "docs/solution.md")
        except OSError:
            self.skipTest("Creating symlinks requires platform privileges")
        self.assertIsNone(safe_file(self.root, "docs/linked.md"))
        self.assertEqual(self.request("GET", "/source/docs/linked.md")[0], 404)


class ModelReplyTests(unittest.TestCase):
    def test_generation_uses_local_client_and_filters_hidden_thinking(self):
        from brain.llama_client import Piece
        runtime = DemoRuntime.__new__(DemoRuntime)
        runtime.model_family = "qwen3"
        with patch("brain.llama_client.LlamaClient") as client:
            client.return_value.stream.return_value = iter((Piece("<think>private reasoning</think>"), Piece("The answer is four.")))
            # Real stream returns a generator, whose close() cancels generation.
            client.return_value.stream.return_value = (p for p in client.return_value.stream.return_value)
            result = runtime.generate("What is two plus two?")
            client.assert_called_once_with(host="127.0.0.1", port=8080, timeout=20)
            self.assertIn("What is two plus two?", client.return_value.stream.call_args.args[0])
        self.assertEqual(result["text"], "The answer is four.")
        self.assertTrue(result["available"])

    def test_model_failure_is_explicit(self):
        from brain.llama_client import LlamaError
        runtime = DemoRuntime.__new__(DemoRuntime)
        runtime.model_family = "qwen3"

        def failed_stream(*args, **kwargs):
            raise LlamaError("test unavailable")
            yield

        with patch("brain.llama_client.LlamaClient.stream", failed_stream):
            result = runtime.generate("A question")
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "model_error")


if __name__ == "__main__":
    unittest.main()
