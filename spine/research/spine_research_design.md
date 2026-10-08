# SPINE research and implementation specification

8 October 2026, IST. Scope: HNX26EPS08, offline CPU-only ASR → LLM → TTS. Native Linux confirmed by the user. This is a research/design deliverable, not a measured performance claim or permission to change another role's interface. Read all five supplied context files. No inference stack, weights, Linux enforcement, or hardware energy counters were available for measurement in this Windows workspace.

## Recommendation

Implement **a profile-driven, phase-aware controller for a capped voice cascade**. Its decision joins three things: protect incoming speech and outgoing audio deadlines; admit speculative work only when its expected latency benefit exceeds its contention and energy costs; select a quality-tested feasible configuration including transition memory and loading time.

The defensible hypothesis is: under changing CPU/RAM limits, joint control improves the latency–energy trade-off relative to a tuned static streaming stack and a reactive pressure ladder, at comparable task success and cutoff rates. This is a proposed systems contribution. Novelty and benefit remain hypotheses until the ablations succeed. Do not claim a new scheduler theory, new quantizer, or the first on-device speculative assistant.

Prefer one coherent contribution over six unrelated tricks. The core works without speculation; speculative generation is an experimental action, not a prerequisite. A small finite search is sufficient. No reinforcement learning, training a turn model, GP optimizer, or online quality bandit is needed.

## 1. Prior art and the gap it actually leaves

Primary sources were accessed on 8 October 2026. “Full sections” means relevant methods/evaluation passages were inspected, not every appendix. Abstract-only sources must not support detailed implementation claims.

| Source and evidence read | What is established | What we can investigate beyond that setting |
|---|---|---|
| [PredGen, 2025](https://arxiv.org/html/2506.15556v2), methods and experiments §3–4 | Generates/verifies response candidates during input. Experiments use an RTX A5000; input is streamed text and ASR is excluded. | Measure the cost of real ASR competing with speculation on the same capped CPU. Input time is not necessarily unused compute. |
| [Personalized Predictive ASR, Interspeech 2023](https://arxiv.org/html/2305.13794v1), methods §2 and evaluation §3 | Prefetch from partial speech, confidence gating, latency versus failed-prefetch cost. | Add measured contention penalties and energy cost, rather than inventing confidence-gated prefetching. |
| [Voice-Light, September 2026](https://arxiv.org/html/2609.20995v1), controller §7 and evaluation §6–8 | Private speculative text/audio, transcript validation, generation IDs and acknowledged playback history; GPU deployment. | Hard-cap scheduling and energy evaluation. Its endpoint-to-server-audio metric differs from acoustic-end-to-speaker-audio. |
| [ElastiLM, MobiCom 2025](https://arxiv.org/html/2409.09071v2), motivation and switching evaluation | Joint prompt/model elasticity; explicitly addresses switching overhead through specially prepared submodels. | Full speech pipeline with off-the-shelf separately loaded models and audio deadlines. Switching-cost awareness itself is established. |
| [NestDNN, MobiCom 2018](https://arxiv.org/abs/1810.10090), abstract and author-hosted system overview | Dynamically selects resource/accuracy trade-offs for concurrent mobile vision models. | Voice-specific transcript commitment, incoming audio backlog and continuous playback. Generic adaptive resource allocation is established. |
| [ApproxNet, 2019](https://arxiv.org/abs/1909.02068), abstract | Adapts embedded vision inference to content and contention. | Same limitation: resource-aware inference is not new by itself. |
| [PRAS, Journal of Systems Architecture 2025](https://www.sciencedirect.com/science/article/pii/S1383762125002693), abstract/introduction | Request-adaptive edge pipeline configurations and accuracy profiling with bandits. | A single interactive voice turn has audio deadlines and no live ground-truth answer labels. Avoid claiming joint pipeline selection is new. |
| [CORE, MLSys 2026](https://proceedings.mlsys.org/paper_files/paper/2026/file/136b9a13861308c8948cd308ccd02658-Paper-Conference.pdf), §5–7 | Coordinates CPU/GPU/memory frequencies for mobile LLM latency and energy. | Runtime stage concurrency under a fixed CPU-only cap. We do not implement DVFS or transfer its performance figures. |
| [Cross-platform conversational agent, 2026 journal pre-proof](https://wiki.edgeaifoundation.org/wp-content/uploads/2026/09/1-s2.0-S1383762126002997-main.pdf), architecture §3 and measurements §5–6 | Moonshine–quantized LM–Piper pipeline; measures footprint, speed, net power and energy efficiency across devices. | Broad “we measure a local voice stack's energy” is already covered. Study dynamic caps and controlled scheduling ablations. |
| [On-device speculative tool execution, 6 October 2026](https://arxiv.org/html/2610.07641v1), §2–3 | Partial-ASR tool prediction with validation and fallback on Android. Uses an NPU LLM and remote search. | Not an offline CPU-only baseline. Its fallback latency claim does not establish a no-slowdown guarantee under our shared cap. |
| [Pushing the Limits of On-Device Streaming ASR, April 2026](https://arxiv.org/html/2604.14493v1), hardware §3.3 and quantization tables | ASR context/chunk/precision trade-offs; CPU measurements pinned to 32 EPYC cores. | Local co-running throughput and WER under 1–4 CPUs. Model file size is not total resident pipeline memory. |
| [SpeculativeETD, ACL 2026](https://aclanthology.org/2026.acl-long.2094/), abstract | Lightweight local detector plus stronger server classifier; public turn-detection data. | Useful evaluation ideas, but the server path fails the offline gate. |

Search included capped CPU speculation, voice scheduling/energy, adaptive edge pipelines, elastic inference, and citations from the closest voice papers. No inspected source establishes the exact proposed combination. That is a bounded search result, not proof of uniqueness. The best gap is **the interaction between speculation, deadline protection, and transition feasibility under a hard shared cap**. A generic hysteresis ladder is too weak as the main novelty claim.

## 2. Where Spine can score

| Rubric | Concrete work | Evidence needed |
|---|---|---|
| Latency, 25% | Phase allocation and bounded clause release; avoid speculative ASR slowdown | Paired acoustic-end → first content audio p50/p90 against default and tuned baselines |
| Footprint, 25% | Limit thread pools; block idle workers; bound buffers/KV; reject wasteful speculation | CPU-seconds/turn, total cgroup peak RAM, gross and idle-adjusted joules/turn |
| Contribution, 20% | Joint controller with explicit benefit gate and transition feasibility | Compare with best static streaming configuration, pressure ladder, and controller ablations |
| Quantization/offload, 15% | Brain/Ears provide measured precision trade-offs; Spine enforces accounting | Same-model precision comparisons, task quality and full pipeline RAM. CPU-only means GPU/NPU offload is unavailable |
| Degradation, 15% | Quality-tested feasible configurations, recovery hysteresis, no stale playback | Dynamic cap trace, failure rate, task success, cutoff rate, switch time/memory and audio gaps |

These are opportunities, not predicted marks. Smaller models, streaming, and caching are engineering choices with prior art. Report “successful turns per joule” or quality and energy separately; “quality per watt” alone ignores completion time.

## 3. Final algorithm choices and model boundaries

### Three controller options

| Option | Benefits | Limitations | Decision |
|---|---|---|---|
| Reactive pressure ladder with hysteresis | Easy, tiny overhead, reliable fallback | Reacts after degradation; cannot price speculation or transition feasibility well | Implement as comparator and emergency fallback |
| Finite profile-driven receding decisions | Explainable, no training, supports measured joint constraints and switch costs | Needs representative solo/co-run profiles; predictions can fail | Recommended main controller |
| Learned bandit/RL or full optimization framework | Potentially broad adaptation | Small data, no live quality labels, exploration can harm the demo | Reject for this build |

Spine's predictive models are **lookup profiles plus conservative residual margins**, a small binned speculation-validity estimator, and a deterministic pipeline timing recurrence. No new neural model is trained by Spine.

Keep the other roles' model ownership. A reference calibration stack is:

- Ears: [sherpa-onnx streaming Zipformer English 20M int8](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/index.html), with the team's VAD/wake-word. Compare one stronger Ears-selected streaming recognizer. The small model must pass measured WER/task tests; it is not assumed good enough.
- Brain: [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B), GGUF Q4_K_M in [llama.cpp](https://github.com/ggml-org/llama.cpp), non-thinking chat template. Evaluate Q8_0 only if memory permits. Compare the Brain role's stronger candidate before declaring the strongest feasible baseline. Download artifact provenance, license, runtime commit and quantization type must be recorded.
- Voice: [Piper](https://github.com/OHF-Voice/piper1-gpl), one English voice chosen by Voice; prototype with `en_US-amy-medium` if available in that runtime. Engine is GPL-3.0; voice license is a separate check. Test natural clause versus sentence synthesis.

These are executable candidate identities, not finalized performance winners. CPU model, runtime builds, total RSS/cgroup RAM and answer quality are unknown. Final model/quantization selection is a calibration decision; fabricating speeds, memory, or a universally “strongest today” baseline would undermine the research.

### Action library

Use at most 12–24 **profiled** actions initially, rather than profiling a Cartesian explosion. Each records active models, phase-specific worker concurrency/thread limits, context limit, maximum response tokens, first chunk policy, speculative mode and residency plan. Include serial and overlapping LLM/TTS schedules. Inactive stages use zero inference workers, with audio capture/VAD still active.

Three initial operational tiers use the same resident weights:

1. Normal: tested full context and answer budget, ordinary clause streaming, optional admitted speculation.
2. Constrained: speculation off; tested shorter context preserving system instructions/current request; fewer concurrently active inference workers; shorter answers only on task classes where quality passes.
3. Minimum: serialization/time-sharing at 1 CPU; minimum tested history and bounded chunks. If this cannot keep up, use a separately validated smaller-model configuration between turns, or report that the cap is below supported operation.

Do not assume short replies preserve quality, or that three model files can reside in 1 GB. A one-CPU system still handles capture/VAD while other stages run; an integer worker allocation is not an OS latency guarantee. Logical CPUs must be declared honestly. Any model switch flushes incompatible KV/ASR state. ASR weights/configuration change only at a safe boundary supported by Ears.

## 4. Math to implement

All times below are seconds, energy joules, and memory bytes. The companion script verifies algebra and deterministic model recurrences on synthetic inputs. It does not validate profile accuracy or hardware performance.

### 4.1 State and measured profiles

At decision time observe phase, incoming-audio backlog q in audio seconds, playable-output buffer B in audio seconds, final/partial transcript revision, current configuration, memory usage/limit, effective cpuset/quota, and pressure deltas. Profile each action under the actual cap both alone and with intended competitors: ASR service rate r, prefill time versus prompt length, decode rate, TTS time versus clause length/duration, full-turn CPU/energy, memory peak, and configuration transition costs.

Use medians for central predictions. Add held-out residual quantiles to form conservative engineering bounds, e.g. T_upper = T_pred + quantile_0.95(T_observed − T_pred). This is not a probabilistic guarantee under a new pressure regime. Use lower service-rate estimates; unprofiled concurrency is infeasible. Do not extrapolate Amdahl's law or assume independent stages under contention. Amdahl/roofline may explain profiles, not replace them.

For slow tracking, update a matched profile's mean with mu_new = (1−alpha)mu_old + alpha observation, initially alpha=0.2. Keep calibration bounds and an out-of-profile flag; do not erase conservative margins with a few fast turns. Invalidate profiles on model/runtime/thread/limit changes.

### 4.2 Incoming speech constraint

For interval Delta, arrival a_t in audio seconds and measured consumption rate r:

    q_next = max(0, q + a_t − r Delta).

During continuous capture a_t=Delta. Require predicted q_next <= Q_max; for a sustainable listening action require a conservative r >= 1+rho (initial rho=0.1, then calibrate). This is a fluid approximation: real chunk release and initialization delay must be included in trace replay. With r<1, long continuous speech inevitably grows backlog; a bigger queue postpones failure rather than fixing it. Cancel speculation when this constraint fails. Never silently drop input audio to improve latency.

### 4.3 First audio and playback continuity

Let R_k be the wall-clock release time of text chunk k, T_k its synthesis time and D_k the resulting playable duration. With one sequential TTS worker:

    F_k = max(R_k, F_(k−1)) + T_k
    P_1 = F_1 + d_audio
    P_k = max(F_k + d_audio, P_(k−1) + D_(k−1))
    gap_k = max(0, F_k + d_audio − P_(k−1) − D_(k−1)), k>1
    L = P_1 − t_acoustic_end.

F is PCM-ready time; P is audible playback start. The constant output-buffer approximation d_audio must be replaced by measured device behavior. R_k derives from measured prefill/decode and the chosen clause release, including speculation/promotion dependencies. Co-run T_k and decode rates must come from co-run profiles.

This recurrence captures the critical path instead of summing stage latency percentiles. For an immediate TTS decision while audio is playing, require next usable PCM to arrive before existing B runs out, allowing a guard margin. A predicted new buffer that appears after starvation cannot retroactively prevent a gap. Pause LLM work if that is the profiled way to meet the TTS deadline. Test 4/8/12-word maximum chunk waits with natural clause boundaries; no mid-word splitting or endlessly waiting for punctuation. Keep chunk policy identical in controller comparisons.

### 4.4 Quality and transition feasibility

For action a in a labeled task class, estimate end-to-end success Q_a on calibration recordings. Count a turn successful only if the answer is acceptable and the speech turn is handled correctly. Store WER and cutoff rate separately; neither alone equals answer quality. Use Wilson lower bounds as conservative screening on finite samples, not guarantees for unseen judges. Unknown task classes use the worst supported class profile.

For current action i and candidate j:

    M_transition(i,j) + M_guard <= M_limit
    L_transition(i,j) = L_j + load_time(i,j) + state_rebuild_time(i,j).

M_transition is a **measured peak** over loading/unloading; with co-residency it can include both models and workspaces. With unload-first switching it includes the service gap and subsequent rebuild. Do not double-count load time already present in a measured transition. A model file being memory-mapped does not make it free of the cgroup cap.

A sudden external RAM reduction below current committed working memory can cause failure before any controller responds. Test announced and unannounced reductions separately. For the live graceful-degradation demo, announce the next cap, downgrade and verify memory, then apply the cap. Report the warning interval. Do not describe this as recovery from arbitrary instantaneous OOM.

### 4.5 Controller objective

Build feasible set F(s) of profiled actions that pass CPU scheduling/cap, memory-transition, quality-floor, ASR-backlog and applicable playback-deadline checks. CPU use is governed by the parent cgroup; phase plans must include all workers and audio overhead. Worker-thread counts are configuration controls, not a substitute for enforcement.

For each candidate predict remaining first-content latency L_upper, incremental remaining energy E_upper, and late-playback gap G_upper using the profile/timing model. Add measured switch costs exactly once. Choose:

    a* = argmin_(a in F(s)) [L_upper(a) + lambda_E E_upper(a) + lambda_G G_upper(a)].

lambda_E has units seconds/joule; lambda_G is dimensionless. Quality remains a constraint. An energy-budget alternative is minimize latency with E_upper<=E_budget; record which version is used. Sweep lambda_E on calibration data to expose the frontier; lock it before test evaluation. Include the current action as a candidate. Pareto-prune only within comparable phase/residency/quality classes; a globally dominated steady-state action can be useful when switching to another costs time or memory.

Run decisions at phase boundaries and every 200 ms during active work; avoid busy polling. Change worker scheduling only at backend-supported safe points. Keep the chosen model through a turn. Require objective improvement > delta_switch plus a 2 s dwell for optional recovery/upgrades; hard feasibility failure bypasses dwell. Initial 200 ms/2 s values are tuning parameters, not optimality results. If F is empty, stop speculative work, use the supported emergency action if feasible, otherwise record a failed turn/unsupported cap.

This is exact minimization over a finite estimated action set, not a theorem of optimal control or a guaranteed p90 bound. Controller overhead is counted in the resource measurements.

### 4.6 Speculation admission

Start with at most one attempt per turn, after a stable partial transcript and early silence. Modes: none, incremental prefill, or private first-clause generation/TTS. Keep the committed endpoint policy unchanged so the controller effect is isolated.

Against no speculation, define p as probability the candidate is valid at final transcript; g as latency saved on valid work after contention/validation; d as extra delay on invalid work; E_s/E_f as incremental **whole-turn** energy on valid/invalid work. E_s may be negative. Expected net utility in seconds is:

    U = p g − (1−p)d − lambda_E [p E_s + (1−p)E_f].

Admit only if a conservative estimate U>delta_spec AND all feasibility checks hold. Let A=g+d−lambda_E(E_s−E_f). If A>0, the equivalent central-estimate gate is:

    p > (d + lambda_E E_f + delta_spec) / A.

For A<=0, use the direct inequality; dividing can reverse or invalidate the gate. Do not blindly clamp thresholds to [0,1]. If threshold>=1, reject; if it is negative, feasibility/validity rules still apply. Under parameter uncertainty, evaluate the worst utility over stored endpoint bounds; the central threshold alone is insufficient.

Toy example, not a measurement: g=0.35 s, d=0.12 s, E_s=0.2 J, E_f=1.0 J, lambda_E=0.1 s/J, delta_spec=0.02 s gives A=0.55 s and p>0.43636. At p=0.8, U=0.22 s before subtracting the admission margin. A high-pressure case with g=0.02 s and d=0.30 s gives p>1 under the same costs, so speculation is rejected even for stable text.

Estimate p from held-out partial→final trace outcomes binned by stability time/revision class and speculative mode; use a binomial lower bound. Require enough samples (initial 20/bin); otherwise keep speculation off. Keep content untouched when computing transcript equality; normalizing negation, names or numbers away is invalid. Promote only after a final-turn commitment and exact tokenized prompt compatibility. The full prompt includes chat-template suffixes: LCP of transcript tokens alone does not establish reusable KV. Reset position/state on divergence. Prefix reuse requires backend support; it is not a default feature of all hybrid models.

No audible or durable speculative output before promotion. Carry turn_id/generation_id/seq internally; request agreement before extending the shared contract. Cancellation increments generation ID and stale PCM/text is dropped. First implementation should use exact reuse, not fuzzy semantic validation or a second LLM judge.

## 5. Enforcement, wiring, and measurement

Native Linux target: one parent cgroup v2 encloses the entire workload, including supervisor, models, audio worker and required child services. A dashboard-only observer may be outside, but disclose its cost. Prefer cpuset on declared CPU topology plus memory.max and swap.max=0. Inspect available delegation before choosing systemd versus a container. taskset alone does not enforce RAM or capture escaped subprocesses. cpu.max is bandwidth/quota, not a count of pinned physical cores. Record effective ancestor limits. [Kernel cgroup documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html)

Use resident stage processes if model wrappers permit, blocking pipes/queues for JSON and bounded PCM buffers. Native inference often releases the GIL, so processes are selected for isolation/monitoring, not an asserted universal speedup over threads. Avoid a six-way IPC benchmark. Idle workers block, audio callbacks never wait for LLM/TTS, and queue capacity is specified in seconds/bytes. A full input queue records overload and rejects speculative work; a full output queue backpressures inference at safe points.

Pressure observations: custom-window PSI `some total` deltas divided by elapsed microseconds; memory.current/limit; ASR backlog/service; audio buffer; cpu.stat usage and throttled-period fraction when a quota exists. PSI is stall time, not CPU utilization. Quota throttling is not a useful primary signal for a cpuset-only configuration. Ten-second PSI averages are too slow for a short speech turn. [Kernel PSI documentation](https://docs.kernel.org/accounting/psi.html)

Latency: use CLOCK_MONOTONIC/monotonic_ns in all processes on this same machine. Log acoustic end annotation, VAD endpoint, final ASR, prompt-ready, first token, chunk release, PCM-ready, audio-device submission and playback position. Audio timestamps must be mapped to the shared clock. Ground truth uses annotated prerecorded WAVs streamed in real time and output captured through the same audio path; threshold sustained content audio above the measured noise floor, not the first nonzero sample. Validate several traces externally by recording input/output. Show both first-any-audio and first-content-audio if acknowledgement clips are used. Never subtract endpoint delay from the headline metric.

Resource accounting: mean used cores = delta(cpu.stat usage_usec)/(1e6 * wall_seconds); CPU-seconds/turn counts listening and reply work over equal test schedules. Report allocated CPUs separately. Whole-cgroup peak RAM includes model pages, cache/workspaces, and children; stage PSS is diagnostic, not the enforcement metric. Reset/recreate measurement groups for each run as supported by the kernel.

Energy: sum non-overlapping RAPL package domains, with optional separately labeled DRAM, handling wraps by frequent counter reads and max_energy_range_uj. Do not sum package plus its core subdomain. RAPL is package energy, not process-specific energy or necessarily whole-laptop energy. [Powercap interface](https://docs.kernel.org/power/powercap/powercap.html), [author-hosted RAPL validation](https://web.eece.maine.edu/~vweaver/projects/rapl/rapl_validation.html).

    E_adjusted_per_turn = (E_run − P_idle * T_run)/N
    efficiency = successful_turns / E_run.

Report gross energy and idle-adjusted energy together. Measure idle before/after runs under matched display, frequency/power profile, and background activity. For always-on sessions include a fixed listening interval between turns. Do not hide idle listening by subtracting the assistant's own listening cost. Negative adjusted energy is a baseline/noise problem to report, not clamp into a flattering score. Without RAPL, use a physical meter; CPU-seconds or CodeCarbon estimates are not measured joules. Whole-system energy under competing external load requires matched controls and cannot be attributed exclusively to our workload.

## 6. Baseline, ablation, and stop rules

Baseline selection is empirical. Briefly calibrate the reference stack and the team's strongest feasible alternative. Select on quality plus latency/footprint under the declared cap, rather than picking Whisper-small solely because it is slow. Freeze models/builds/prompts before tests.

| ID | Comparison | Question answered |
|---|---|---|
| B0 | Strong feasible standard stack, defaults, same cap | Does the system clear the rubric baseline? |
| B1 | Same stack, tuned threads/context/endpoint, standard streaming | Does tuning alone explain gains? |
| B2 | Best fixed action from our library, same models/chunks/cache, tuned per cap | Does adaptive control add value beyond an honestly optimized static stack? |
| B3 | Reactive pressure ladder with identical action library | Does prediction/joint feasibility beat a simple adaptive implementation? |
| C0 | Main controller, speculation disabled | Value of phase/deadline scheduling and degradation |
| C1 | C0 + confidence-only speculation | Does confidence gating suffice? |
| C2 | Full controller with contention/energy gate | Value of resource-priced speculation |
| A1 | C2 without transition-cost accounting | Does accounting prevent costly switches? Test only within safe enforced limits |
| A2 | C2 without playback/backlog constraints | Does deadline protection prevent speech stalls? |

Use a fixed static setting across changing caps as one comparator, and a per-cap best-static envelope as a stronger reference. The latter knows the cap in advance; label it clearly. If B2 matches the controller at stable caps, that is expected and useful. The dynamic experiment is the primary controller test.

Initial dataset: 30 calibration turns and 60 held-out turns from different speakers where possible. Include ordinary questions, hesitations, corrections/negations/numbers, long prompts and short backchannels; reference transcripts and acceptable answer criteria are required. Keep synthetic math traces separate. Repeat held-out recordings at least 3 times across randomized system order. Resample uncertainty at the speaker/utterance cluster level, not as if repeated replays were independent new speakers. Run cold starts separately from warmed sessions. Report p50/p90; label p99 exploratory with this small sample.

Initial cap grid: 4/2/1 logical CPUs crossed with 3/2/1.5 GB where the stack is feasible. Start with 2 CPUs/2 GB as a proposed cap, not a promise. Include tightening and recovery traces, both between turns and during active work; do not rely on a predictable fixed sequence. Exercise memory-only, CPU-only and combined reductions separately. Also test imposed pressure inside the declared workload group with the stressor budget separately identified. Never silently omit failed turns from latency statistics: report timeout/failure rate and conditional latency together.

Quality: report end-to-end task success, WER, false cutoff rate, invalid speculative promotion, intelligibility and audio gap duration. Suggested preregistered tolerances: task-success drop <=5 percentage points, cutoff increase <=2 points, with paired uncertainty reported. These are engineering targets, not clinically/statistically justified universal margins. A small test set may be inconclusive. A valid gain requires latency and footprint improvement without unacceptable quality loss; never compress the four objectives into one flattering scalar alone.

Kill rules: remove speculation from the shipped path if paired net gain is negligible, energy worsens beyond the declared trade-off, or ASR/audio deadlines worsen. A 50 ms latency gain is an initial practical floor, subject to measurement precision. Keep the simple ladder if B3 matches C2. Reject any tier that fails quality. No claimed novelty from a negative result, but publish the negative result and simplify the system.

## 7. Build order and handoff

1. Native Linux preflight: topology/cgroup delegation/RAPL/audio-clock availability. Store exact CPU, kernel, OS, model hashes, licenses and runtime commits.
2. Same-clock mocked pipeline with cancellation and bounded blocking queues. Establish measurement trace consistency.
3. B0/B1 working and measured under the cap. No controller claim before this.
4. Profile 12–24 actions, including solo/co-run service, quality and transitions. Freeze B2/B3.
5. Implement finite feasibility filter, timing recurrence, objective, fallback and hysteresis. Replay pressure traces before live cap changes.
6. Add private speculation only if backend KV/prompt validation and measured headroom allow it.
7. Run locked paired tests and ablations; record unsupported caps and negative results. Freeze code, rehearse, record fallback video.

At 25% implementation effort: baseline plus instrumented loop. At 50%: same-model phase controller and three operational tiers. At 75%: pressure trace and core B2/B3 ablations. Remaining effort: optional speculation and results/pitch, without endangering the verified core. Local context targets a first loop before 18:00 IST and integration by midnight; this research specification does not reset those deadlines.

No install/run commands are presented as “worked”: the judging machine is Linux and this workspace is Windows, so such a statement would be false. No package installation or model downloads were performed. The companion Python verification uses only the standard library.

Needed from Ears: timestamp semantics, tested chunk/context changes, per-cap WER/service curves, final-transcript revision rules. From Brain: full prompt serialization, KV rewind/prefix support, thread reconfiguration boundaries, quality/context/quantization profiles, peak load memory. From Voice: minimum natural chunk, synth cancellation, PCM-ready/playback timestamps, co-run RTF and voice license. Agree any generation-ID additions at the team merge; preserve the current JSON contract until then.

## 8. Corrections to the earlier log

These corrections override only the cited assumptions; preserve the original log as history.

- Broad local conversational pipeline characterization and energy measurement already exist in the 2026 cross-platform study. Narrow the novelty claim to the controlled interaction under changing hard caps.
- For within-turn pause CDF F and n independent pauses, false cutoff risk is 1−F(tau)^n. To target per-turn epsilon use F(tau)>=(1−epsilon)^(1/n), not a per-pause quantile claimed as a per-turn guarantee. Independence is often false; calibrate whole-turn cutoff empirically.
- CUSUM average-run-length expressions are distribution/assumption dependent. Do not cite a universal exp(h) guarantee for correlated VAD frames. Endpoint innovation belongs to Ears; lock a tested endpoint policy for Spine ablations.
- CPU quota and cpuset are different constraints; throttling is not synonymous with pressure. nproc alone is insufficient enforcement evidence.
- A stage-time sum applies to a serial path. Streaming/speculation require release/dependency/queue timing; adding marginal p90s does not give end-to-end p90.
- Processes do not universally fix GIL contention in native inference. Busy-polling avoidance is the reliable design requirement.
- Private speculation protects output correctness only with validation; it can still increase latency or energy under a shared CPU cap.
- Small model files and idle-subtracted package counters do not establish total RAM or whole-device energy consumption.

## 9. Mathematical verification completed

Ran `python research/verify_spine_math.py` in this workspace. All 120,160 synthetic consistency checks passed: signed speculation-threshold algebra, explicit outcome expectations, queue conservation, unstable arrival/service example, playback timing against an independent tick simulator, independent-pause risk enumeration, Wilson-bound monotonicity, and a transition-cost counterexample. Maximum speculation identity error was 2.67e-15 (floating point rounding).

Artifacts: [verification script](verify_spine_math.py), [machine-readable results](math_verification.json). No model throughput, Linux cap enforcement, audio latency, energy reduction, quality retention, or controller speedup was measured. The checks validate the specified simplified mathematics, not the proposed empirical contribution.

The algorithm design is now concrete enough to implement. Final numeric thresholds, winning stage models, cap, and claimed gains remain explicitly dependent on calibration on the team's Linux laptop.
