import io
from queue import Empty
import unittest

from common.log import EventLog
from spine.bus import EventBus
from spine.ladder import PressureSample, TierLadder


class TierStage:
    def __init__(self): self.tiers = []
    def start(self): pass
    def stop(self): pass
    def feed(self, msg): pass
    def set_tier(self, n): self.tiers.append(n)


class LadderTests(unittest.TestCase):
    def test_sustained_risk_downgrades_but_isolated_spike_does_not(self):
        ladder = TierLadder()
        for t, risk in enumerate([True, False, True, True, True]):
            tier = ladder.observe(PressureSample(t, (2, 2), risk))
            self.assertEqual(tier, 1 if t == 4 else 0)

    def test_recovery_needs_good_readings_and_dwell(self):
        ladder = TierLadder(tier=2, up_readings=3)
        for t in [0, 0.2, 0.4, 1.9]:
            self.assertEqual(ladder.observe(PressureSample(t, (2, 2), False)), 2)
        self.assertEqual(ladder.observe(PressureSample(2, (2, 2), False)), 1)

    def test_cap_change_and_unknown_reading_reset_history(self):
        ladder = TierLadder()
        ladder.observe(PressureSample(0, (2, 2), True))
        ladder.observe(PressureSample(1, (2, 2), True))
        self.assertEqual(ladder.observe(PressureSample(2, (1, 1), True)), 0)
        ladder.observe(PressureSample(3, (1, 1), None))
        self.assertEqual(ladder.observe(PressureSample(4, (1, 1), True)), 0)

    def test_cap_floor_prevents_unsupported_upgrade(self):
        ladder = TierLadder(up_readings=1, dwell_s=0)
        self.assertEqual(ladder.observe(PressureSample(0, (1, 1), False, 2)), 2)
        self.assertEqual(ladder.observe(PressureSample(1, (1, 1), False, 2)), 2)

    def test_tier_request_waits_for_explicit_safe_boundary(self):
        stages = {name: TierStage() for name in ("ears", "brain", "voice")}
        bus = EventBus(stages, EventLog(io.StringIO()))
        bus.start()
        self.addCleanup(bus.stop)
        bus.publish("ears", {"type": "partial", "turn": 1})
        bus.request_tier(2)
        bus.publish("voice", {"type": "playback_state", "turn": 1, "playing": False})
        for _ in range(3): bus.dispatch_one(timeout=0)
        self.assertEqual(bus.tier, 0)
        bus.finish_turn(0)  # stale completion cannot change the active turn
        bus.dispatch_one(timeout=0)
        self.assertEqual(bus.tier, 0)
        bus.finish_turn(1)
        bus.dispatch_one(timeout=0)
        self.assertEqual(bus.tier, 2)
        for stage in stages.values(): self.assertEqual(stage.tiers, [2])


if __name__ == "__main__":
    unittest.main()
