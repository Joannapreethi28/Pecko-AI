# SOLUTION v2: "Pecko", a voice assistant that thinks while you talk, on a 2-core laptop and then on your phone
HackNEX 2026 · HNX26EPS08 On-Device Conversational Stack · Team Plumbers
v2, 8 Oct 2026 evening. Merges v1 plus Spine latency research v2 (`spine/research/latency_v2/`). Supersedes v1 where they conflict.

**Read order:** §0 → §1 → §3 → your `<role>/SPEC.md` → §8.
**Role details now live in each role's `SPEC.md`.** This file holds the shared decisions, the architecture and the plan.

> **Honesty rule.** Every number here is vendor, paper, synthetic or an estimate. **Nothing is measured on our hardware yet.** Each `[MEASURE]` is replaced by our own measurement before it reaches a slide.

---

## 0. What changed from v1

| # | v2 decision | Why |
|---|---|---|
| V1 | Product name is **Pecko**. Wake phrase is **"hey Pecko"** (sherpa KWS, any phrase) plus a push-to-talk key. | Team decision. |
| V2 | **Target 1: Ubuntu (dual-boot laptop), native.** Host cgroups via `systemd-run`, no Docker, no Windows path. | The cgroup, PSI and RAPL tooling only exists on Linux. |
| V3 | **Target 2: Android phone, fully on-device.** It runs the same contract and the same orchestrator, with phone engine profiles (§4). Starts only after Linux is stable, except one early 45-min de-risk spike. | Bonus "smaller device", plus Feasibility & Scalability. Phone thermal throttling makes graceful degradation real, not staged. |
| V4 | **Objective is latency-first:** minimise (p90, then p50 first-content-audio latency, then energy), subject to a quality floor, cut-off/underrun budgets and footprint budgets no worse than baseline. **Replaces v1's weighted `L + λE + λG`.** | Spine v2 audit. A weighted or "max quality" objective picked a 3.8 s plan when a 2.2 s plan was feasible (synthetic). |
| V5 | **Critical-path control:** first audio = `max(C, R) + d` (§1). Optimise whichever of C or R is later. Speculation is admitted on **critical-path gain**, not on tokens hidden. | Accelerating R past C buys zero first-audio time. Contention that delays C can make "optimisation" slower. |
| V6 | **Hold-and-release.** Prepare the first clause privately (text plus PCM) before the commit gate, then release on `final`. Nothing audible before commit. | Hides LLM and TTS time inside endpoint confirmation. |
| V7 | **Event-driven dispatch** on the first-audio path (final, first token, PCM-ready, buffer watermark). The 200 ms loop is only for pressure telemetry. | A periodic gate adds up to one loop period of pure waiting. |
| V8 | **Chunking is a decision.** v1 rule first. v2 adds a causal two-chunk planner checked against an offline oracle. | Synthetic: one-word chunks start sooner but stall (560 ms of gaps); 3-3-2 starts at 435 ms with no gaps. |
| V9 | **Endpointing uses calibrated context thresholds** (lookup table per evidence bin), chosen at matched whole-turn cut-off risk. We do **not** claim "Bayesian endpointing" as new (Raux & Eskenazi 2008). | Prior art. Silence alone collapses to a fixed threshold. |
| V10 | **Stats honesty.** Zero cut-offs in 60 turns still means up to 4.87% at 95%. Proving < 2% needs 149 independent turns. Report p50/p90 and gap duration, use paired complete turns, never drop failures. | Audit. |
| V11 | Supplied `incoming_spine/spine_core.py` is **reference only, do not ship as-is**. Its planner objective, its alarm history across cap changes and its endpoint prior sampling are wrong. | Audit (`supplied_code_audit.json`). |

Unchanged from v1: headline = labelled end of speech → first sustained audio of the **real answer** (fillers off) · same LLM in baseline and Pecko · `llama-server` in its own process · Brain model chosen by bake-off and KV rewind must work · ladder ships first · contract v2.

---

## 1. The idea: find the last dependency, then remove it

```
                 user stops talking (acoustic end, t=0)
                 │
 C  commit gate  ├──── endpoint confirmed ── final transcript ── prompt validated ──┤ C
 R  answer ready ├──── prefill delta ── first clause tokens ── first clause PCM ────┤ R
                 │
 first audio  =  max(C, R) + d          d = audio device delay
```

- **If R > C** (answer is late), speed up R: KV cache, early prefill, a short first clause, warm TTS.
- **If R ≤ C** (answer waits for commit), extra speed on R is worth **0 ms** of first audio. Spend effort on C (endpointing) or on buffer for the second chunk.
- **Gain of an optimisation** = `max(C0,R0) − max(C1,R1)`. Speeding R up by h gives `min(h, max(0, R0 − C))`.
- *Synthetic example:* C = 600, R = 900 ms. R → 500 saves 300 ms. R → 200 saves **nothing more**. If speculation's CPU contention pushes C to 1000 ms, the "faster" system is **100 ms slower**.

**Claim (hypothesis until measured):** *Deadline-constrained critical-path control of speculation and chunking under a shared hard CPU cap.* At each moment Pecko decides whether to spend its 2 cores on earlier first audio, on playback buffer, or on finalisation, based on which dependency is currently limiting. It keeps working as the cap tightens (laptop cgroup) or as the device throttles itself (phone).

**Not claimed:** speculation (PredGen, Endpoint Anticipation, Voice-Light), Bayesian/contextual endpointing (Raux 2008), "first local stack with energy numbers" (2026 Moonshine–LM–Piper study). The ingredients are known. The integration under a hard shared cap, measured by ablation, is ours.

---

## 2. Where the points come from

| Rubric item | What earns it | Proof we show |
|---|---|---|
| Latency 25% | critical-path control, hold-and-release, KV cache, event dispatch | B0 vs Pecko p50/p90, paired turns, waterfall with C and R bars |
| Footprint 25% | gated listening, spinning off, rejecting wasteful speculation, 1 resident model | CPU-s/turn, cgroup `memory.peak`, gross and idle-adjusted J/turn |
| What's new 20% | §1 claim | master ablation §7, incl. confidence-only vs critical-path admission |
| Quant + offload 15% | Q4 vs Q8 LLM, int8 vs fp32 TTS, ARM Q4_0 on phone; CPU-only means no offload, said plainly | same-model precision tables, laptop and phone |
| Degradation 15% | one ladder for cgroup caps **and** phone thermals | p90 / quality / failures vs cap; phone run under real throttling |
| Bonus | cached TTS (router), **phone**, Hindi stretch | hit/false-hit rate; phone numbers |
| Event: Design & UX | live dashboard: state, transcript, C/R waterfall per turn, CPU/RAM vs cap, tier | live on screen during demo |
| Event: Feasibility & Scalability | **same contract runs laptop → phone** | phone demo or honest phone measurements |

---

## 3. Architecture, target 1: Ubuntu laptop

```
┌──────────────────── cgroup pecko.scope: 2 CPUs · 2 GB · swap 0 · network off ─────────────────────┐
│                                                                                                        │
│ mic 16k ─▶ [EARS] gate→VAD→"hey Pecko" KWS→streaming ASR→endpointer (context thresholds)              │
│              │ partial+stable        │ tentative_final            │ final  ─────────────┐               │
│              ▼                       ▼                            │                     ▼               │
│ [BRAIN] router ─hit─▶ cached clip_id ───────────────────────────────────────────▶ ┌──────────────┐     │
│    │ miss                                                                         │ COMMIT GATE  │     │
│    ▼                                                                              │ (Spine)      │     │
│ llama-server: sys-prompt KV cached · prefill stable words · on tentative_final    │ C = final +  │     │
│ prepare first clause privately (gen id) · on final: validate prompt tokens        │ validated    │     │
│    │ chunk(gen, seq)                                                              └──────┬───────┘     │
│    ▼                                                                                     │ release     │
│ [VOICE] normalise → chunk policy → cache? → Piper synth → HOLD BUFFER (private PCM) ──────┘             │
│                                                       → ring buffer → audio callback → 🔊 first sample │
│                                                                                                        │
│ ◀── playback_state / barge_in ──  Ears raises VAD threshold while playing; barge-in stops < 100 ms    │
│                                                                                                        │
│ [SPINE] supervisor · shared monotonic clock · JSONL event bus (event-driven dispatch)                  │
│         critical-path controller: tracks C and R per turn, admits speculation on expected gain,        │
│         deadline-aware decode/TTS dispatch, tier ladder between turns                                  │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 outside the cgroup (cost disclosed): dashboard · harness · RAPL reader
```

**Process layout:** `llama-server` (C++) in its own process. Ears + Voice + router + orchestrator in one Python process with threads (ONNX Runtime releases the GIL). Split later only if measured contention says so.

**Core plan on 2 CPUs (start here, then measure serial vs fixed split vs phase lending):**

| Phase | CPU A | CPU B |
|---|---|---|
| idle | Ears gate/VAD/KWS (near 0) | nothing (workers block, spinning off) |
| user talking | Ears VAD + ASR | Brain prefill of stable words |
| pause → commit | Ears endpointer + speculative ASR finish | Brain prepares first clause → Voice synth into hold buffer |
| Pecko speaking | Voice TTS + Ears VAD | Brain decode, **only if** `upper(decode batch) + upper(next TTS) + guard ≤ buffer` |

**Deadline-aware dispatch rule (Spine):** while audio plays, the next decode batch runs only if it cannot starve TTS. Otherwise TTS goes first or the batch is shortened. This is a best-effort deadline on Linux, not hard real-time.

**Commit gate rule:** release held audio only when `final` arrives **and** the full serialized prompt tokens match what was prepared. On mismatch, rewind (full-attention models only), recompute and bump `gen`. Stale PCM is dropped.

---

## 4. Architecture, target 2: Android phone (after Linux is stable)

**Principle: same contract, same orchestrator, different engine profile.** The phone is essentially the laptop's **T2 tier** running on smaller hardware, so the degradation ladder and the smaller-device bonus share one mechanism.

```
Android phone (Termux, no root, airplane mode)
  mic ─▶ sherpa-onnx: VAD + KWS "hey Pecko" + streaming Zipformer  ─┐
                                                                    ├─ same JSONL contract, same Python orchestrator
  llama.cpp built in Termux: Qwen3-0.6B Q4_0, ctx 512–1024          ─┤  (router + cache identical)
  sherpa-onnx: Piper low voice + cached clips ─▶ speaker            ─┘
  Spine-lite: big-core affinity · thermal + battery telemetry · ladder triggered by throttling
```

| Item | Phone choice | Status |
|---|---|---|
| ASR / VAD / KWS / TTS | **sherpa-onnx** (one runtime for all four) | sherpa-onnx lists Android arm64, streaming ASR, VAD, KWS, TTS, Piper voices **[verified docs]** |
| LLM | **llama.cpp built natively in Termux** | Termux build documented for `llama-cli`; `llama-server` "should work" **[verify]** |
| Endpointer | VAD + transcript cues + calibrated timer (Smart Turn only if ONNX runs) | same as laptop T2 |
| Limit | the phone is the limit. Declare SoC/RAM; pin to big cores with `taskset` if allowed **[verify]**; no cgroups without root | state honestly |
| Energy | battery `current_now`/`voltage_now` from `/sys/class/power_supply/` if readable **[verify per device]**; otherwise CPU-seconds, labelled as **not joules** | |
| Degradation | thermal zone temps / tok/s drop → ladder steps down (shorter ctx, n_predict, cache-first) | real throttling, logged |
| Audio I/O | **highest risk.** Termux PulseAudio for mic/speaker **[verify]**. Fallback: WAV-in mode (recorded request streamed at real time) + playback, labelled | |

**Phone spike (45 min, one person, right after Linux M1):** in Termux, build llama.cpp and run Qwen3-0.6B (record tok/s), then try sherpa-onnx (pip or source build) with one streaming ASR on a WAV file. **Gate:** both run → P1 is a go. Either fails → phone becomes measured-components-only (still bonus evidence) and nobody sinks more time.

**Stretch beyond Termux (only if everything else is done):** native app from sherpa-onnx's Android demos plus llama.cpp's Android example. Too slow to integrate in this window, so it is said as future scalability, not promised.

---

## 5. Controller (Spine), built in layers. Each layer ships only if it beats the one below

1. **Ladder with hysteresis (must ship).** Signals: PSI `some` deltas (short window), `memory.current/max`, ASR backlog, buffer level, tok/s; on phone, temperatures and tok/s. Down after sustained risk, up after dwell. **Reset regime history when the cap changes.** A tiny miss window is not a p90 estimator.
2. **Latency-first action selection.** 12–24 **profiled** actions (model, threads, ctx, n_predict, chunk bounds, speculation mode, serial vs concurrent schedule). Feasible = quality floor (Wilson lower bound), cut-off and underrun budgets, memory transition peak + guard ≤ limit, CPU/energy ≤ baseline budgets. Pick min (p90, p50, energy). Use `spine/research/latency_v2/spine_latency_core.py::choose_latency_action`.
3. **Critical-path speculation admission.** At most one attempt per turn: `E[gain] = p·g − (1−p)·d_fail`, where g and d_fail come from the `max(C,R)` model including ASR contention. Admit only if positive, within the energy/memory budget and keeping the ASR backlog stable. Kill it from the shipped path if the paired gain is < 50 ms.
4. **Chunk planner.** Causal: after each stable boundary, compare "release now" with "wait for the next natural boundary (≤ 12 words)" using forecasts for 2 chunks. Offline oracle `optimize_chunks` gives the gap. Start time `T0* = max(C+d, max_k[r_k + d − Σ_{j<k} D_j])`.

**The first decisive experiment (before building layers 2–4):** a warm, instrumented baseline on a few ordinary, hesitation and correction turns under **1 and 2 CPUs**, logging endpoint, final ASR, prefill, first token, text release, PCM-ready and playback. It shows whether **C or R dominates**, and that decides where the next hours go.

---

## 6. Latency targets (estimates; owners replace with `[MEASURE]`)

| Segment | Owner | B0 (est.) | Pecko target |
|---|---|---|---|
| acoustic end → commit C | Ears + Spine | 0.7–2.5 s (silence timer + whole-clip ASR) | 150–300 ms |
| acoustic end → first clause PCM R | Brain + Voice | 2–6 s (full reply) | ≤ C on hit turns (hold-and-release), ~0.5–0.8 s on misses |
| **first real-answer audio = max(C,R)+d** | Spine | **≈ 3–8 s** | **< 1 s p50, < 1.5 s p90** |
| cached intent | Brain + Voice | same | ≈ C + d |
| phone (T2 profile) | Mobile | n/a | report honestly; no target until the spike |

---

## 7. Proof: master ablation (same cap, same paired held-out turns)

| Step | Adds | Owner | p50/p90 | gap s | CPU-s/turn | J/turn | WER | cut-offs | answer score |
|---|---|---|---|---|---|---|---|---|---|
| A0 | B0 default stack | Spine | `[MEASURE]` | | | | | | |
| A1 | streaming ASR | Ears | | | | | | | |
| A2 | endpointer (context thresholds) at matched cut-off risk | Ears | | | | | | | |
| A3 | system-prompt KV cache | Brain | | | | | | | |
| A4 | clause-streamed TTS (v1 rule) | Voice | | | | | | | |
| A5 | early prefill + speculative ASR finish | Brain + Ears | | | | | | | |
| A6 | hold-and-release + event dispatch | Spine | | | | | | | |
| A7 | router + cache-first | Brain + Voice | | | | | | | |
| A8 | critical-path admission + chunk planner | Spine | | | | | | | |

**Extra v2 comparisons (only if time):** confidence-only vs critical-path admission at matched budget · fixed clause vs causal planner vs oracle · periodic vs event dispatch · serial vs split vs lending.
**Degradation:** cgroup caps 2/2 GB → 1.5/1.5 → 1/1.25 (announced, between turns): static T0 vs static T2 vs ladder. **Phone:** a sustained-use run where throttling happens naturally, plotting tok/s, temperature, tier and latency.

---

## 8. Plan (order fixed, the team sets the clock)

| Step | Must be true | Who |
|---|---|---|
| **L0 now** | repo + first commit · contract v2 · `common/clock.py`, `common/log.py` · cgroup wrapper · models in `models/` · airplane test | all, Spine leads |
| **L1 ASAP** | half-baked loop on Ubuntu under the cap: "hey Pecko" → ASR → llama-server → Piper → speaker | all |
| **L2** | B0 runs + **decisive experiment (§5)**: C vs R known at 1 and 2 CPUs | Spine |
| **P-spike** | 45-min Termux spike, go/no-go (§4) | Voice (default), Brain helps with llama.cpp |
| **PC2 12 AM** | streaming, endpointer, KV cache, router + cache, hold-and-release v1, ladder, dashboard v1, A0–A4 measured | all |
| **L4 ~hour 15** | integrated and stable on Ubuntu, A5–A7, degradation demo. **No new laptop features after this.** | all |
| **P1** | phone loop in T2 profile (or WAV-in mode), phone numbers + throttling run | Mobile owner + one helper |
| **L5** | held-out 60 turns × 3, ablations, README, deck numbers, backup video (laptop **and** phone) | Spine + Sir Jabin |
| **6:30–7:30 AM** | submit (not 7:59) | Sir Jabin |

**Rule:** the phone never blocks the laptop. If L4 slips, P1 shrinks to the spike's measured numbers.

---

## 9. Risks (top 8)

| # | Risk | Mitigation |
|---|---|---|
| 1 | Pecko hears itself | headphones/wired speaker, `playback_state`, VAD 0.8 + 250 ms while playing, half-duplex switch |
| 2 | Indian-accent WER | team-voice bake-off, hotwords, Small not Tiny at T0 |
| 3 | KV rewind fails | rewind is a bake-off gate; Qwen3 default |
| 4 | Speculation slows C (contention) | critical-path admission; kill if gain < 50 ms |
| 5 | RAM > 2 GB (mmap counts) | 400 MB headroom, KV q8_0, ctx limits |
| 6 | Phone audio I/O in Termux | WAV-in fallback, labelled; spike gate |
| 7 | Phone throttling makes numbers noisy | report temperature with every phone number; paired runs |
| 8 | Rules: history, README, late submission | commit often, README grows with the build, submit by 7:30 |

---

## 10. Rejected (do not reopen)
Weighted quality-product objective · "max quality under SLO" planner · v1 `L+λE+λG` as the shipping objective (kept only in the study notes) · periodic 200 ms gating of first audio · claiming Bayesian endpointing or speculation as new · fillers in the headline · Docker · Windows target · native Android app inside this window · plus everything in v1's rejected list (Whisper as main ASR, Porcupine, 8B models, Laya/CLM/Jev as the generator, speech-to-speech models, draft speculative decoding, RL controllers).

---

## 11. Where everything lives
`CLAUDE.md` (build rules) · `docs/CONTRACT.md` · `<role>/SPEC.md` (ears, brain, voice, spine, **mobile**) · `spine/research/` (v1 design + v1 math) · `spine/research/latency_v2/` (revision, latency core, audits, supplied code) · `docs/study_guide.md` · `docs/pitch_deck.md`.

## Sources (new in v2)
- Spine latency revision: `spine/research/latency_v2/spine_latency_revision.md` (its own source list)
- sherpa-onnx supported functions and platforms: https://pub.dev/documentation/sherpa_onnx/1.13.5/
- llama.cpp Android/Termux build: https://github.com/ggml-org/llama.cpp/blob/master/docs/android.md
- Raux & Eskenazi 2008: https://www.cs.cmu.edu/~antoine/papers/raux_sigdial08.pdf · Endpoint Anticipation: https://arxiv.org/html/2606.13450v1 · PredGen: https://arxiv.org/html/2506.15556v2
