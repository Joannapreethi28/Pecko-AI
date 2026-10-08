# Pecko: an offline voice assistant that thinks while you talk

> **THE PLAN: [`docs/solution.md`](docs/solution.md)** (architecture, critical-path idea, laptop → phone roadmap, milestones, ablation plan). Messages between stages: [`docs/CONTRACT.md`](docs/CONTRACT.md). Math in plain words: [`docs/study_guide.md`](docs/study_guide.md).

HackNEX 2026 · HNX26EPS08 On-Device Conversational Stack · Team Plumbers

> **STATUS: Spine's portable runtime is built; Ears' pipeline is built.** Five Spine deliverables are verified with mocks/fixtures; Ears' VAD/KWS/ASR/endpointer tier ladder (T0-T3) runs end-to-end against real audio. Real engines and Ubuntu VM validation are deferred for both. See [Spine delivery status](spine/BUILD_STATUS.md) and [`ears/RESULTS.md`](ears/RESULTS.md).

## What it is
Fully offline, CPU-only voice loop (wake word/VAD → streaming ASR → small LLM → TTS) running under an enforced 2 CPU / 2 GB limit. It overlaps stages so the first audio of the answer starts far sooner than a default serial stack. See `docs/solution.md`.

## Results (measured on our laptop, same cap, same test set)
_TODO: baseline B0 vs Pecko: p50/p90 latency, CPU-s/turn, peak RAM, J/turn; master ablation table; degradation curve._

## Evaluator frontend

Pecko now includes a local presentation workspace: a working typed intent demo,
seven recorded voice samples, four model comparisons, a synthetic pipeline
replay, and a searchable evidence library. Design follows
[Impeccable](https://github.com/pbakaus/impeccable). Fonts and assets are bundled;
the frontend needs no Node build or internet connection at runtime.

From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r frontend/requirements.txt
.\.venv\Scripts\python.exe -m frontend
```

On Ubuntu:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r frontend/requirements.txt
.venv/bin/python -m frontend
```

Open **http://127.0.0.1:8765**. On this Windows checkout the environment and
dependencies are already prepared, so only the final command is needed.
Choose another port with `--port 8766` if required. Stop with Ctrl+C.

Suggested presentation flow:

1. **Demo studio:** click “Introduce yourself”, ask the time, then play a recorded voice sample.
2. **Benchmarks:** switch first-token latency, memory and decode speed; inspect the linked evidence.
3. **How it works:** explain the commit gate and replay the labelled synthetic correction scenario.
4. **Evidence library:** show measured, synthetic and unfinished work; export the source-backed JSON.

The text demo calls the real `brain.router`; it does not transcribe microphone
input or synthesize the chat reply. General questions need an existing
`llama-server` on `127.0.0.1:8080`. The default prompt family is Qwen3; use
`--model-family lfm2` only with a matching model. Without a model, cached intents
and composed time/date replies still work. No weights are downloaded by the UI.
Time/date replies use Asia/Kolkata. Each request is a single turn.

Brain results are Ubuntu VM component benchmarks; voice results are Windows
component experiments. Synthetic traces remain labelled. The displayed 2 CPU /
2 GB budget is a target, not live resource enforcement. No end-to-end voice
latency, microphone readiness or energy result is implied.

Refresh evidence after new results are committed:

```sh
python frontend/build_evidence.py
python -m unittest tests.test_frontend_server -v
```

Use the virtual environment's Python for the tests. The server only binds to
localhost and serves explicitly allowed source/evidence files.

## Core runtime setup

Portable Spine requires Python 3.10+ and the standard library. Checks ran on
Windows with Python 3.14.8. No model files are needed for placeholder development.
Real model downloads/builds remain the stage owners' setup work.
_TODO: exact commands that worked (Python version, venv, models download to `models/`, llama.cpp build)._

### Ears setup
Ears (wake word/VAD/streaming ASR/endpointer) is implemented and runs standalone (Brain, Voice ship independently in this parallel-build hackathon and are not wired up yet). What actually worked on this machine, Python 3.12.5, Windows:

```
pip install -r requirements.txt
```

First run of anything that touches `MoonshineASR` (T0/T1 ASR backend) downloads ONNX model weights from Hugging Face on first use (one-time, cached after) -- expect a delay the first time, none after.

Test clips are already provided, converted, and ready in `data/clips/` (33 real WAVs + `MANIFEST.csv`); see `data/clips/SOURCE.md` for provenance. No model build step (no llama.cpp yet -- that is Brain's role).

## Run

Team integration: [Spine handoff](docs/handoff_spine.md).
Development history and traps: [Spine gotchas](docs/gotcha_spine.md).

Recorded-input and paired evaluation tooling is available on Windows.
See [WAV ingress and repeated comparisons](spine/RECORDED_INPUT.md).

Start the configurable placeholder runtime and generate its dashboard:

```sh
python -m spine.runtime --profile spine/examples/runtime.placeholder.json --plan spine/examples/plan.scripted.json --output data/results/mock-contract-01
python -m spine.demo --output data/results/mock-control-01
```

Use new output directories. These commands work without Ubuntu and save explicit
synthetic results. Open dashboard.html in the output directory to review the run.

Spine foundation checks (Python 3.10+, from the repository root):

```sh
python -m spine.mock
python -m unittest discover -s tests -v
python -m spine.linux --cpus 0,1 --dry-run
```

This is a synthetic text-only wiring check, not a working voice loop or benchmark.
See [Spine integration and remaining work](spine/README.md). Real engines,
verified Ubuntu caps, baseline runs and measurement tables remain to be built.

Inspect the synthetic measurement report:

```sh
python -m spine.report spine/examples/events.synthetic.jsonl --manifest spine/examples/experiment.synthetic.json
```

Spine also provides read-only cgroup accounting and a reactive tier ladder.
The full eight-phase build remains in progress; hardware results are pending.

Run the multi-turn synthetic experiment (choose a fresh output directory):

```sh
python -m spine.experiment --plan spine/examples/plan.synthetic.json --output data/results/mock-run-01
```

It saves the plan, events, turn manifest, completion summary and report,
preserving failures and unstarted cases. Its mock does not produce audio.

### Ears run
Ears runs standalone against a WAV file, pure contract JSONL on stdout, diagnostics on stderr:

```
python -m ears.mock data/clips/hindi10.wav --push-to-talk --fast
```

`--push-to-talk` force-arms immediately (the real clips don't say "hey pecko"); `--fast` uses a VirtualClock instead of real-time pacing. Drop `--fast` to replay at real-time speed, or add `--mic` to listen live. `--tier N` selects the tier (T0 default, T1-T3 the degraded tiers; see `docs/CONTRACT.md`'s tier ladder and `ears/RESULTS.md` for what each tier actually runs and its measured tradeoffs).

Other scripts that work standalone today:
```
python scripts/measure.py              # WER + endpoint-delay + false-cutoff proxy + peak RSS + idle CPU over the clip set
python scripts/ablation.py             # fixed-800ms vs fixed-400ms vs fusion endpointer, real measured comparison
python scripts/test_tier_switch.py     # tier-switch timing + peak RSS, sanity-checks tiers transcribe
```

Brain/Voice/Spine mocks and the full end-to-end pipeline command do not exist yet -- not claimed here until built.

## Layout
`ears/ brain/ voice/ spine/ common/ docs/ data/ scripts/ tests/`. Contract: `docs/CONTRACT.md`. `ears/` and shared `common/`, `data/`, `scripts/` have real, tested code; see each role's own `RESULTS.md`/`BUILD_STATUS.md` for what's real vs. spec/skeleton in `brain/ voice/ spine/`.

## Limits and honesty
_TODO: what is measured vs estimated, known failure cases, licenses (Piper GPL-3, MMS non-commercial, LFM Open License)._
