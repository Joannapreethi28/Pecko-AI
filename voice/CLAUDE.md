# VOICE (speaking)
Read `SPEC.md`, `../docs/CONTRACT.md`, and `research/03_VOICE_research.md`.
Mission: turn `chunk`s into audio with the lowest first-sample latency, no gaps, <100 ms barge-in stop, plus a pre-synthesized cache.
First task: Piper (sherpa-onnx, 1 thread) benchmark grid incl. int8 vs fp32 (quantization trap: int8 may be slower). Keep one `sounddevice` stream open from startup; stamp the first non-silent sample via DAC time.
Rules: first phrase short, later phrases grow while buffer >300 ms ahead; cache only closed-domain intents, measure false-hit rate; fillers OFF in headline numbers; models vendored, no runtime downloads.
