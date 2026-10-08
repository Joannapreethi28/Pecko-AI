"""Portable v2.1 authorization gate; Voice still owns held PCM and playback.

Brain supplies exact serialized token sequences, including history and template.
Transcript equality alone is not sufficient. Calls must be serialized by Spine.
"""

from common.clock import now


class CommitGate:
    def __init__(self):
        self.turn = -1
        self.gen = -1
        self.tokens: tuple[int, ...] | None = None

    def prepare(self, turn: int, gen: int, prompt_tokens: list[int]) -> None:
        if turn < 0 or gen < 0:
            raise ValueError("turn and gen must be nonnegative")
        if turn < self.turn or (turn == self.turn and gen <= self.gen):
            raise ValueError("Preparation must advance turn or generation")
        self.turn, self.gen = turn, gen
        self.tokens = tuple(prompt_tokens)

    def validate_final(self, turn: int, gen: int, final_tokens: list[int]) -> dict:
        """Call only after Ears final and Brain's complete prompt serialization.

        A mismatch cancels this generation; Brain must rewind/recompute and
        prepare a NEW generation before trying again. This method never rewinds
        engine state itself. Successful authorization is single-use.
        """
        if (turn, gen) != (self.turn, self.gen) or self.tokens is None:
            raise ValueError("No matching active preparation")
        matched = self.tokens == tuple(final_tokens)
        self.tokens = None
        return {"type": "commit" if matched else "cancel",
                "turn": turn, "gen": gen, "t": now()}

    def cancel(self, turn: int, gen: int) -> None:
        if (turn, gen) == (self.turn, self.gen):
            self.tokens = None
