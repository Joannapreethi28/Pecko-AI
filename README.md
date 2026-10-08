# Pecko: an offline voice assistant that thinks while you talk

> **THE PLAN: [`docs/solution.md`](docs/solution.md)** (architecture, critical-path idea, laptop → phone roadmap, milestones, ablation plan). Messages between stages: [`docs/CONTRACT.md`](docs/CONTRACT.md). Math in plain words: [`docs/study_guide.md`](docs/study_guide.md).

HackNEX 2026 · HNX26EPS08 On-Device Conversational Stack · Team Plumbers

> **STATUS: skeleton.** This README is a required submission item. Fill every section as the build progresses; remove this line when done.

## What it is
Fully offline, CPU-only voice loop (wake word/VAD → streaming ASR → small LLM → TTS) running under an enforced 2 CPU / 2 GB limit. It overlaps stages so the first audio of the answer starts far sooner than a default serial stack. See `docs/solution.md`.

## Results (measured on our laptop, same cap, same test set)
_TODO: baseline B0 vs Pecko: p50/p90 latency, CPU-s/turn, peak RAM, J/turn; master ablation table; degradation curve._

## Setup
Only **Ears** is implemented so far (this is a parallel-build hackathon; Brain, Voice, and Spine ship independently and are not wired up yet). What actually worked on this machine, Python 3.12.5, Windows:

```
pip install -r requirements.txt
```

First run of anything that touches `MoonshineASR` (T0/T1 ASR backend) downloads ONNX model weights from Hugging Face on first use (one-time, cached after) -- expect a delay the first time, none after.

Test clips are already provided, converted, and ready in `data/clips/` (33 real WAVs + `MANIFEST.csv`); see `data/clips/SOURCE.md` for provenance. No model build step (no llama.cpp yet -- that is Brain's role, not yet built).

## Run
Ears runs standalone against a WAV file, pure contract JSONL on stdout, diagnostics on stderr:

```
python -m ears.mock data/clips/hindi10.wav --push-to-talk --fast
```

`--push-to-talk` force-arms immediately (the real clips don't say "hey pecko"); `--fast` uses a VirtualClock instead of real-time pacing. Drop `--fast` to replay at real-time speed, or add `--mic` to listen live. `--tier N` selects the tier (T0 default; see `docs/CONTRACT.md`'s tier ladder).

Other scripts that work standalone today:
```
python scripts/measure.py              # Phase 4: WER + endpoint-delay + peak RSS + idle CPU over all 33 clips
python scripts/test_tier_switch.py     # tier-switch (T0->T1) timing + peak RSS, sanity-checks both tiers transcribe
```

Brain/Voice/Spine mocks and the full end-to-end pipeline command do not exist yet -- not claimed here until built.

## Layout
`ears/ brain/ voice/ spine/ common/ docs/ data/ scripts/ tests/`. Contract: `docs/CONTRACT.md`. Only `ears/` and shared `common/`, `data/`, `scripts/` have real code right now; `brain/ voice/ spine/` currently hold spec/skeleton files only.

## Limits and honesty
_TODO: what is measured vs estimated, known failure cases, licenses (Piper GPL-3, MMS non-commercial, LFM Open License)._
