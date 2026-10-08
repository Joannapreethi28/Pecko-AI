# VOICE: build spec (v1 spec + v2 changes at the end)
> v2: this file is the source of truth for this role. Shared decisions, architecture and plan: ../docs/solution.md (v2). Contract: ../docs/CONTRACT.md.

**Stack:** **Piper `en_US-lessac-medium` on sherpa-onnx**, `num_threads=1`, two warm-up synths at start. Same speaker `lessac-low` for the lower tier, so the voice never changes. Kokoro only if the A/B shows its first phrase ≤ 150 ms under the cap (unlikely on 2 cores). espeak-ng as the guaranteed bottom tier.

**Pipeline:** turn filter + `seq` reorder (300 ms gap timeout) → normalizer (strip markdown/emoji/URLs, `num2words` incl. lakh/crore/₹, times, units) → **adaptive phrase chunker** (first phrase: first punctuation or 4–6 words, min 2; later phrases grow up to a sentence while the buffer is > 300 ms ahead; shrink again below 150 ms) → cache lookup → synth worker → preallocated ring buffer (trim, 100/220 ms pauses, 5–10 ms fades, one loudness target) → one always-open `sounddevice` stream, blocksize 256–512, `latency='low'`, callback copies only.

**First-sample timestamp:** `t = time.monotonic() + (time_info.outputBufferDacTime - time_info.currentTime)` at the first non-silent sample. Spine cross-checks with a phone recording.

**Cache layers:** L2 openers and stock phrases (exact hash) · L3 runtime memo (LRU of every phrase synthesized) · L4 full intent answers (from Brain's router `cached` messages) · composed time/date from word clips · L1 fillers **off by default** (D2). All clips made with the exact live voice and settings; regenerate when either changes.

**Must-dos:** keep the stream open from startup (no 50–200 ms device open per reply) · wired/built-in speaker (Bluetooth adds 150–300 ms) · charger in, performance mode · barge-in stop < 100 ms with a 10 ms fade · `--barge-in off` half-duplex switch for the judged run if echo misfires · per-phrase exception falls back to the next tier so the user always hears something.

**Quantization finding:** A/B Piper/Kokoro int8 vs fp32 on our CPU at 1 thread. If int8 is not ≥ 15% faster, ship fp32 and report "int8 slower or no gain on our CPU." This is evidence for the 15% quantization criterion either way.

**Voice ablation rows:** no cache · L2 · L2+L3 · L2–L4 + composed · sentence vs comma vs adaptive chunking (first audio, underruns, synth calls) · int8 vs fp32 · fillers on (separate column only).

**Done when:** chunk → first sound p50/p90 logged; no audible gaps; barge-in stop delay measured; cache hit and false-hit rate on the test set; 2+ voice tiers; RAM/CPU under the cap.

---
## v2 changes
- **Hold buffer:** PCM for `held:true` chunks is synthesized into a private buffer and played only after `commit` for that `gen`. Drop it on `cancel` or a new `gen`.
- Chunking is a decision. Ship the v1 adaptive rule first. Spine may later drive a causal two-chunk planner. Report **gap duration** with first-audio time: a tiny first chunk that stalls is not a win (synthetic: one-word chunks → 560 ms of gaps).
- Measure **input text → first PCM** for Piper (its Python path is sentence-level, not token streaming).
- Phone: Piper `lessac-low` via sherpa-onnx (../mobile/SPEC.md).
