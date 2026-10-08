# Pecko: an offline voice assistant that thinks while you talk

> **THE PLAN: [`docs/solution.md`](docs/solution.md)** (architecture, critical-path idea, laptop → phone roadmap, milestones, ablation plan). Messages between stages: [`docs/CONTRACT.md`](docs/CONTRACT.md). Math in plain words: [`docs/study_guide.md`](docs/study_guide.md).

HackNEX 2026 · HNX26EPS08 On-Device Conversational Stack · Team Plumbers

Fully offline, CPU-only voice loop (wake word/VAD → streaming ASR → small LLM → TTS) that runs under an enforced 2 CPU / 2 GB / no-swap limit. It overlaps stages so the first audio of the answer starts sooner than in a serial stack.

## Quickstart (Ubuntu, the judged platform)

Needs Python 3.10+, network **only during setup**.

```sh
sudo apt install libportaudio2          # needed by sounddevice (mic/speaker)
python3 -m venv .venv
bash scripts/setup_models.sh            # Python deps + all speech models (see below)
bash scripts/setup_vm_brain.sh          # llama.cpp b11501 + Qwen3-0.6B GGUF
.venv/bin/python -m pytest -q           # sanity check
```

Run the whole loop under the cap:

```sh
scripts/run_pecko.sh --mic                                               # say "hey Pecko, ..."
scripts/run_pecko.sh --wav data/clips/synthetic/q1.wav --no-audio       # no mic/speaker needed
```

Turn the network off after setup if you want to show it works offline: `nmcli networking off` (turn back on with `nmcli networking on`).

### What the setup scripts do
- `scripts/setup_models.sh` (re-runnable): creates `.venv` if missing; installs the CPU-only `torch` wheel plus the root, `frontend/` and `voice/` requirements; downloads Piper lessac voices (`voice/get_models.py`), the sherpa-onnx Zipformer 20M streaming ASR, the sherpa KWS model with the wake phrase "hey pecko", Smart Turn v3.2 (int8 CPU build), Vosk small en-in, and the Moonshine small/tiny streaming models (cached in `~/.cache/moonshine_voice`); checks that Silero VAD loads. Models go to `models/` (gitignored). After this, nothing downloads at runtime (`HF_HUB_OFFLINE=1`).
- `scripts/setup_vm_brain.sh` (re-runnable, each step skipped if done): installs apt basics (`python3-venv python3-pip git curl unzip gh`, uses sudo), warns if the CPU lacks AVX2, checks for RAPL energy counters, installs `brain/requirements.txt`, downloads the llama.cpp `b11501` Ubuntu build into `models/llama.cpp/`, downloads `Qwen3-0.6B-Q4_K_M.gguf` and `Q8_0.gguf` into `models/`, prints their sha256, and runs the Brain tests.

### The cap and how to prove it live
`scripts/run_pecko.sh` starts `spine.app` inside `systemd-run --user --scope` with `CPUQuota=200% MemoryMax=2G MemorySwapMax=0`, pinned with `taskset -c 0,1`. No sudo needed. `PECKO_SUDO=1` uses the system scope with `AllowedCPUs` instead (needs sudo). `PECKO_CPUS` and `PECKO_MEM` override the defaults (`0,1`, `2G`). The script prints the unit name (`pecko-HHMMSS`). In a second terminal:

```sh
systemd-cgtop
cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/app.slice/pecko-*.scope/{cpu.max,memory.max,memory.peak}
```

### Run options (`python -m spine.app --help`)
Pass them through `scripts/run_pecko.sh`. Input is `--mic` or `--wav FILE...` (16 kHz mono, played in real time).

| Option | Meaning |
|---|---|
| `--tier N` | start tier T0-T3 (see `docs/CONTRACT.md`) |
| `--no-wake` | WAV runs: skip the wake word (push-to-talk) |
| `--no-audio` | no speaker (Voice still synthesizes) |
| `--no-hold` | disable hold-and-release (ablation) |
| `--half-duplex` | ignore barge-in (use if echo makes Pecko stop itself) |
| `--tail SEC` | seconds of silence after each WAV (default 15) |
| `--port N` | llama-server port (default 8080) |
| `--out DIR` | run folder (default `data/results/run-<time>`) |

### What a run writes
`data/results/run-<time>/` contains `events.jsonl` (contract log lines from all stages), `bus.jsonl` (every routed message) and `llama-server.log`. Watch a run live:

```sh
.venv/bin/python -m spine.dashboard data/results/run-<time>/events.jsonl --watch
```

## How it works (6 lines)
1. Mic → **Ears**: Silero VAD, sherpa KWS wake word, Moonshine streaming ASR, Smart Turn + text-cue endpointer.
2. **Brain**: router for common intents, Qwen3-0.6B Q4_K_M on llama.cpp (CPU), KV-cache + early prefill, hold-and-release.
3. **Voice**: Piper via sherpa-onnx, audio cache, ring-buffer player, barge-in.
4. **Spine** routes the contract messages ([`docs/CONTRACT.md`](docs/CONTRACT.md)).
5. Spine sends `commit` (C) when the held answer matches the final transcript; nothing is audible before it.
6. First audio = `max(C, R) + d`: work on whichever of commit (C) or answer-ready (R) is later.

## Results
**Conditions for every number in this section (unless a row says otherwise):** VirtualBox VM (Ubuntu, kernel 6.17) on an i7-14650HX host, run inside a **2 CPU / 2 GB cgroup, swap 0** (`cpu.max 200000 100000`, `memory.max 2147483648`, `oom_kill 0` in both runs), **synthetic Piper-voice questions** (`data/clips/synthetic24`, TTS speech, not human), **no speaker** (first audio = first non-silent PCM written, 0 ms device latency on both stacks). Times are ms after end of speech (`t_eos`). One run each, failures kept in n (there were none).

### Pecko vs B0 (default stack), 24 paired turns
B0 = a typical serial stack with the **same LLM and flags** (Qwen3-0.6B Q4_K_M on llama-server), same ASR files (Zipformer 20M int8), same Piper voice, same prompt/history/n_predict: Silero VAD with an 800 ms silence timer → whole-utterance ASR → full prompt, no KV reuse → full reply → whole-reply TTS (`baseline/run.py`). Pecko ran with `--ears-tier 2`.

| Metric (24 paired turns) | B0 | Pecko | Source |
|---|---|---|---|
| First audio p50 | 2059 ms | **835 ms** | compare file below |
| First audio p90 | 2496 ms | **1280 ms** | |
| First audio max | 2815 ms | 1376 ms | |
| Paired gap B0 − Pecko | | p50 **1199 ms**, p90 1472 ms, min 837 ms | |
| Pecko faster | | **24 / 24 pairs** | |
| CPU-seconds per turn | 1.96 | **1.20** (1.63× less) | |
| Peak RAM (cgroup, incl. model load) <!-- RAM row: update from data/results/run-syn24-pecko-ram if re-measured --> | 917 MiB | **846 MiB** (−71 MiB; repeat run 848) | |
| Energy per turn | not yet measured | not yet measured | needs native Ubuntu RAPL; this VM has none |

Source: [`data/results/run-syn24-pecko-ram/compare_vs_baseline-syn24-b0.txt`](data/results/run-syn24-pecko-ram/compare_vs_baseline-syn24-b0.txt) (per-turn transcripts and answers included).

**RAM history (honest):** the first integrated build peaked at 1140 MiB, *above* B0 (`data/results/run-syn24-pecko`). Profiling each component showed Moonshine Small loading and then being thrown away at `--ears-tier 2` (+217 MiB) and `import torch` used only for Silero VAD (+128 MiB). Building Ears at the requested tier and running Silero on onnxruntime brought the peak to 846 MiB. B0 still uses the stock torch Silero, so part of the 71 MiB lead is that choice. Model files were already in the page cache, so a cold start was not measured, and that holds for both stacks.

### Where Pecko's time goes: C vs R (first audio = max(C, R) + d)
From `python3 scripts/turn_report.py data/results/run-loop6-commitfix` (4 real-voice WAV turns, same cap, peak 996 MiB, `oom_kill 0`):
- **C (commit gate) lands 300-440 ms after end of speech** on LLM turns (437, 398, 302 ms). In the syn24 run (`turn_report.py data/results/run-syn24-pecko`) C was 291-323 ms on all 24 turns vs B0's fixed ~803 ms endpoint.
- **R (first answer clause PCM ready) is later than C on every LLM turn**: 956, 753, 676 ms in loop6; 499-1693 ms in syn24 (R > C on 24/24, all on the held path). So the LLM + first-clause synthesis is now the critical path, not endpointing; making C faster would gain 0 ms on these turns.
- The one cached turn ("thank you") had C = R = 1209 ms: the endpointer waited longer on a short utterance, so the cache saved nothing there. n = 1; not a cache latency claim.
- Earlier 4-turn paired run (`data/results/baseline-loop5-b0/compare_vs_run-loop5-zip.txt`): Pecko p50 700 / p90 1225 ms vs B0 1757 / 1957 ms, faster 4/4, CPU-s/turn 0.85 vs 1.74, peak RAM 1481 vs 813 MiB. n = 4, so p90 ≈ max.

### Component results (not end-to-end)
- **Brain ablation** (Ubuntu VM, same cap, 12 scripted turns × 3 = 36, times from `final` to first chunk, [`brain/RESULTS.md`](brain/RESULTS.md)): no cache 1024 / 1198 ms (p50/p90) → + system-prompt KV cache 290 / 813 → + early prefill (stable) 231 / 265 → + `tentative_final` prefill 177 / 213 ms. After the history fix, re-run: tentative_final 178 / 220 ms, wasted prefill 10-19%.
- **LLM quantization** (same source): Q4_K_M beats Q8_0 on first chunk p50, 177 vs 261 ms. Q8 answer quality not scored yet.
- **TTS quantization** ([`voice/RESULTS.md`](voice/RESULTS.md), **Windows dev laptop, not the judged machine**): Piper int8 is 2.4-3.2× *slower* than fp32 under co-run, so we ship fp32 with 1 ONNX thread.
- Ears: [`ears/RESULTS.md`](ears/RESULTS.md). Spine status: [`spine/BUILD_STATUS.md`](spine/BUILD_STATUS.md).
- The A0→A7 end-to-end ablation waterfall, the degradation curve under tighter caps, and the 60 held-out human turns are **not yet measured**.

### Honest caveats
- **Synthetic speech.** Questions are Piper TTS ("Hey Pecko, ..."), not human voices; a sanity set, not the held-out set. Real voices will be harder.
- **VM, not native.** VirtualBox may add scheduling noise; no RAPL, so no energy numbers yet.
- **No speaker.** d = 0 ms on both stacks; a real device adds its output latency to both.
- **RAM lead is thin** (846 vs 917 MiB). Part of it is that Pecko's Silero VAD runs on onnxruntime without torch, while B0 uses the stock torch Silero (~128 MiB for `import torch`). Both stacks share the same llama-server and Piper memory.
- **One run each, n = 24.** p90 of 24 turns is a rough estimate.
- **ASR mishears** in both stacks: "Romeo **when** Juliette" (loop5/loop6), "**why** is the boiling point of water", "what **cast** do plants take in", "cricket**ine**"; B0 twice kept the wake word ("PACKO ...").
- **Some answers are wrong** (same 0.6B model in both): Pecko said "a week has 7 hours", "0 players on a cricket", "7 continents in our solar system", "Juliette wrote Romeo"; B0 said the Mona Lisa was by Van Gogh. Latency is not answer quality; quality is not scored yet.
- Fillers are off in every number.

### How to reproduce
```sh
.venv/bin/python scripts/make_question_set.py      # 24 synthetic WAVs -> data/clips/synthetic24/
PECKO_CPUS=2,3 scripts/run_baseline.sh --wav data/clips/synthetic24/q*.wav --out data/results/baseline-syn24-b0
PECKO_CPUS=2,3 scripts/run_pecko.sh --wav data/clips/synthetic24/q*.wav --ears-tier 2 --no-audio --out data/results/run-syn24-pecko
.venv/bin/python scripts/compare_runs.py data/results/run-syn24-pecko data/results/baseline-syn24-b0
python3 scripts/turn_report.py data/results/run-syn24-pecko   # per-turn C / R / path
```

## Phone (in progress)
A Flutter Android app is planned and under construction in `mobile/`. See [`mobile/PLAN.md`](mobile/PLAN.md). Not finished; no phone result is claimed.

## Other tools
```sh
.venv/bin/python -m pytest -q                     # all tests
.venv/bin/python -m brain.mock_cli                # Brain from typed text
.venv/bin/python -m ears.mock data/clips/hindi10.wav --push-to-talk --fast   # Ears from a WAV, contract JSONL on stdout
.venv/bin/python -m frontend                      # typed-text evaluator demo, http://127.0.0.1:8765
```

Ears scripts: `scripts/measure.py` (WER, endpoint delay, false cut-offs, RSS, idle CPU over the clip set), `scripts/ablation.py` (fixed 800 ms vs 400 ms vs fusion endpointer), `scripts/test_tier_switch.py` (tier-switch time and peak RSS). Spine foundation checks: `python -m spine.mock`, `python -m spine.linux --cpus 0,1 --dry-run`. Synthetic Spine runtime and experiment commands: see [`spine/README.md`](spine/README.md) and [`spine/RECORDED_INPUT.md`](spine/RECORDED_INPUT.md). Their outputs are synthetic and labelled so.

## Evaluator frontend
A local presentation workspace: a typed intent demo, recorded voice samples, model comparisons, a synthetic pipeline replay and an evidence library. Fonts and assets are bundled; no Node build or internet is needed at runtime. Run `.venv/bin/python -m frontend`, open **http://127.0.0.1:8765** (`--port 8766` to change; Ctrl+C to stop).

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

## Layout
`ears/ brain/ voice/ spine/ mobile/ frontend/ common/ docs/ data/ scripts/ tests/`. Contract: `docs/CONTRACT.md`. Models live in `models/` (gitignored).

## Limits and honesty
- Only numbers in the `RESULTS.md` files and in `data/results/` (as quoted in Results above, with their conditions) are measurements; synthetic traces and replays are labelled as such.
- The frontend text demo does not run ASR or TTS and does not measure latency. General questions there need a running `llama-server` on `127.0.0.1:8080`; the default prompt family is Qwen3 (`--model-family lfm2` only with a matching model).
- Licenses to respect: Piper (GPL-3), MMS (non-commercial), LFM Open License.
