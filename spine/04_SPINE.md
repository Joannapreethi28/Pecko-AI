> **Original role brief (v1).** The build spec is `SPEC.md` in this folder; the shared contract is `../docs/CONTRACT.md` (v2). Research ideas below are folded into the master ablation in `../docs/solution.md` §7.

# ROLE 4: SPINE (the backbone)

## In plain words
You are the manager and the referee. You connect the three stages, **enforce the small resource limit**, **measure everything**, build the **baseline we must beat**, and later add the logic that **slows things down gracefully** when the device is starved. This is the heaviest role: if Spine fails, the team has nothing provable to show. Give it to the strongest Linux and systems person.

## You own
- The pipeline wiring (queues, threads or processes, startup, shutdown)
- Enforcing CPU and RAM limits (and showing them live to the judges)
- The **baseline stack** (the "default" setup we compare against)
- The measurement harness: latency, CPU, RAM, energy
- The graceful-degradation controller (tiers)
- The test set, the ablation tables, and the write-up

## Test alone with mocks
Wire three fake stages (a WAV reader, a typed-text brain, a hardcoded voice) and prove timestamps flow end to end before the real stages arrive.

## Solo research questions
1. How do we enforce "N cores, X GB" on a laptop? (cgroups, systemd-run, Docker limits, taskset, or the OS equivalent). Which works on **our** laptop? How do we show it live?
2. How do we measure **energy** on our laptop? (RAPL counters, perf, CodeCarbon, powermetrics, or a wall meter) and how do we subtract idle?
3. What is the strongest fair **baseline**: a standard quantized ASR + small LLM + TTS with default settings? Build a runnable script for it.
4. How do we measure **end-of-speech → first audio** accurately, using one shared clock and a sanity check by recording with a phone?
5. How do we detect resource pressure? (CPU and memory pressure info, cgroup stats) and how do we design **tiers** that switch without crashing?
6. Python wiring: threads versus processes, avoiding CPU fights between stages on 2 cores.
7. What is our test set? (30 recorded requests, mixed types, including mid-sentence pauses and accents)

## Your research idea to test (the "what's new" score)
**Pressure-aware tier controller vs fixed configurations.** Tighten the limit step by step (for example 4 → 2 → 1 core, and 3 → 1.5 → 1 GB). Compare a static setup against an adaptive one on latency, quality and energy per turn. The claim: **quality kept per watt as the limit tightens.**

## Stretch goals for Spine
- **Keep quality as the limit tightens (priority):** this is your tier controller. Plot latency and quality against the limit for the demo.
- **Smaller device:** try the pipeline on a Raspberry Pi or phone. Report what works, honestly.
- **Multilingual:** collect results from the other three roles and present one clear table.
- **Cached TTS:** include cache on/off in your ablation matrix.

## Definition of done (for the build phase)
- **Baseline measured first** (this unblocks everything else)
- One command starts the whole stack under the declared limit
- Live limit display ready for judges (and live tightening ready for the degradation demo)
- Measurement of: median and p90 latency, mean CPU cores, peak RAM, energy per turn (idle subtracted)
- At least 3 tiers working with logged switches
- Ablation tables ready, a short write-up, and a backup demo video
- "Airplane mode" offline proof ready to show
