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
Measured results are kept next to the code that produced them. Read them there; this README does not copy numbers.
- Brain: [`brain/RESULTS.md`](brain/RESULTS.md)
- Ears: [`ears/RESULTS.md`](ears/RESULTS.md)
- Voice: [`voice/RESULTS.md`](voice/RESULTS.md)
- Spine status: [`spine/BUILD_STATUS.md`](spine/BUILD_STATUS.md)

The full baseline-vs-Pecko end-to-end comparison (p50/p90 latency, CPU-s/turn, peak RAM, J/turn, ablation table) is not in this README yet. Anything not in those files is not a measurement.

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
- Only numbers in the `RESULTS.md` files are measurements; synthetic traces and replays are labelled as such.
- The frontend text demo does not run ASR or TTS and does not measure latency. General questions there need a running `llama-server` on `127.0.0.1:8080`; the default prompt family is Qwen3 (`--model-family lfm2` only with a matching model).
- Licenses to respect: Piper (GPL-3), MMS (non-commercial), LFM Open License.
