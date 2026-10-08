import io
import json
from queue import Full
import unittest

from common.log import EventLog
from spine.bus import EventBus
from spine.commit import CommitGate
from spine.linux import build_command


class FakeStage:
    def __init__(self):
        self.messages = []
        self.stopped = False
        self.fail_start = self.fail_stop = False

    def start(self):
        if self.fail_start:
            raise RuntimeError("load failed")

    def stop(self):
        self.stopped = True
        if self.fail_stop:
            raise RuntimeError("cleanup failed")

    def feed(self, msg):
        self.messages.append(msg)

    def set_tier(self, n):
        pass


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.stream = io.StringIO()
        self.log = EventLog(self.stream)
        self.stages = {name: FakeStage() for name in ("ears", "brain", "voice")}
        self.bus = EventBus(self.stages, self.log, capacity=2)

    def test_cancel_fanout_and_message_ownership(self):
        self.bus.start()
        msg = {"type": "cancel", "turn": 7}
        self.bus.publish("ears", msg)
        msg["turn"] = 8
        self.bus.dispatch_one(timeout=0)
        for name in ("brain", "voice"):
            self.assertEqual(self.stages[name].messages[0]["turn"], 7)
        self.assertIsNot(self.stages["brain"].messages[0], self.stages["voice"].messages[0])
        self.bus.stop()

    def test_start_failure_cleans_partial_start(self):
        self.stages["brain"].fail_start = True
        self.stages["brain"].fail_stop = True
        with self.assertRaisesRegex(RuntimeError, "load failed"):
            self.bus.start()
        self.assertTrue(self.stages["brain"].stopped)
        self.assertTrue(self.stages["voice"].stopped)
        self.assertFalse(self.stages["ears"].stopped)

    def test_overload_is_visible(self):
        for _ in range(2):
            self.bus.publish("ears", {"type": "cancel", "turn": 0})
        with self.assertRaises(Full):
            self.bus.publish("ears", {"type": "barge_in", "turn": 0})

    def test_missing_generation_is_rejected(self):
        with self.assertRaises(ValueError):
            self.bus.publish("brain", {"type": "chunk", "turn": 0})

    def test_log_preserves_capture_time_and_jsonl(self):
        self.log.emit("ears", "asr_final", 7, t=12.5, text="hello\nPecko")
        lines = self.stream.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["t"], 12.5)
        with self.assertRaises(ValueError):
            self.log.emit("ears", "bad", t=float("nan"))

    def test_launcher_preserves_arguments_and_limits(self):
        cmd = build_command("/path with spaces/python", "0,1", 200, "2G",
                            ["-m", "spine.mock", "--text", "hi Pecko"])
        self.assertIn("MemorySwapMax=0", cmd)
        self.assertIn("CPUQuota=200%", cmd)
        self.assertEqual(cmd[cmd.index("--") + 1], "/path with spaces/python")
        self.assertEqual(cmd[-1], "hi Pecko")

    def test_commit_requires_exact_prompt_and_is_single_use(self):
        gate = CommitGate()
        gate.prepare(7, 1, [10, 20])
        self.assertEqual(gate.validate_final(7, 1, [10, 20])["type"], "commit")
        with self.assertRaises(ValueError):
            gate.validate_final(7, 1, [10, 20])
        gate.prepare(7, 2, [10, 20])
        self.assertEqual(gate.validate_final(7, 2, [11, 20])["type"], "cancel")

    def test_cancel_and_stale_generation_cannot_commit(self):
        gate = CommitGate()
        gate.prepare(7, 1, [10])
        gate.cancel(7, 1)
        with self.assertRaises(ValueError):
            gate.validate_final(7, 1, [10])
        gate.prepare(7, 2, [10])
        with self.assertRaises(ValueError):
            gate.validate_final(7, 1, [10])
        with self.assertRaises(ValueError):
            gate.prepare(7, 1, [10])


if __name__ == "__main__":
    unittest.main()
