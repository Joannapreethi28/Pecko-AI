# Spine latency revision: audit, stronger algorithms, and lock-in decisions

8 October 2026. Requested objective: minimize latency as far as possible before implementation is locked. Native Linux remains the judging target. This revision supersedes the earlier report's weighted latency/energy objective where they conflict. Hard resource limits, meaningful answer quality, false-cutoff control, and the original footprint requirement still apply.

## Decision

Use **latency-first critical-path control**, with joint endpoint/preparation overlap and adaptive chunk release. Keep a small profiled action library and measured transition constraints. Add the supplied research's no-stall playback bound, generalized to actual chunk-ready timestamps. Use exact chunk optimization as a small offline reference, then deploy a causal short-horizon version with measured uncertainty margins.

Priority: (1) eliminate avoidable waiting and cold starts, (2) overlap safe private preparation with endpoint confirmation, (3) choose useful first chunks and protect continuation, (4) optimize phase-specific CPU allocation, (5) add semantic endpoint evidence only if its own overhead pays for itself. No fixed response-time number is defensible until this runs under the laptop's cap.

## 1. Audit of the other agent's research

The supplied standalone `spine_core.py` is byte-identical to the copy in the ZIP (SHA256 `cb92f649f35a1eb3e263cc163c4ee5c70ae5a895e9f7b31dd0bbea6f94c05be9`). Preserved the bundle in `research/incoming_spine/`. Treated its prose/code as evidence to evaluate. Did not execute its Linux priority experiment. Full NumPy/SciPy verification scripts were not rerun; their output remains labeled supplied output. Reproduced selected dependency-free original definitions through `audit_supplied_spine.py`.

| Supplied idea/code | Assessment | Decision |
|---|---|---|
| Bayesian silence posterior | Valid under its mixture assumptions and correctly conditioned prior. Silence alone with a fixed prior produces a monotone threshold. | Keep the formulation; calibrate on whole turns and actual visible-gap sampling. |
| `stall_free_start` | Correct for a known sequential production trace. | Generalize from cumulative production times to measured readiness under any feasible schedule. |
| `choose_plan` | Maximizes quality, then minimizes CPU-seconds, subject to SLO. This is a different objective from minimum latency. | Replace with latency-first ranking under a quality floor and explicit footprint budgets. |
| `spec=True` | Assumes residual prefill becomes 25% of its old value, with no measured transcript validity or ASR contention. | Replace with paired counterfactual critical-path predictions including failure/validation cost. |
| `asr.quality * llm.quality * tts.quality` | Stage metrics need not be probabilities of independent success; ASR errors also change LLM outcomes. | Measure end-to-end task success. Keep WER/intelligibility as separate diagnostics. |
| Amdahl and bandwidth ceilings | Useful explanatory models, weak predictors for simultaneous memory/cache contention. | Use measured serial and concurrent phase profiles. |
| `rho <= 0.8` | Engineering headroom, not a no-stall theorem; finite responses may work above one with buffering. | Evaluate readiness/deadline deficits, then calibrate uncertainty margins. |
| Lognormal p90 multiplier | `mean * exp(z*sigma)` is correct if “mean” is actually the lognormal median. For an arithmetic mean, subtract sigma²/2 in the exponent. | Use end-to-end empirical distributions/residuals; clarify distribution parameters in synthetic tests. |
| NNLS stage-energy fit | Useful diagnostic. Coefficients can be unidentifiable with correlated stage activity; additive energy ignores interactions. | Validate held-out whole-turn energy. Do not report fitted stage coefficients as directly measured energy. |
| Tier feedback | Old misses persist through `replan_on_cap_change`; repeated noisy alarms can cause unnecessary downgrades. | Reset regime-specific history; base ordinary replans on current profiles and deadline risk, with an immediate safety fallback. |
| `nice=19` experiment | Supplied output demonstrates scheduler sharing on that test machine. | Does not establish protection from memory bandwidth, cache, native-kernel nonpreemption, or quota effects. |

Two reproductions using the original definitions, with synthetic inputs:

- At the same quality, original selection predicts **3.825 s** while another feasible serial plan predicts **2.249 s**. This proves objective mismatch, not a real speedup. The alternative uses two threads in each stage **sequentially**. The sum of those counts exceeds two, but that is not a cap violation unless they overlap; distinguish serial from concurrent plans explicitly.
- One old-regime miss survives a cap replan, so one miss in the new regime triggers another downgrade. Also, with independent 10% per-turn misses, a two-of-three alarm fires with probability 2.8% per independent block. Across 25 disjoint blocks, at least one such alarm occurs with probability 50.8%. A p90 target naturally permits occasional exceedances; a tiny miss window is not a p90 estimator.

The endpoint simulator also uses `E[1/(N+1)]` as an event prior, whereas pooling every one of N pauses plus one endpoint per turn gives `1/(E[N]+1)` before visibility filtering. In its synthetic distribution these are 0.3896 and 0.3571. It clips invisible short pauses up to the visibility threshold rather than sampling the stated conditional distribution. Correct the sampling/conditioning before trusting its reported gain curves. AUC alone does not establish a calibrated posterior or real endpoint savings.

## 2. Change the optimization objective

The deployable feasible set must pass measured quality, cutoff, underrun, memory-transition and CPU scheduling checks. Within that set choose lexicographically:

    minimize (p90 first-content-audio latency, p50 latency, whole-turn energy).

This prioritizes tail responsiveness; retain a p50-first frontier as a reported alternative so a mean/tail trade-off is visible. Energy and CPU-seconds must remain within declared budgets derived from the fair baseline if claiming lower footprint. A Pareto trade-off is reported honestly when faster response spends more energy. We should not silently buy milliseconds by breaking qualification requirements.

Do not use a weighted quality product, and do not choose the richest model merely because it meets an SLO. Select the fastest model that passes the agreed quality floor. Once this is fixed, measure p50/p90 on paired held-out speech. No optimizer can establish an absolute global minimum from incomplete hardware/model profiles.

## 3. Optimize the last dependency, not a serial sum

Let C be the time at which final endpoint, final transcript compatibility, and validation permit output. Let R be the time usable first content PCM is ready. Times share an origin; subtract acoustic end when reporting TTFA. With an output-device delay d:

    P_first = max(C, R) + d.

If the response was prepared privately before C, it can be released when commitment completes. C must include validation and cancellation checks. If finalization changes the prompt, R becomes the ready time of repaired or recomputed audio. This equation does not let the application play unvalidated speech.

For a proposed optimization changing (C0,R0) to (C1,R1):

    gain = max(C0,R0) − max(C1,R1).

The resource controller must predict both paths. Under unchanged C and h seconds of useful preparation savings:

    gain(h) = min(h, max(0, R0−C)).

Past that crossover, more acceleration has zero first-audio benefit. It can still buy continuity buffer, so the next relevant deadline then becomes the second audio chunk.

Synthetic example: C=600 ms and R=900 ms. Reducing R to 500 ms saves 300 ms. Reducing it again to 200 ms saves nothing more at first audio. If speculative contention instead moves C to 1000 ms, the “accelerated” preparation makes first audio 100 ms slower than the original 900 ms.

Consequences:

1. Keep one resident model instance and warm audio/runtime paths; use a valid static prompt-prefix cache. Include resident pages/workspaces in the memory cap. Cold starts remain a separate reported test.
2. During speech, optionally prefill stable prefixes; during early silence, optionally prepare the first clause. Cache compatibility uses complete serialized prompt tokens and positions, not just matching words. Do not share one mutable KV buffer between a speculative branch and committed history.
3. Admit work using expected **critical-path** gain, not number of hidden tokens. Estimate expected gain as p*g − (1−p)*d_fail; filter by energy/memory budgets. At most one attempt per turn initially. Repeated speculation is considered only after measured benefit exceeds invalidation/cancellation costs.
4. Stop or pause private generation at the useful first-clause/buffer target. Filling an entire reply early can waste bandwidth and postpone ASR finalization.
5. Once R<=C, concentrate optimization on finalization/endpoint/validation. Once C<R, concentrate on the remaining prefill/decode/TTS dependency.

This extends the earlier admission gate rather than claiming speculation is new. [Endpoint Anticipation, 2026](https://arxiv.org/html/2606.13450v1) already prepares LLM/TTS work before turn completion and evaluates compute redundancy. [PredGen](https://arxiv.org/html/2506.15556v2) already verifies input-time candidates. Our narrower hypothesis concerns **critical-path saturation and shared-cap interference**.

## 4. Generalize the supplied playback bound

Let r_k be the actual/predicted PCM-ready time of chunk k, D_k its playable duration, and C its valid commitment gate (one common gate for the validated response). A no-gap playback beginning T0 must satisfy:

    T0 >= C+d
    T0 + sum_(j<k) D_j >= r_k+d, for every k.

Thus the exact earliest start for the known trace is:

    T0* = max(C+d, max_k [r_k+d − sum_(j<k) D_j]).

Proof: each inequality is necessary for chunk k to exist when needed; their maximum satisfies all inequalities. It is exact for the stated chunk/device model. The supplied cumulative-production formula is its sequential special case. Actual sound-card buffering may need a richer device model.

Do not wait for the entire generated response to learn r_k. That would destroy streaming. This expression is an offline optimum for known traces and a predictive planning objective at runtime. Forecast error must be measured; whole-turn no-stall guarantees require a valid joint forecast, not point estimates of unknown text.

### Chunk boundaries are optimization decisions

Represent legal text chunks as edges i→j, where i/j are token or word boundaries. Exclude unacceptable prosody/semantic boundaries before optimizing. Each edge has profiled release time R_ij, synthesis duration T_ij, playable duration D_ij and energy E_ij. Keep speech rate and answer content controlled; creating slow filler to inflate the buffer is not an improvement.

For fixed LLM release times and a single TTS lane, a label at boundary i stores `(F, D, Z, E)`: previous TTS finish, accumulated playable audio, minimum start bound so far, and energy. Extend it by:

    F' = max(F, R_ij) + T_ij
    Z' = max(Z, F'+d−D)
    D' = D + D_ij
    E' = E + E_ij.

Initialize F=D=E=0 and Z=C+d. Retain nondominated labels at each boundary. A label dominates another if it has no larger F/Z/E and no smaller D. At the final boundary, choose smallest Z, then energy. This dominance is valid for the fixed edge-cost model with identical continuation possibilities; it must include TTS state if future costs depend on prior speech state.

For a shared CPU serial schedule, insert the measured decode time before each synthesis; text release is endogenous. Never reuse fixed overlapping release times for a serial plan. The reference core implements both clearly separated modes. For 2+ CPUs, also profile split lanes and dynamic lending; backend/cache contention can make overlap worse.

The reference optimizer is exact for its supplied deterministic graph, with a frontier size limit that fails explicitly. It is not a claim of polynomial complexity or global neural pipeline optimality. Use integer time/energy units or a declared quantization before production ranking; near-equal floating values can change tie-breaks.

### Causal deployment

After a token/clause becomes stable, compare “release now” against “wait for the next eligible boundary,” with forecasts for at most the next two chunks. Enumerate only a small candidate set (e.g. natural boundaries up to 12 words), commit the first action, and replan on actual events. Unknown future text stays a forecast. Validate the complete deployed policy, including its forecast errors; the offline optimizer supplies a useful oracle gap.

When audio is playing, a new LLM decode batch can run only if:

    upper(next decode batch time) + upper(next TTS time) + guard <= playable buffer B,

unless TTS has an independently reserved feasible lane. Otherwise prioritize the next TTS job or shorten the compute batch. Include already-running nonpreemptible work and capture/VAD service. This is deadline-aware dispatch, not a hard-real-time guarantee on a general Linux scheduler.

## 5. Calibrate buffering at the turn level

A 20% fixed headroom or arbitrary 80th-percentile bootstrap threshold is a heuristic. A stronger optional method is to record one residual per calibration turn:

    score_i = actual required no-gap start_i − predicted required start_i.

Freeze the complete chunk/controller policy before these runs. Choose rank `ceil((n+1)*(1−alpha))` from sorted calibration scores, clipped below at zero to avoid negative safety margins. If the rank exceeds n, there is no finite bound from that sample: return infinity/unavailable. Add this margin to the predicted start, while still waiting for actual first PCM and commitment.

This is a one-sided split-conformal construction: coverage is marginal across exchangeable turns for a frozen predictor/policy. It is not a per-turn certainty or a guarantee under new caps, speakers, thermal states, or adaptively selected policies. Separate regimes or calibrate a fixed regime selector. Do not estimate a margin for every candidate and select the smallest using the same data without correcting selection. [Conformal prediction tutorial](https://arxiv.org/html/2107.07511v6), [beyond-exchangeability limitations](https://arxiv.org/abs/2202.13415).

For ongoing receding decisions, score the maximum deficit over the complete frozen policy's turn trace. Treating each correlated chunk as an independent calibration example is invalid. If only heuristic calibration is possible in the hackathon, label it accordingly and compare actual underrun rate on unseen turns.

## 6. Improve endpointing without borrowing imaginary confidence

The supplied posterior is:

    P(end | still silent at t, z) = p_z / [p_z + (1−p_z) S_pause(t | z)].

p_z must be the prior conditional on exactly the text/prosody evidence and visible-gap selection used in deployment. If pauses are left-truncated at 150 ms, the prior must also refer to surviving to that detection threshold. Do not multiply in the same silence evidence twice. The final-gap “survives forever” approximation is only a decision-horizon model of the present turn.

Conditional on fixed z and monotonically decreasing S, a posterior threshold is just a silence threshold. Richer gains require predictive information from text/prosody, or a lower-overhead observation/decision path. A 150 ms minimum observation delay is already a lower bound for that policy. Lowering it requires recalibrating noise/cutoff behavior; zero hangover is not a free gain.

Recommended implementation: precompute a lookup table of thresholds per calibrated evidence bin; update on transcript/prosody events and arm a timer for the next crossing. Cheap candidate bins can use sentence completeness, unfinished conjunctions, and transcript stability, but their probability values must come from labeled speech. A pretrained semantic model is eligible only if its CPU/RAM and contention costs are measured. No LLM classifier per VAD frame.

Choose endpoint policy on development data at **matched whole-turn cutoff risk**. Freeze it for the core scheduling ablation. Zero cutoffs in 60 independent turns still has a one-sided 95% upper bound of 4.87%; demonstrating an upper bound below 2% with zero events requires 149 independent turns. Replays of one utterance do not provide 149 independent speakers/utterances. Multiple policy selection needs separate calibration or a simultaneous correction.

Context-dependent endpoint thresholds have longstanding prior art: [Raux and Eskenazi, SIGDIAL 2008](https://www.cs.cmu.edu/~antoine/papers/raux_sigdial08.pdf). [Projection of Turn Completion, SIGDIAL 2021](https://aclanthology.org/2021.sigdial-1.45/) also anticipates turn endings. The contribution cannot be called “Bayesian endpointing” alone.

## 7. Remove smaller but avoidable delays

- **Use events for critical transitions.** First token, final ASR, PCM-ready and playback-watermark events should wake dispatch immediately. The earlier 200 ms loop is acceptable for slow pressure telemetry, not gating first audio; periodic gating could add up to one loop period.
- **Keep sessions/audio open and warm.** Record cold and warm results separately. Warmup is not excluded from deployment cost, and all resident data must fit the cap.
- **Expose runtime thread pools.** The inspected Piper implementation constructs default ONNX session options. ONNX Runtime documents default worker spinning and multiple thread pools. Explicitly tune counts and compare disabled versus bounded spinning under co-run load; spinning can improve isolated wake latency while wasting shared CPU. [Piper source](https://raw.githubusercontent.com/OHF-Voice/piper1-gpl/main/src/piper/voice.py), [ONNX Runtime documentation](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).
- **Verify what “streaming TTS” means.** Piper's inspected Python implementation yields synthesized chunks after sentence phonemization/inference; an iterator alone does not establish token-level acoustic streaming. Supply bounded meaningful clauses and measure input-text → first PCM. Keep one voice loaded.
- **Use meaningful early content.** Prompt for the answer first, then explanation. Test answer correctness/qualification; never remove a necessary condition simply to speak earlier. Keep this prompting identical in controlled scheduler comparisons.
- **Treat deep TTS changes as a separate project.** [X2Streaming-TTS, 2026](https://arxiv.org/html/2608.18661v1) explores causal token-level synthesis, commitment and speech-state inheritance. This supports the direction, but the inspected source does not establish performance under our CPU cap. Do not transfer its headline timings to Piper or assume state inheritance can be added as a wrapper.

## 8. What is stronger, and what is still research

The specific candidate contribution is **deadline-constrained critical-path control of speculation and chunking under a shared CPU cap**, evaluated at matched task quality and cutoff/underrun risk. Its distinguishing decision is whether to spend resources on earlier first audio, additional playable buffer, or finalization, based on which dependency is currently limiting.

The ingredients—Bayesian endpointing, speculative generation, DAG/Pareto optimization, playback buffering, and conformal calibration—already exist. Their integration is a systems hypothesis. Additional papers found in this pass further narrow the novelty claim; they do not justify a “first” claim.

Run these additions to the earlier ablation plan:

| Comparison | What it isolates |
|---|---|
| Original objective vs latency-first objective with same feasible actions | Selection objective |
| Fixed clause length vs causal two-chunk planner vs known-future oracle | Boundary choice and remaining predictive gap |
| Confidence-only speculation vs critical-path admission, at matched budget | Saturation and ASR contention |
| Fixed headroom vs turn-calibrated start, at matched underrun rate | Unnecessary startup buffer |
| Fixed endpointer vs calibrated context thresholds, at matched cutoff | Endpoint evidence, separately from scheduling |
| Periodic dispatch vs event-driven dispatch | Avoidable coordination wait |
| Serial vs fixed split vs phase lending under the same cap | Actual concurrency value |

Report both first-content TTFA and gap duration. Playing a tiny chunk and then stalling must not masquerade as a win. Include cancellation/wasted work, memory transition peaks, quality, CPU-seconds and gross/adjusted energy. Never compare successful speculation cases alone with failures; use paired complete turns.

## 9. Artifacts and verification

- `spine_latency_core.py`: generalized playback bound, critical-path gain, corrected conditional posterior, optional finite-sample buffer quantile, latency-first action selection and exact finite chunk-graph optimizer.
- `verify_latency_core.py`: checks 2,000 minimal-start traces; 600 graphs against 11,561 exhaustively enumerated paths; signed contention/saturation examples; rank coverage enumeration; endpoint monotonicity; constraint rejection.
- `audit_supplied_spine.py`: reproducible objective/history counterexamples from selected original source definitions.
- `latency_verification.json` and `supplied_code_audit.json`: machine-readable results.

All checks pass. An initial exact-ranking comparison exposed floating-point ties in energy; exhaustive graph tests now use exactly representable binary fractions to test the combinatorics, while general random floats remain in the playback checks. Deployment should quantize profile units explicitly. This does not validate measured runtime speed, prediction accuracy, model quality, or real Linux energy.

Synthetic eight-word example (same speech rate, all text preserved):

| Policy | First chunk ready | Earliest gap-free start |
|---|---:|---:|
| One word per chunk | 225 ms | 785 ms |
| Whole response | 960 ms | 960 ms |
| Optimized 3–3–2 words | 435 ms | 435 ms |

Immediate playback of the one-word chunks incurs 560 ms of total gaps. This demonstrates a failure of “smallest chunk is always fastest,” not an expected measured benefit. The optimizer uses known synthetic future timing; live performance must use causal forecasts.

## 10. Lock now; measure before locking the remaining details

**Lock the design:** latency-first constrained ranking; explicit serial/concurrent schedules; max-of-dependencies timing; event-driven first-audio dispatch; conservative prompt validation; meaningful chunk boundaries; deadline protection; complete-turn paired evaluation; reject unsupported configurations rather than fabricate feasibility.

**Keep as measured decisions:** model winners, endpoint thresholds, private-prefill versus full-clause speculation, useful speculative buffer size, core allocation, spinning settings, chunk bounds and calibrated startup margin. These variables depend on real co-run traces. The supplied synthetic tables cannot settle them.

The smallest decisive Linux experiment is a warm, instrumented baseline with a few ordinary/hesitation/correction turns, under 1 and 2 CPUs, logging endpoint/final ASR/prefill/first token/text release/PCM/playback. That reveals whether C or R dominates and which proposed optimization can actually remove the most milliseconds. Profile the dominant path first, then run the held-out evaluation required for claims.
