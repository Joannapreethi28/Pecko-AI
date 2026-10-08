# Pecko: an offline voice assistant that thinks while you talk

> **THE PLAN: [`docs/solution.md`](docs/solution.md)** (architecture, critical-path idea, laptop → phone roadmap, milestones, ablation plan). Messages between stages: [`docs/CONTRACT.md`](docs/CONTRACT.md). Math in plain words: [`docs/study_guide.md`](docs/study_guide.md).

HackNEX 2026 · HNX26EPS08 On-Device Conversational Stack · Team Plumbers

> **STATUS: skeleton.** This README is a required submission item. Fill every section as the build progresses; remove this line when done.

## What it is
Fully offline, CPU-only voice loop (wake word/VAD → streaming ASR → small LLM → TTS) running under an enforced 2 CPU / 2 GB limit. It overlaps stages so the first audio of the answer starts far sooner than a default serial stack. See `docs/solution.md`.

## Results (measured on our laptop, same cap, same test set)
_TODO: baseline B0 vs Pecko: p50/p90 latency, CPU-s/turn, peak RAM, J/turn; master ablation table; degradation curve._

## Setup
_TODO: exact commands that worked (Python version, venv, models download to `models/`, llama.cpp build)._

## Run
_TODO: one command under the cgroup limit; baseline command; how to run each stage's mock; how to reproduce the tables._

## Layout
`ears/ brain/ voice/ spine/ common/ docs/ data/ scripts/ tests/`. Contract: `docs/CONTRACT.md`.

## Limits and honesty
_TODO: what is measured vs estimated, known failure cases, licenses (Piper GPL-3, MMS non-commercial, LFM Open License)._
