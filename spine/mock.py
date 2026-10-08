"""Text-only wiring smoke test. No ASR, model inference, audio or benchmarks."""

import argparse
import sys

from common.clock import now
from common.log import EventLog
from spine.bus import EventBus
from spine.hold import HoldBuffer


class MockStage:
    def __init__(self, name, emit, log):
        self.name, self.emit, self.log = name, emit, log
        self.tier = 0
        self.completed = False
        self.hold = HoldBuffer()
        self.prepare = self.validate = None
        self.on_complete = None

    def _released(self, msg, blocks):
        if not blocks:
            return
        self.log.emit("voice", "mock_release", msg["turn"], gen=msg["gen"],
                      synthetic=True, blocks=len(blocks), audio=False)
        self.emit("voice", {"type": "playback_state", "turn": msg["turn"],
                            "playing": False, "t": now()})
        if self.on_complete is not None:
            self.on_complete(msg["turn"], msg["gen"], success=True, gap_s=None)

    def start(self):
        pass

    def stop(self):
        pass

    def set_tier(self, n):
        self.tier = n

    def feed(self, msg):
        if self.name == "brain" and msg["type"] == "final":
            # Synthetic token IDs only; real Brain supplies its own full prompt.
            tokens = [1, *msg["text"].encode("utf-8")]
            self.prepare(msg["turn"], 0, tokens)
            self.emit("brain", {"type": "chunk", "turn": msg["turn"],
                                "gen": 0, "seq": 0, "last": True,
                                "held": True,
                                "text": "This is a mock reply from Pecko."})
            self.validate(msg["turn"], 0, tokens)
        elif self.name == "voice" and msg["type"] == "chunk":
            self.log.emit("voice", "mock_text_received", msg["turn"],
                          text=msg["text"], synthetic=True)
            self._released(msg, self.hold.ready(msg["turn"], msg["gen"],
                                               msg["seq"], b"synthetic PCM"))
        elif self.name == "voice" and msg["type"] == "commit":
            self._released(msg, self.hold.commit(msg["turn"], msg["gen"]))
        elif self.name == "voice" and msg["type"] in ("cancel", "barge_in"):
            if "gen" in msg:
                self.hold.cancel(msg["turn"], msg["gen"])
            elif self.hold.key[0] == msg["turn"]:
                self.hold.cancel(*self.hold.key)
        elif self.name == "ears" and msg["type"] == "playback_state":
            self.completed = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="Hello Pecko")
    args = parser.parse_args()
    log = EventLog(sys.stdout)
    stages = {name: MockStage(name, lambda src, msg: bus.publish(src, msg), log)
              for name in ("ears", "brain", "voice")}
    bus = EventBus(stages, log)
    stages["brain"].prepare = bus.prepared
    stages["brain"].validate = bus.validate_final
    log.emit("spine", "mock_run", synthetic=True, audio=False)
    try:
        bus.start()
        t = now()
        bus.publish("ears", {"type": "final", "turn": 0, "text": args.text,
                             "norm": args.text.lower(), "t_eos": t, "t_endpoint": t})
        while not stages["ears"].completed:
            bus.dispatch_one(timeout=5)
    finally:
        bus.stop()


if __name__ == "__main__":
    main()
