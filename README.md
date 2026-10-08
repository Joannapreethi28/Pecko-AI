# Pecko: an offline voice assistant that thinks while you talk

> **THE PLAN: [`docs/solution.md`](docs/solution.md)** (architecture, critical-path idea, laptop → phone roadmap, milestones, ablation plan). Messages between stages: [`docs/CONTRACT.md`](docs/CONTRACT.md). Math in plain words: [`docs/study_guide.md`](docs/study_guide.md).

HackNEX 2026 · HNX26EPS08 On-Device Conversational Stack · Team Plumbers

> **STATUS: Spine's portable runtime is built.** Five software deliverables are verified with mocks/fixtures; real engines and Ubuntu VM validation are deferred. See [Spine delivery status](spine/BUILD_STATUS.md).

## What it is
Fully offline, CPU-only voice loop (wake word/VAD → streaming ASR → small LLM → TTS) running under an enforced 2 CPU / 2 GB limit. It overlaps stages so the first audio of the answer starts far sooner than a default serial stack. See `docs/solution.md`.

## Results (measured on our laptop, same cap, same test set)
_TODO: baseline B0 vs Pecko: p50/p90 latency, CPU-s/turn, peak RAM, J/turn; master ablation table; degradation curve._

## Setup

Portable Spine requires Python 3.10+ and the standard library. Checks ran on
Windows with Python 3.14.8. No model files are needed for placeholder development.
Real model downloads/builds remain the stage owners' setup work.
_TODO: exact commands that worked (Python version, venv, models download to `models/`, llama.cpp build)._

## Run

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

## Layout
`ears/ brain/ voice/ spine/ common/ docs/ data/ scripts/ tests/`. Contract: `docs/CONTRACT.md`.

## Limits and honesty
_TODO: what is measured vs estimated, known failure cases, licenses (Piper GPL-3, MMS non-commercial, LFM Open License)._
