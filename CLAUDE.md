# Pecko: HNX26EPS08 On-Device Conversational Stack (HackNEX 2026, team Plumbers)

Pecko is a fully offline, CPU-only voice assistant (mic → ASR → LLM → TTS → speaker). **Target 1:** Ubuntu laptop under a declared, enforced limit (2 logical CPUs, 2 GB RAM, swap 0, network off). **Target 2:** the same stack on an Android phone. It must beat a default stack on **end of speech → first audio of the real answer** and on CPU/RAM/energy.

**THE PLAN (read first): `docs/solution.md` (v2)** — architecture (laptop → phone), the critical-path idea, milestones and ablation plan. Role details: `<role>/SPEC.md`. Math explained simply: `docs/study_guide.md`.

## How to work with Sir Jabin (always)
- Address him as **Sir Jabin**. He is an intermediate coder who learns fast and wants to **understand everything being built**.
- **Explain as you build.** Before each step, say in 1–3 lines *what* you will do and *why* (which latency/footprint/score it serves). After it, say what changed, how to run or verify it, and what to look for in the output. Explain any new concept (KV cache, cgroup, VAD, RTF...) once, simply, with an example.
- **Build in parallel.** Split independent work into parallel subagents/tasks (for example the four stage mocks, or a benchmark plus a script). Rule: parallel workers never edit the same file. Stage boundaries are the contract, and the contract changes only with the whole team. Report each worker's result in one short line.
- Be brutally honest. Push back on weak ideas. Never present an estimate as a measurement. Short answers unless depth is needed.
- Plan before big code. For anything over ~100 lines, show a 5-line plan first.

## The idea (do not lose it)
first audio = `max(C, R) + d`. **C** = commit gate (endpoint confirmed + final transcript validated). **R** = first answer clause PCM ready. Always work on whichever is later. Speeding up R past C gives 0 ms. Prepare privately before C (hold-and-release); nothing is audible before commit. Claim: *deadline-constrained critical-path control of speculation and chunking under a shared hard CPU cap.* Not claimed as new: speculation, Bayesian endpointing, local energy measurement.

## Pass/fail gate
No cloud, no GPU, CPU only, offline · loop runs under a limit shown enforced live · wake word/VAD · beats baseline latency at lower resource use · measured CPU, RAM, energy + write-up.

## Scores
Latency 25 · footprint 25 · what's new (ablation) 20 · quantization+offload 15 · degradation 15 · bonus: cached TTS, **smaller device (phone)**, multilingual. Event: Innovation, Technical Complexity, Feasibility & Scalability, **Design & UX (live dashboard)**, Pitch.

## Rules that can disqualify us
All core code written in the 24 h window; no pre-built project/template · **git history from the start**, commit small and often, never rewrite history · **README with setup + usage** kept current · submit repo + README + deck by 8:00 AM 9 Oct (aim 7:30) · team must understand what it built (so explain it).

## Honesty rules
No number is ours until we measured it; fill `[MEASURE]` only with measurements. Report p50 **and** p90 **and** gap duration. Use paired complete turns and never drop failures. Fillers are off in the headline. Same LLM in baseline and Pecko. Zero cut-offs in 60 turns still means ≤ 4.87% (95%), not 0%.

## Contract (v2 + v2.1 proposal). Read before touching any stage boundary
@docs/CONTRACT.md

## Platform
- **Ubuntu (native, dual boot) is the dev and judged platform.** Linux-only code (cgroups, PSI, RAPL, `taskset`) lives in `spine/`.
- Phone code lives in `mobile/` and reuses the same orchestrator and contract. **The phone never blocks the laptop.**
- Python 3.10+, `.venv`, `pathlib`. No network at runtime (`HF_HUB_OFFLINE=1`), no lazy downloads, models in `models/` (gitignored).

## Code conventions
- Every stage is a class with `start()` (load + warm up + ready), `feed(msg)`, `stop()`, `set_tier(n)`, and runs standalone with a mock (Ears from WAV at real-time speed, Brain from typed text, Voice from a sentence file).
- One JSON object per line; `time.monotonic()` seconds everywhere. Log: `{"stage":"brain","event":"first_token","turn":7,"t":13.41,"extra":{}}`.
- First-audio path is **event-driven** (no polling loops). ONNX sessions `intra_op=1, inter_op=1, allow_spinning=0`. Never more busy threads than CPUs.
- Merge to `main` only after the stage mock test passes. Spine owns `main`.

## Layout
```
docs/    solution.md · CONTRACT.md · study_guide.md · pitch_deck.md · TEAM_BRIEF.md · reference/ · archive/
ears/ brain/ voice/ spine/ mobile/   each: CLAUDE.md · SPEC.md · research/
common/  clock.py, log.py (write first)     models/ (gitignored)     data/clips, data/results
scripts/ run_pecko.sh, run_baseline.sh, bench     tests/
```

## Order
L0 repo + clock/log + cgroup wrapper + models → L1 half-baked loop on Ubuntu → L2 baseline + decisive C-vs-R experiment → (parallel) 45-min phone spike → PC2 → L4 stable, then no new laptop features → P1 phone → L5 held-out tests, ablations, README, videos → submit.
