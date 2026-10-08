import io
from queue import Empty
import unittest

from common.log import EventLog
from spine.bus import EventBus
from spine.hold import HoldBuffer


class Recorder:
    def __init__(self):
        self.messages = []

    def start(self): pass
    def stop(self): pass
    def set_tier(self, n): pass
    def feed(self, msg): self.messages.append(msg)


class TurnTests(unittest.TestCase):
    def setUp(self):
        self.stages = {name: Recorder() for name in ("ears", "brain", "voice")}
        self.bus = EventBus(self.stages, EventLog(io.StringIO()))
        self.bus.start()
        self.addCleanup(self.bus.stop)

    def drain(self):
        while True:
            try:
                self.bus.dispatch_one(timeout=0)
            except Empty:
                return

    def ears(self, kind, turn=1):
        self.bus.publish("ears", {"type": kind, "turn": turn})

    def chunk(self, gen=0, turn=1, held=True):
        self.bus.publish("brain", {"type": "chunk", "turn": turn, "gen": gen,
                                   "seq": 0, "text": "Hello", "held": held})

    def voice_types(self):
        return [msg["type"] for msg in self.stages["voice"].messages]

    def test_prepare_before_final_is_held_then_committed(self):
        self.ears("tentative_final")
        self.bus.prepared(1, 0, [1, 2])
        self.chunk()
        self.drain()
        self.assertEqual(self.voice_types(), ["chunk"])
        self.ears("final")
        self.bus.validate_final(1, 0, [1, 2])
        self.drain()
        self.assertEqual(self.voice_types(), ["chunk", "commit"])

    def test_validation_before_final_is_error(self):
        self.ears("tentative_final")
        self.bus.prepared(1, 0, [1])
        self.bus.validate_final(1, 0, [1])
        with self.assertRaisesRegex(ValueError, "follow the Ears final"):
            self.drain()
        self.assertNotIn("commit", self.voice_types())

    def test_unheld_and_unregistered_output_never_reaches_voice(self):
        self.ears("tentative_final")
        self.chunk()
        self.bus.prepared(1, 0, [1])
        self.chunk(held=False)
        self.drain()
        self.assertEqual(self.voice_types(), [])

    def test_mismatch_cancels_and_new_generation_can_commit(self):
        self.ears("final")
        self.bus.prepared(1, 0, [1])
        self.chunk()
        self.bus.validate_final(1, 0, [2])
        self.chunk()
        self.bus.prepared(1, 1, [2])
        self.chunk(gen=1)
        self.bus.validate_final(1, 1, [2])
        self.drain()
        chunks = [m for m in self.stages["voice"].messages if m["type"] == "chunk"]
        self.assertEqual([m["gen"] for m in chunks], [0, 1])
        commits = [m for m in self.stages["voice"].messages if m["type"] == "commit"]
        self.assertEqual([m["gen"] for m in commits], [1])

    def test_cancel_blocks_late_tokens_and_tags_generation(self):
        self.ears("tentative_final")
        self.bus.prepared(1, 0, [1])
        self.ears("cancel")
        self.bus.validate_final(1, 0, [1])
        self.chunk()
        self.drain()
        self.assertEqual(self.voice_types(), ["cancel"])
        self.assertEqual(self.stages["voice"].messages[0]["gen"], 0)

    def test_new_turn_cancels_old_and_drops_old_outputs(self):
        self.ears("final")
        self.bus.prepared(1, 0, [1])
        self.ears("partial", turn=2)
        self.chunk(turn=1)
        self.bus.validate_final(1, 0, [1])
        self.drain()
        self.assertEqual(self.voice_types(), ["cancel"])
        self.assertEqual(self.stages["voice"].messages[0]["turn"], 1)

    def test_cancelled_generation_cannot_finish_resumed_turn(self):
        self.ears("tentative_final")
        self.bus.prepared(1, 0, [1])
        self.ears("cancel")
        self.bus.complete_turn(1, 0, success=True)
        self.ears("partial")
        self.drain()
        self.assertNotIn(1, self.bus.outcomes)
        self.assertFalse(self.bus.turns.closed)

    def test_completion_of_older_generation_is_ignored(self):
        self.ears("final")
        self.bus.prepared(1, 0, [1])
        self.bus.prepared(1, 1, [1])
        self.bus.validate_final(1, 1, [1])
        self.bus.complete_turn(1, 0, success=True)
        self.drain()
        self.assertNotIn(1, self.bus.outcomes)
        self.bus.complete_turn(1, 1, success=True)
        self.drain()
        self.assertIn(1, self.bus.outcomes)
        self.assertTrue(self.bus.turns.closed)

    def test_barge_in_closes_turn_and_duplicate_final_does_not_restart(self):
        self.ears("final")
        self.bus.prepared(1, 0, [1])
        self.bus.validate_final(1, 0, [1])
        self.ears("barge_in")
        self.ears("final")
        self.bus.prepared(1, 1, [1])
        self.chunk(gen=1)
        self.drain()
        self.assertEqual(self.voice_types(), ["commit", "barge_in"])


class HoldTests(unittest.TestCase):
    def test_no_release_until_commit_and_sequence_is_preserved(self):
        hold = HoldBuffer()
        self.assertEqual(hold.ready(1, 0, 1, b"second"), [])
        self.assertEqual(hold.commit(1, 0), [])
        self.assertEqual(hold.ready(1, 0, 0, b"first"), [b"first", b"second"])
        self.assertEqual(hold.ready(1, 0, 0, b"duplicate"), [])

    def test_pcm_before_commit(self):
        hold = HoldBuffer()
        self.assertEqual(hold.ready(1, 0, 0, b"first"), [])
        self.assertEqual(hold.commit(1, 0), [b"first"])
        self.assertEqual(hold.commit(1, 0), [])

    def test_cancel_before_pcm_blocks_worker_completion(self):
        hold = HoldBuffer()
        hold.cancel(1, 0)
        self.assertEqual(hold.ready(1, 0, 0, b"late"), [])
        self.assertEqual(hold.commit(1, 0), [])
        hold.ready(1, 1, 0, b"new")
        self.assertEqual(hold.commit(1, 1), [b"new"])
        self.assertEqual(hold.ready(1, 0, 1, b"old"), [])

    def test_new_turn_drops_previous_pcm(self):
        hold = HoldBuffer()
        hold.ready(1, 9, 0, b"old")
        hold.ready(2, 0, 0, b"new")
        self.assertEqual(hold.commit(1, 9), [])
        self.assertEqual(hold.commit(2, 0), [b"new"])

    def test_memory_budget_is_bounded(self):
        hold = HoldBuffer(max_bytes=4)
        hold.ready(1, 0, 0, b"1234")
        with self.assertRaises(BufferError):
            hold.ready(1, 0, 1, b"5")
        self.assertEqual(hold.size, 4)
        hold.cancel(1, 0)
        self.assertEqual(hold.size, 0)


if __name__ == "__main__":
    unittest.main()
