"""Moonshine streaming ASR backend (moonshine-voice package). T0 uses
SMALL_STREAMING, lower tiers TINY_STREAMING, per docs/CONTRACT.md's tier
table and ears/SPEC.md's lead pick. We did not have time for the 3-way
Tiny/Small/Zipformer bake-off the spec calls for, so this is "picked per the
research doc's own recommendation, not bake-off-verified" -- said plainly in
ears/RESULTS.md.

O1 (speculative ASR finish): `force_update()` calls the engine's own
`update_transcription()` immediately at the first silent frame instead of
waiting for its internal update-interval timer. Nothing is thrown away if
speech resumes -- a Stream just keeps accruing audio -- so this is simpler
than the generic "decode on a cancellable copy" sketch in the research doc;
Moonshine's own API shape makes the copy unnecessary.

O10 (hotwords): `set_keyterms()` is the engine's built-in decoder bias, used
directly instead of a custom post-hoc replace pass.

Thread/spinning control (O3) is not exposed by this native library's Python
wrapper (checked: no num_threads/spinning option in TranscriberOptionC) --
said honestly rather than claimed.
"""
from dataclasses import dataclass, field

from moonshine_voice import ModelArch, get_model_for_language
from moonshine_voice.transcriber import (
    LineCompleted,
    LineTextChanged,
    Stream,
    Transcriber,
)

SAMPLE_RATE = 16000

_TIER_TO_ARCH = {
    0: ModelArch.SMALL_STREAMING,
    1: ModelArch.TINY_STREAMING,
    2: ModelArch.TINY_STREAMING,
    3: ModelArch.TINY_STREAMING,
    "phone": ModelArch.TINY_STREAMING,
}


@dataclass
class _UtteranceState:
    text: str = ""
    prev_text: str = ""
    words: list = field(default_factory=list)
    is_complete: bool = False


class MoonshineASR:
    def __init__(self, tier: int | str = 0, language: str = "en"):
        self._tier = tier
        self._language = language
        self._transcriber: Transcriber | None = None
        self._stream: Stream | None = None
        self._state = _UtteranceState()

    def start(self) -> None:
        """O4: load + warm up. Call once before the first turn."""
        wanted_arch = _TIER_TO_ARCH.get(self._tier, ModelArch.TINY_STREAMING)
        model_path, arch = get_model_for_language(
            self._language, wanted_arch, include_word_timestamps=True
        )
        self._transcriber = Transcriber(model_path, model_arch=arch)
        # Warm-up pass: 0.5 s of silence through the real decode path so the
        # first user turn doesn't pay the first-inference cost.
        self._transcriber.transcribe_without_streaming([0.0] * (SAMPLE_RATE // 2), SAMPLE_RATE)

    def set_keyterms(self, hotwords: list[str]) -> None:
        if self._transcriber is not None:
            self._transcriber.set_keyterms(hotwords)

    def set_tier(self, tier: int | str) -> None:
        if tier == self._tier:
            return
        self._tier = tier
        self.start()  # reload lazily; Spine calls this between turns only

    def begin_utterance(self) -> None:
        self._state = _UtteranceState()
        if self._stream is not None:
            self._stream.close()
        self._stream = Stream(self._transcriber, update_interval=0.3)
        self._stream.add_listener(self._on_event)
        self._stream.start()

    def _on_event(self, event) -> None:
        if isinstance(event, (LineTextChanged, LineCompleted)):
            self._state.prev_text = self._state.text
            self._state.text = event.line.text
            self._state.words = event.line.words or []
            self._state.is_complete = event.line.is_complete

    def accept_frame(self, frame) -> None:
        if self._stream is not None:
            self._stream.add_audio(frame.tolist(), SAMPLE_RATE)

    def force_update(self) -> None:
        """O1: run a decode pass right now instead of waiting for the
        stream's own update-interval timer."""
        if self._stream is not None:
            self._stream.update_transcription()

    def finish(self) -> tuple[str, list]:
        """Flush the stream and return (final_text, word_timings)."""
        if self._stream is not None:
            self._stream.stop()
        return self._state.text, self._state.words

    def current_text(self) -> str:
        return self._state.text

    def stable_prefix(self) -> str:
        """Words agreed by two consecutive updates (docs/CONTRACT.md's
        `stable` field) -- longest common word-prefix of the last two
        partials."""
        cur = self._state.text.split()
        prev = self._state.prev_text.split()
        n = 0
        for a, b in zip(cur, prev):
            if a != b:
                break
            n += 1
        return " ".join(cur[:n])
