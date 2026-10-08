# Study Guide (v2, Pecko): Pecko (HNX26EPS08): Novelty + Math

Sir Jabin, read in this order: §1 → §2 → §3. Every number marked *toy* is made up to teach the algebra. **Nothing here is measured yet.**

---

## 1. The one idea

> **Models aren't slow. The waiting is.**

Default voice bot = relay race where each runner waits for the previous one to *fully* finish:

```
SERIAL:   [wait for silence][ASR whole clip][LLM prefill][LLM reply][TTS whole reply] → sound
OVERLAP:  [ASR+prefill run WHILE user talks][short endpoint][1st chunk][TTS chunk 1] → sound
```

Latency `L = P_1 − t_acoustic_end` (first audio sample minus the moment the user actually stopped).

*Toy* (ms): serial ≈ 800 endpoint + 800 ASR + 700 prefill + 300 gen + 400 TTS = **3000**.
Overlapped ≈ 250 + 80 + 60 + 250 + 200 = **840**. The work moved *before* the user finished; it didn't get faster.

Two facts under everything:
- **Prefill** (reading the prompt) = compute-bound → scales with cores × tokens → *can be done early*.
- **Decode** (writing tokens) = memory-bandwidth-bound → tok/s ≈ bandwidth ÷ bytes of weights read per token. *Toy:* 0.4 GB model, 20 GB/s → ≤ 50 tok/s. (Assumption, verify.)

---

## 2. The novelty (honest version)

**Claim: "Listen-while-thinking under a hard cap."**
Overlapping the stages is *not* new. What we add:

1. **Speculation has a price.** Early prefill burns CPU and energy; if the user keeps talking, the work is thrown away. We only speculate when the expected gain beats the expected waste (§3.3).
2. **The cap is hard and shared.** 2 CPUs / 2 GB enforced by cgroups. Speculation steals cores from ASR and TTS. Prior work assumes spare GPU/server capacity.
3. **A ladder, not one config.** As the cap shrinks, T0 Full → T1 Tight → T2 Starved → T3 Survival (cache + composed answers, no LLM). Switch only between turns, only if memory fits (§3.4).

| Prior art | What it does | Why it's not our claim |
|---|---|---|
| PredGen, Voice-Light, Endpoint Anticipation | speculative/early generation | GPU/server, no shared hard cap |
| ElastiLM | elastic model sizing | not an end-to-end voice loop |
| 2026 Moonshine–LM–Piper energy study | measures local energy | measures, doesn't control |

**Do NOT say:** "first local stack with energy numbers." **Say:** "controlled interaction of speculation + deadline protection + transition feasibility under a hard, changing cap, with ablation." This is a bounded search, not proof of uniqueness. If a judge names a paper, agree and point to the cap + ladder + ablation.

**Proof = ablation table** (solution.md §6, A0–A7): turn each mechanism off, show latency / CPU / energy / wasted-work change. No table, no novelty score.

---

## 3. The math

### 3.1 ASR backlog: can the ear keep up?
`q_next = max(0, q + a_t − rΔ)`
- `q` unprocessed audio (s) · `a_t` audio arriving this tick · `r` audio-seconds processed per wall-second · `Δ` tick length.
- Need `q_next ≤ Q_max`, and design for `r ≥ 1+ρ` (ρ≈0.1 headroom).
- *Toy:* Δ=0.1, a=0.1. r=0.8 → q grows 0.02/tick → **1 s lag after 5 s of speech**. r=1.5 → q stays 0.
- Why: if speculation steals CPU and `r` drops below 1, transcripts fall behind forever.

### 3.2 Playback gaps: will the voice stutter?
Sequential TTS, chunk k: `R_k` text ready, `T_k` synth time, `D_k` audio length, `d_audio` output delay.
```
F_k   = max(R_k, F_(k-1)) + T_k            (synth finishes)
P_1   = F_1 + d_audio
P_k   = max(F_k + d_audio, P_(k-1) + D_(k-1))   (starts playing)
gap_k = max(0, F_k + d_audio − P_(k-1) − D_(k-1))
```
- *Toy:* R_1=0.3, T_1=0.25, d=0.05, D_1=1.2 → F_1=0.55, P_1=**0.60**. Chunk 2: R_2=0.6, T_2=0.3 → F_2=0.9, P_2=max(0.95, 1.8)=1.8, **gap 0**. If T_2=1.5 → F_2=2.1, P_2=2.15, **gap 0.35 s** (audible).
- Rule: synthesise chunk k+1 faster than chunk k plays (`T_{k+1} ≲ D_k`). That's why the first chunk is small and later ones can be bigger.

### 3.3 Speculation gate: should we start early?
Start early prefill with success probability `p`:
```
U = p·g − (1−p)·d − λ_E·[p·E_s + (1−p)·E_f]      admit if U > δ_spec
```
- `g` latency saved on success · `d` latency penalty on failure (e.g. cancel/rewind/CPU stolen) · `E_s,E_f` energy if success/fail · `λ_E` exchange rate (s per joule) · `δ_spec` safety margin.
- Rearranged: `A = g + d − λ_E(E_s − E_f)`; if A>0: **`p > (d + λ_E·E_f + δ)/A`**.
- *Toy:* g=0.35, d=0.12, E_s=0.2, E_f=1.0, λ=0.1, δ=0.02 → A=0.35+0.12+0.08=**0.55**; threshold = 0.24/0.55 = **p > 0.436**. Speculate only if the stable-partial predictor is >44% sure.
- *Toy, CPU-starved:* g=0.02, d=0.30 → A=0.40, threshold = 0.42/0.40 = **1.05 > 1 → never speculate.** The gate switches itself off under pressure. This is the novelty in one inequality.
- `p` comes from data: how often did a stable partial survive to the final? (O3: log it.)

### 3.4 Controller + ladder
> **v2:** the shipping objective is now **latency-first** `min(p90, p50, energy)` over feasible actions (§3.7). The weighted form below is kept only to understand the trade-off.
Pick action `a` from feasible set F(s) (profiled configs that fit memory & quality):
`a* = argmin [ L_upper + λ_E·E_upper + λ_G·G_upper ]`   (G = gap risk)
- **Upper bound, not mean:** `T_upper = T_pred + q95(residual)`. *Toy:* pred 0.40 + q95 residual 0.15 = **0.55** (protect the p95, not the average).
- **Quality is a constraint, not a term:** Wilson lower bound on pass rate. *Toy:* 18/20 pass → p̂=0.90 but Wilson 95% lower ≈ **0.70**. Small samples earn little trust.
- **Profile update (EWMA):** `μ_new = 0.8·μ_old + 0.2·obs`. *Toy:* 400 → obs 500 → **420**.
- **Transition feasibility:** switch i→j only if `M_transition(i,j) + M_guard ≤ M_limit`. *Toy:* T0 1.5 GB loaded + T1 0.9 GB new = 2.4 > 2.0 → must **unload first**. Cost: `L_transition = L_j + load_time + state_rebuild_time` (KV cache rebuilt). So never switch mid-reply.

### 3.5 Energy & cores
- `E_adj/turn = (E_run − P_idle·T_run) / N`. *Toy:* 600 J, idle 2 W, 120 s, 20 turns → (600−240)/20 = **18 J/turn**. (Subtract idle or you credit/blame the OS.)
- `efficiency = successful_turns / E_run` (a fast wrong answer is not efficient).
- `mean cores = Δusage_usec / (1e6 · wall_s)`. *Toy:* 150e6 µs over 100 s = **1.5 cores**.
- RAPL gotcha: don't sum package + core (core is inside package; double count).

### 3.6 Pause cut-off risk
Utterance with `n` internal pauses; `F(τ)` = chance one pause is shorter than our wait τ.
`P(cut off) = 1 − F(τ)^n`  → to keep ≤ ε need **`F(τ) ≥ (1−ε)^(1/n)`**.
- *Toy:* F=0.98, n=5 → 1−0.904 = **9.6% cut-offs**. For ε=2%: need F ≥ 0.98^(0.2) = **0.996**.
- Why a fusion endpointer (Smart Turn + silence + transcript cues): a single silence timer can't reach 99.6% without waiting ~1 s.
- Caveat: assumes pauses are independent (often false). Measure empirically on our 30 clips, with accented speakers.

---

### 3.7 v2 math: the critical path (read this one twice)
**Two clocks race after you stop talking.** C = when we are *allowed* to speak (endpoint confirmed + transcript validated). R = when the first answer audio is *ready*.
`first audio = max(C, R) + d`
- *Toy:* C=0.6, R=0.9 → 0.9. Make R=0.5 → 0.6 (**saved 0.3**). Make R=0.2 → still 0.6 (**saved 0**: you hit C's wall). If speculation steals CPU and C becomes 1.0 → 1.0 (**0.1 s worse**).
- Gain of a speed-up h on R: `min(h, max(0, R0 − C))`. **Lesson:** always attack the later clock.
- **Hold-and-release:** prepare the first clause before C, keep it silent, release at C. That pushes R ≤ C on good turns.

**Gap-free start** with chunks ready at r_k, each D_k long:
`T0* = max(C+d, max_k [ r_k + d − Σ_{j<k} D_j ])`. In words: start early enough to begin, late enough that every chunk arrives before it's needed.
- *Synthetic 8-word reply:* one word per chunk → first ready 225 ms but a gap-free start only at 785 ms (play at once = 560 ms of stutter). Whole reply → 960 ms. **3-3-2 words → 435 ms, no gaps.** Smallest chunk is not fastest.

**Speculation (v2):** `E[gain] = p·g − (1−p)·d_fail`, with g measured on the critical path, so it is 0 when R is already ≤ C. Admit only if > 0 and within the energy/memory budget.

**Stats reality:** zero cut-offs in 60 turns → true rate could still be **4.87%** (95% bound, `1−0.05^(1/60)`). Claiming < 2% needs **149** independent turns.

## 4. Honesty box (say this before a judge asks)

- `verify_spine_math.py` passed 120,160 synthetic checks → the **algebra** is right. It says nothing about real performance.
- All latency/RAM/energy figures are vendor/paper/estimates until we measure. Fill every `[MEASURE]` in pitch_deck.md with our own numbers.
- Untested: Indian-accent WER, Hindi/Tamil support, Brain bake-off, LFM2 rewind (hybrid models may not rewind cleanly in llama.cpp).
- Cached/filler audio is reported separately from "first audio of the real answer".

## 5. Self-test (if you can answer these, you own it)

1. Why does a drop in `r` below 1 break the whole loop, not just ASR? *(§3.1)*
2. Under heavy CPU pressure, why does the gate refuse to speculate? Which two terms flip it? *(g shrinks, d grows → A small → threshold > 1)*
3. Why unload before switching tiers? *(memory sum > cap; cgroup would OOM-kill)*
4. What's our claim vs PredGen? *(hard shared cap + energy pricing + ladder, measured by ablation)*
5. Why Wilson, not the raw pass rate? *(20 samples ≠ certainty)*
