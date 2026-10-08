# EARS (listening)
Read `SPEC.md`, `../docs/CONTRACT.md`, and `research/` (v2 research + O1-O10 optimizations).
Mission: wake word → VAD → streaming ASR → fusion endpointer; emit `partial` (with `stable`), `tentative_final`, `final`, `cancel`, `barge_in`. Endpoint delay is the biggest latency number we control.
First task: 30-clip bake-off (Moonshine Tiny vs Small vs sherpa Zipformer, 1 core) on the team's own voices incl. Indian-accent clips and ≥10 mid-sentence pauses. Hand-label last-word times. Do not trust vendor WER.
Rules: ONNX 1 thread + spinning off; stamp times at audio capture; warm up in `start()`; ignore wake word and raise VAD threshold while `playback_state.playing`.
