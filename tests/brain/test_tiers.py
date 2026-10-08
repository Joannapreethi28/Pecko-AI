from fakes import FakeClient, wait_until
from test_stage import done, events, final, make


class FakeServer:
    log = []

    def __init__(self, tier):
        self.tier = tier

    def start(self):
        FakeServer.log.append(("start", self.tier.name, self.tier.ctx))
        return 0.25

    def stop(self):
        FakeServer.log.append(("stop", self.tier.name, self.tier.ctx))


def make_with_server(tmp_path, **kw):
    FakeServer.log = []
    return make(tmp_path, FakeClient(), server_factory=FakeServer, **kw)


def test_ctx_change_restarts_server_unload_first(tmp_path):
    stage, out, log = make_with_server(tmp_path)
    stage.set_tier(2)
    assert wait_until(lambda: events(log, "tier_switch"))
    stage.stop()
    assert FakeServer.log[:3] == [("start", "T0", 2048), ("stop", "T0", 2048), ("start", "T2", 512)]
    assert events(log, "tier_switch")[0]["extra"]["load_ms"] == 250.0


def test_same_server_config_does_not_restart(tmp_path):
    from brain.tiers import TIERS
    from dataclasses import replace
    tiers = dict(TIERS)
    tiers[1] = replace(TIERS[0], name="T1", n_predict=40, prefill="stable")
    stage, out, log = make_with_server(tmp_path, tiers=tiers)
    stage.set_tier(1)
    assert wait_until(lambda: events(log, "tier_switch"))
    stage.stop()
    assert [e for e in FakeServer.log if e[0] == "start"] == [("start", "T0", 2048)]


def test_t3_stops_server_and_back_to_t0_restarts(tmp_path):
    stage, out, log = make_with_server(tmp_path)
    stage.set_tier(3)
    assert wait_until(lambda: events(log, "tier_switch"))
    stage.feed(final(1, "what is the capital of france"))
    assert wait_until(lambda: done(out, turn=1))
    assert out[-1]["clip"] == "low_power"
    stage.set_tier(0)
    assert wait_until(lambda: len(events(log, "tier_switch")) == 2)
    stage.feed(final(2, "what is the capital of france"))
    assert wait_until(lambda: done(out, turn=2))
    stage.stop()
    assert out[-1]["type"] == "chunk"
    assert FakeServer.log[:3] == [("start", "T0", 2048), ("stop", "T0", 2048), ("start", "T0", 2048)]
