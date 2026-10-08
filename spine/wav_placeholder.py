"""Audio-ingress stand-in using reference text; never a real ASR measurement."""

from pathlib import Path

from common.clock import now
from spine.audio import inspect_wav, WavReplayer
from spine.placeholders import PlaceholderEars


class WavPlaceholderEars(PlaceholderEars):
    def __init__(self, context, config):
        super().__init__(context, config)
        self.player = None
        self.case = None
        self.eos = None
        self.received_samples = 0

    def replay(self, case, turn):
        if self.player:
            self.player.stop()
        if not isinstance(case.get("reference_text"), str):
            raise ValueError("WAV placeholder needs reference_text; it does not recognize speech")
        path = Path(case["wav"])
        metadata = inspect_wav(path, case["eos_offset_s"])
        self.case = case
        self.received_samples = 0
        self.context.log("input_clip", turn, **metadata, asr="reference-text-placeholder")
        self.player = WavReplayer(self.feed_audio, self.end_audio, self.context.fail)
        capture_start = now()
        self.eos = capture_start + metadata["eos_offset_s"]
        self.player.start(path, turn, metadata, capture_start=capture_start)
        return self.eos

    def feed_audio(self, frame):
        # Real Ears enqueues these exact PCM frames to its streaming recognizer.
        self.received_samples += len(frame.pcm) // 2
        self.context.log("audio_frame", frame.turn, offset_frames=frame.offset_frames,
                         samples=len(frame.pcm) // 2, t_capture=frame.t_capture)

    def end_audio(self, turn):
        self.context.log("wav_replay_end", turn, samples=self.received_samples)
        self.context.log("endpoint", turn, source="reference-placeholder")
        self.context.log("asr_final", turn, source="reference-placeholder")
        text = self.case["reference_text"]
        self.context.publish({"type": "final", "turn": turn, "text": text,
                              "norm": text.lower(), "t_eos": self.eos, "t_endpoint": now()})

    def stop(self):
        if self.player:
            self.player.stop()
        super().stop()
