"""Single-owner turn/generation state; all transitions run on the bus dispatcher.

Prepared/final_tokens are internal adapter callbacks, not new contract messages.
Brain must submit final_tokens only after serializing the corresponding final.
"""

from common.log import EventLog
from spine.commit import CommitGate


class TurnController:
    def __init__(self, log: EventLog):
        self.log = log
        self.gate = CommitGate()
        self.turn = -1
        self.gen = -1
        self.final = False
        self.closed = False
        self.valid = False
        self.committed = False

    def _control(self, kind: str) -> dict:
        msg = {"type": kind, "turn": self.turn}
        if self.gen >= 0:
            msg["gen"] = self.gen
        return msg

    def _invalidate(self):
        self.gate.cancel(self.turn, self.gen)
        self.valid = self.committed = False

    def complete(self, turn: int) -> bool:
        """Supervisor-confirmed boundary after stage work/playback has stopped."""
        if turn != self.turn:
            return False
        self._invalidate()
        self.closed = True
        return True

    def accept(self, source: str, msg: dict) -> tuple[bool, list[dict]]:
        """Return whether to route the event, plus controls to deliver first."""
        turn, kind = msg["turn"], msg["type"]
        controls = []
        if source == "ears":
            if turn < self.turn or (turn == self.turn and self.closed):
                return False, controls
            if turn > self.turn:
                # Cancel old synthesis/playback even when no gen was registered.
                if self.turn >= 0:
                    controls.append(self._control("cancel"))
                self._invalidate()
                self.turn, self.gen = turn, -1
                self.final = self.closed = False
            if kind in ("cancel", "barge_in"):
                if self.gen >= 0:
                    msg["gen"] = self.gen
                self._invalidate()
                self.final = False
                self.closed = kind == "barge_in"
            elif kind == "final":
                if self.final:
                    return False, controls
                self.final = True
            elif self.final and kind in ("partial", "tentative_final"):
                # Revised speech needs cancel first or a new turn ID.
                return False, controls
            return True, controls
        if turn != self.turn or self.closed:
            return False, controls
        if source == "brain":
            if msg["gen"] != self.gen or not self.valid:
                return False, controls
            # Prepared chunks must explicitly remain private until commit.
            return self.committed or msg.get("held") is True, controls
        if source == "voice" and kind == "cancel":
            if "gen" in msg and msg["gen"] != self.gen:
                return False, controls
            self._invalidate()
            # Also flush Voice's held data through the same control path.
            controls.append(self._control("cancel"))
            return False, controls
        if source == "voice" and kind == "playback_state":
            # v2 feedback has no gen. Voice must suppress stale worker callbacks.
            return not msg["playing"] or self.committed, controls
        return True, controls

    def prepared(self, turn: int, gen: int, tokens: list[int]) -> list[dict]:
        if turn != self.turn or self.closed or gen <= self.gen:
            self.log.emit("spine", "stale_preparation", turn, gen=gen)
            return []
        controls = [self._control("cancel")] if self.gen >= 0 else []
        self.gate.prepare(turn, gen, tokens)
        self.gen = gen
        self.valid, self.committed = True, False
        return controls

    def validate(self, turn: int, gen: int, tokens: list[int]) -> list[dict]:
        if (turn, gen) != (self.turn, self.gen) or not self.valid or self.closed:
            self.log.emit("spine", "stale_validation", turn, gen=gen)
            return []
        if not self.final:
            raise ValueError("Prompt validation must follow the Ears final event")
        if self.committed:
            return []
        control = self.gate.validate_final(turn, gen, tokens)
        self.committed = control["type"] == "commit"
        self.valid = self.committed
        self.log.emit("spine", control["type"], turn, t=control["t"], gen=gen)
        return [control]
