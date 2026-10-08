from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from spine.process import EngineProcess, validate_health_url


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.errors = []
        self.failed = Event()

    def make_process(self, code):
        def failure(message):
            self.errors.append(message)
            self.failed.set()
        process = EngineProcess([sys.executable, "-u", "-c", code],
                                Path(self.folder.name) / "engine.log", failure)
        self.addCleanup(process.stop)
        return process

    def test_unexpected_exit_reaches_failure_callback_and_log(self):
        process = self.make_process("print('engine failure'); raise SystemExit(7)")
        process.start()
        self.assertTrue(self.failed.wait(3))
        process.stop()
        self.assertIn("code 7", self.errors[0])
        self.assertIn("engine failure", process.log_path.read_text())

    def test_intentional_shutdown_does_not_report_failure(self):
        process = self.make_process("import time; time.sleep(30)")
        process.start()
        process.stop()
        self.assertFalse(self.errors)
        self.assertIsNotNone(process.process.poll())

    def test_readiness_timeout_stops_owned_process(self):
        process = self.make_process("import time; time.sleep(30)")
        process.start()
        with patch("spine.process.health_ready", return_value=False):
            with self.assertRaises(TimeoutError):
                process.wait_ready("http://127.0.0.1:8080/health", timeout_s=0.05)
        self.assertIsNotNone(process.process.poll())
        self.assertFalse(self.errors)

    def test_successful_readiness_still_requires_running_process(self):
        process = self.make_process("import time; time.sleep(30)")
        process.start()
        with patch("spine.process.health_ready", return_value=True):
            process.wait_ready("http://127.0.0.1:8080/health")
        self.assertIsNone(process.process.poll())

    def test_remote_health_checks_are_rejected_before_network_access(self):
        for url in ("http://example.com/health", "http://localhost/health",
                    "https://127.0.0.1/health", "http://user@127.0.0.1/health"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_health_url(url)

    def test_existing_health_endpoint_is_not_mistaken_for_owned_engine(self):
        process = self.make_process("import time; time.sleep(30)")
        with patch("spine.process.health_ready", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "another process"):
                process.start(health_url="http://127.0.0.1:8080/health")
        self.assertIsNone(process.process)


if __name__ == "__main__":
    unittest.main()
