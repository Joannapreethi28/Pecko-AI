# SPINE: build spec (v1 spec + v2 changes at the end)
> v2: this file is the source of truth for this role. Shared decisions, architecture and plan: ../docs/solution.md (v2). Contract: ../docs/CONTRACT.md.

**Enforcement (live, shown to judges):**
```bash
sudo systemd-run --scope -p AllowedCPUs=2,3 -p CPUQuota=200% \
  -p MemoryMax=2G -p MemorySwapMax=0 --unit=pecko ./scripts/run_pecko.sh
systemctl status pecko.scope ; systemd-cgtop            # live CPU/RAM for judges
cat /sys/fs/cgroup/system.slice/pecko.scope/{cpu.max,memory.max,memory.peak,memory.events}
# degradation demo (announced): lower the cap between turns
sudo systemctl set-property --runtime pecko.scope AllowedCPUs=2 CPUQuota=100% MemoryMax=1250M
```
Show `memory.events` oom_kill = 0 after the demo. Prove offline with `nmcli networking off` (or airplane mode) live.

**Measurement harness:**
- Ground truth: annotated WAVs streamed at real time through the same code path; output captured through the audio path. Headline = labelled acoustic end → first sustained content audio. Validate a few traces with a phone recording (mic + speaker in Audacity).
- CPU: `Δ cpu.stat usage_usec / (1e6 × wall_s)` = mean cores; CPU-seconds per turn.
- RAM: whole-cgroup `memory.peak` (includes mmapped model pages; state this on the slide).
- Energy: RAPL package domains (`/sys/class/powercap/intel-rapl*/energy_uj`, handle wraps), never package + core summed. Report gross J/turn **and** idle-adjusted J/turn `(E_run − P_idle × T_run)/N`, and successful turns per joule. No RAPL → physical meter; CPU-seconds are not joules.
- Test sets: **30 calibration turns + 60 held-out turns** (different speakers, hesitations, numbers, negations, corrections, short backchannels), each with a reference transcript and an "acceptable answer" note. Repeat held-out runs 3× in random order. Report p50/p90, and failures (never drop failed turns from the stats).

**Baselines (frozen before tests):**
| ID | What | Question it answers |
|---|---|---|
| B0 | Default stack: Silero VAD default silence → whisper.cpp/faster-whisper base.en on the whole utterance → llama.cpp **same LLM as our T0**, defaults, no prompt cache, full reply → Piper full reply. Same cap. | Do we beat a standard stack? |
| B0' | Same, with the "typical" model (Llama-3.2-1B or Qwen3-1.7B Q4_K_M). | Do we beat what most teams would run? |
| B1 | B0 with tuned threads/context but no streaming tricks | Does tuning alone explain the gain? |
| B2 | Best fixed configuration from our own action library, tuned per cap | Does adaptive control beat an honest static stack? |
| B3 | Reactive pressure ladder (hysteresis) | Does the smart controller beat a simple ladder? |

**Controller, built in three layers (D7):**
1. **Ladder (must ship by M3):** signals = PSI `some` deltas over a short custom window, `memory.current/memory.max`, ASR backlog, audio buffer level, LLM tok/s. Down after 3 bad readings, up after 10 good + 2 s dwell. Tier changes between turns only. Logged.
2. **Profile-driven controller (M4 if time):** 12–24 profiled actions; feasibility filter (ASR backlog `q_next = max(0, q + a − rΔ) ≤ Q_max` with service rate r ≥ 1.1; playback continuity; memory transition peak + guard ≤ limit; quality floor); pick `argmin [L_upper + λ_E·E_upper + λ_G·G_upper]` over feasible actions. Math already verified (120,160 synthetic checks passed, `verify_spine_math.py`).
3. **Speculation gate (only if it pays):** admit early generation only if `U = p·g − (1−p)·d − λ_E[p·E_s + (1−p)·E_f] > δ`. Kill it from the shipped path if the paired gain is < 50 ms or energy/ASR deadlines get worse. A negative result is still reported.

**Dashboard (Design & UX criterion), outside the cgroup, cost disclosed:** one screen showing the live transcript, Pecko's state (listening / thinking / speaking), the last turn's latency waterfall by stage, CPU and RAM against the declared limit, current tier, cache hit/miss, and energy per turn. A terminal UI (`rich`) is enough and costs almost nothing; a local web page is a stretch. Owner: whoever is ahead at M3 (default: Ears).

**Done when:** B0 measured first · one command starts Pecko under the cap · live limit display · p50/p90 latency, mean cores, peak RAM, J/turn · 3+ tiers with logged switches · ablation tables · README · backup demo video.

---
## v2 changes (from research/latency_v2/spine_latency_revision.md) — these override the v1 text above
- **Objective:** latency-first lexicographic `min (p90, p50, energy)` over feasible profiled actions. Feasible = quality floor (Wilson lower bound), cut-off and underrun budgets, memory transition peak + guard ≤ limit, CPU-s and energy ≤ baseline-derived budgets. Replaces `argmin [L + λE + λG]`. Use `choose_latency_action` in `research/latency_v2/spine_latency_core.py`.
- **Critical path:** track per turn C (commit: final + prompt validation) and R (first clause PCM ready). First audio = `max(C,R)+d`. Speculation admitted on `p·g − (1−p)·d_fail > 0` where g, d_fail come from this model incl. ASR contention. At most one attempt per turn.
- **Commit gate + hold buffer** (contract v2.1): release held PCM on `commit`, drop on `cancel`/gen mismatch.
- **Event-driven dispatch** on first-audio events. The 200 ms loop is for pressure telemetry only.
- **Deadline-aware dispatch** while playing: run a decode batch only if `upper(decode) + upper(next TTS) + guard ≤ buffer`.
- **Ladder:** reset regime history on cap change. Do not treat a 2-of-3 window as a p90 estimator (false alarms are about 51% over 25 blocks at a true 10% miss rate).
- **Chunk planner (only after measurement):** causal two-chunk, natural boundaries ≤ 12 words. The offline oracle `optimize_chunks` gives the oracle gap. Start bound `T0* = max(C+d, max_k[r_k+d−Σ_{j<k}D_j])`.
- **First experiment after L1:** warm instrumented baseline, a few ordinary/hesitation/correction turns at 1 and 2 CPUs, logging endpoint, final ASR, prefill, first token, text release, PCM-ready and playback → which of C or R dominates.
- `research/latency_v2/incoming_spine/spine_core.py` is reference only (audited flaws). Unit name: `--unit=pecko`.
- Stats: zero cut-offs in 60 turns → ≤ 4.87% (95%). Needs 149 independent turns to show < 2%.
