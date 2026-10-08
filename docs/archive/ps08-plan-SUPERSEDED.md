> **SUPERSEDED by `docs/solution.md`.** Kept as history. Notable changes since: host cgroups (not Docker/WSL2), role split is now Ears/Brain/Voice/Spine, contract is v2.

# HackNEX26 — Team Plumbers — LOCKED: HNX26EPS08 On-Device Conversational Stack
Locked 8 Oct 2026, 12:32 IST. Chosen after a 4-lens council (judge/crowding, GPU-track feasibility, CPU/API feasibility, red team). 3 of 4 lenses ranked PS08 first; GPU lens never scored it. Fallback if PS08 breaks: PS01 (Legal, deterministic citation verifier).

## Thesis (one line)
Under a fixed small CPU/RAM budget, end-of-speech to first-audio latency is lost to serial stage waiting (endpointing, ASR finalize, LLM prefill, TTS first chunk), not to slow models. We overlap stages and degrade gracefully as the limit tightens, and prove every gain by ablation.

## Baseline (declared, strongest default we can configure)
Sequential Silero VAD -> streaming/small ASR (Moonshine or whisper.cpp) -> llama.cpp small LLM Q4 -> Piper/Kokoro TTS, default settings, same enforced limit.

## Our own code (must be written in-window; rules)
1. Orchestrator: streaming pipeline, sentence-chunked LLM->TTS, speculative LLM prefill on partial transcript with rollback.
2. Resource governor: watches CPU/RAM pressure, steps down a tier ladder (ASR size, LLM size/quant, TTS voice, context length).
3. Measurement harness: latency timer, CPU/RAM/energy logging, ablation runner.

## Metrics
p50/p95 end-of-speech -> first audio; peak RAM; CPU-seconds per reply; energy (state method + error bars); WER; answer quality on a held-out spoken set. Ablate every technique separately. Show quality-vs-budget curve.

## Rules / gotchas
- No GPU anywhere (pass/fail). Enforce limit in Docker/WSL2 (--cpus, --memory), show live stats.
- Cached TTS only for known common intents; no filler sounds to fake first-audio latency.
- Energy: Linux RAPL; Mac powermetrics; Windows HWiNFO/LibreHardwareMonitor or CPU-seconds proxy. Ask organisers what they accept.
- Edge: Intel Power Gadget is end-of-life.

## Split
- A Pipeline lead: streaming loop, overlap, rollback.
- B Runtime + measurement: limits, latency timer, energy, baseline numbers.
- C Models + quantization: tiers, WER/answer-quality eval.
- D Governor + eval + write-up + pitch.

## Timeline (plan to the earlier deadline: form closes 8:00 AM 9 Oct per rules PDF; freeze ~6:30 AM)
- 12:30-2:00 gates: limit enforcement, energy method, plain chained loop runs.
- 2:00-5:30 PM baseline numbers + v1 loop. Progress Check 1 at 5:30 PM.
- 5:30-10:30 PM overlap + governor. Progress Check 2 at 12:00 AM.
- 10:30 PM-6:30 AM refine: held-out test, ablations, write-up, rehearse pitch.

## Ask organisers
1. Real submission end time. 2. How are energy and "no GPU" measured; does an iGPU/NPU count. 3. Are pretrained weights allowed. 4. Who declares the resource limit. 5. Is a bare scaffold a "template".
