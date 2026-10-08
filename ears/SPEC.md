# EARS: build spec (v1 spec + v2 changes at the end)
> v2: this file is the source of truth for this role. Shared decisions, architecture and plan: ../docs/solution.md (v2). Contract: ../docs/CONTRACT.md.

**Stack (pick from research):** energy gate → **TEN VAD vs Silero** (bake-off, ship the faster speech→silence flip) → **sherpa-onnx open-vocabulary KWS, "hey Pecko"** + push-to-talk → **Moonshine v2 Small Streaming** (challenger: sherpa streaming Zipformer) → **fusion endpointer** (Smart Turn v3.2 int8, 8 MB + silence length + transcript cues).

**State machine:** `IDLE → ARMED → LISTENING → PAUSED → (final) → ARMED (~8 s follow-up window) → IDLE`

**Endpoint rule (starting values, tune on our clips):**
1. First silent frame: stamp `t_eos`, start Smart Turn **and** a speculative ASR finish on a copy of the stream (O1, O2).
2. p(done) ≥ 0.7 and no dangling word ("and", "the", "of", "um", "so") → send `final` at ~150 ms of silence. At p ≥ 0.6 also send `tentative_final` earlier.
3. 0.4–0.7 → wait ~300 ms, re-check.
4. < 0.4 or dangling word → wait up to the **per-speaker adaptive cap** (1.5 × median mid-sentence pause, clamped 0.5–1.2 s) (O6).
5. Speech resumes → `cancel`, discard speculative work, keep listening.

**Must-do optimizations:** O3 spinning off (energy), O4 warm-up at start, O5 timestamps at capture, O7 throttle partials (on change, ≤ 1 per 150 ms), O9 echo-safe barge-in (VAD threshold 0.8 + 250 ms during playback, ignore wake word), O10 normalized text + hotwords (Coimbatore, Karunya, Chennai, rupees, lakh, crore, Pecko).

**First task (bake-off):** Moonshine Tiny vs Moonshine Small vs Zipformer on the **30-clip team set** (all four voices, Indian English, 10+ clips with mid-sentence pauses), pinned to 1 core. Record WER, last word → `final` delay, peak RAM. Pick on numbers. Biggest risk: Indian-accent WER, since Moonshine has no published Indian-English score.

**Ears ablation rows:** fixed 800 ms · fixed 400 ms · Smart Turn + 200 ms · fusion · fusion + O1/O2 · + O6 · tentative_final (delay seen by Brain) · always-on ASR (gating off) · spinning on vs off (idle CPU). Endpoint delay is measured against a **hand-labelled** last-word time.

**Done when:** median endpoint delay and false cut-offs /30 reported; idle CPU over 60 s silence reported; works from mic and WAV; `set_tier` works.

---
## v2 changes
- Endpointer = **calibrated context thresholds**: a lookup table of silence thresholds per evidence bin (sentence complete, dangling word, transcript stable, Smart Turn bin). Probabilities come from **our labelled turns**. Arm a timer for the next crossing (event-driven, not polling).
- Choose the policy at **matched whole-turn cut-off risk**, then freeze it for the scheduling ablations. Do not claim "Bayesian endpointing" as new (Raux & Eskenazi 2008).
- Phone: sherpa streaming Zipformer + VAD + text cues + timer (../mobile/SPEC.md).
