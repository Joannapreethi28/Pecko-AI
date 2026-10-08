# Brain handoff (a NEW Claude session can resume from this file alone)
Owner: Sir Jabin · Last update: 8 Oct, late night (Ubuntu VM session) · Branch `main` (everyone pushes to main, own folders only, `git pull --rebase` before push, never force-push). Update this file whenever you push.

## 1. Resume in 60 s
Read in this order: `brain/CLAUDE.md` → this file → `brain/gotcha.md` (G1-G12) → plan `docs/superpowers/plans/2026-10-08-brain-stage.md` (only the task you work on + Global Constraints + Review Focus).
- **Run tests (Windows, Python 3.13 `.venv`):** `.venv/Scripts/python -m pytest -q tests`. Ubuntu VM: `bash scripts/setup_vm_brain.sh`, then `.venv/bin/python -m pytest -q tests`.
- **Start the server (Windows):** `models/llama.cpp/b11501-win/llama-server.exe -m models/Qwen3-0.6B-Q4_K_M.gguf -c 2048 -np 1 -t 1 -tb 2 -ctk q8_0 -ctv q8_0 --host 127.0.0.1 --port 8080`
- **Talk to Brain:** `.venv/Scripts/python -m brain.mock_cli [--speak]` (`--speak` simulates speech so early prefill runs).
- Live tests are skipped unless `PECKO_LLAMA_PORT=8080` is set.
- Windows shell traps: `cd "<abs path>" &&` in every command (G2), no multi-heredoc commands (G12), `/c`-style args get rewritten (G1).

## 2. Task status (plan Tasks 1-12)
| Task | State | Note |
|---|---|---|
| 1 clock + log | DONE | `common/clock.py`, `common/log.py` |
| 2 chunker + speakable | DONE | |
| 3 prompt builder | DONE | `brain/prompt.py` |
| 4 llama client/server/probes | DONE | `brain/llama_client.py`, `llama_server.py`, `probe_server.py` |
| 5 BrainStage core | DONE | `brain/stage.py`, `tiers.py` |
| 6 typed-text mock | DONE | `brain/mock_cli.py`, verified live |
| 7 early prefill | DONE | stage logic by lead; `brain/sim.py` + `--speak` |
| 8 router + intents | DONE | `router.py`, `intents.yaml`, stage wiring (commit dea3294) |
| 10 tier switching | DONE (logic + fake-server tests) | live VM switch timing NOT measured |
| 12 ablation | CODE DONE, not run | `brain/ablate.py`, `ablation_turns.jsonl` |
| 9 bake-off | RUN, quality pending | all 4 models measured under the cap (RESULTS.md). T0 provisionally Qwen3-0.6B. Blind sheet built: a teammate scores `data/results/blind_scores.csv` (never show `blind_scores_key.csv`), then `python -m brain.score_sheet --tally` |
| 11 hold-and-release | DONE | commit b54f2c1; contract v2.1 approved by all four (CONTRACT.md) |
| 12 ablation | RUN (Q4 all configs + Q8) | RESULTS.md; history cache bug FIXED (block trim + idle base warm-up): sys_cache first-chunk p90 813 → 324 ms. TODO: re-run to get wasted % with the fixed metric |
| 10 real run | NOT STARTED | live T0→T2→T3→T0 switch timing under the cap |

Tests (Ubuntu VM, after Voice merge): 223 pass, 5 skipped (1 Windows-only, 3 live, 1 Piper model missing). Needs `pip install -r voice/requirements.txt` + `sudo apt install libportaudio2`. Live tests with llama-server on :8080: 3/3 pass.

## 3. Measured so far
### ubuntu-vm (8 Oct)
- **Cap command (no sudo needed):** `systemd-run --user --scope --unit=pecko-bakeoff -p CPUQuota=200% -p MemoryMax=2G -p MemorySwapMax=0 --setenv=HF_HUB_OFFLINE=1 -- taskset -c 0,1 .venv/bin/python -m brain.bakeoff --model models/Qwen3-0.6B-Q4_K_M.gguf --family qwen3 --label <label>`. Inside: `cpu.max 200000 100000`, `memory.max 2147483648`, `memory.swap.max 0`. `AllowedCPUs` is ignored in a user scope, hence `taskset`. Evict the model from page cache first (G17).
- **Bake-off, Qwen3-0.6B Q4_K_M, ubuntu-vm, 2 CPU / 2 GB cgroup:** TTFT p50 103 / p90 123 ms (n=20), rewind TTFT p50 103 ms, no reprocessing, decode 34.1 tok/s, cgroup peak 814 MB.
- **Bake-off, other 3 models, same cap:** Qwen3-1.7B Q4_K_M p50 256 ms, 13.6 tok/s, 2012 MB (fills the cap, fails RAM rule); LFM2.5-1.2B Q4_0 p50 232 ms, 19.8 tok/s, 1370 MB, rewind reprocesses; LFM2.5-350M Q4_0 p50 69 ms, 58.7 tok/s, 450 MB, rewind reprocesses. LFM replies are coherent (no BOS problem), but they invent live weather.
- **Ablation, same cap (server + harness in one scope), n=36/row:** first chunk p50 no_cache 1024 → sys_cache 290 → early_stable 231 → early_tentative 177 → router 182 ms; Q8 early_tentative 261 ms. Runner: start llama-server and `python -m brain.ablate --label <l> --configs ...` inside one `systemd-run --user --scope ... -- taskset -c 0,1 sh -c ...`.
- **Live mock, no cap (`ubuntu-vm, uncapped, not judged`), same 3 questions as Windows:** first_token 101 / 113 / 132 ms (Windows 110 / 127 / 157); first_chunk 251 / 285 / 324 ms (Windows 268 / 296 / 325); computed 18-22 tokens, reused 84-147; decode 30-38 tok/s. Same wrong sky answer and "366" digits.
### windows-dev, not judged
- Probe: `n_predict:0` yields 1 token, so `DEFAULT_PREFILL_N_PREDICT=1` (G11). q8_0 V cache works without `-fa`. Client disconnect stops generation in 92 ms. Rewind keeps the full common prefix (cache_n 37 == lcp 37).
- Live mock, 3 turns: first_token 110 / 127 / 157 ms; first_chunk 268 / 296 / 325 ms; prompt computed 18-22 tokens, reused 84-148; decode 32-37 tok/s.
- Router held-out (36 rows): 18/18 hits, 0 wrong, 0/18 false hits.
- Quality problems: Qwen3-0.6B said the sky is blue because of water droplets (wrong). It outputs digits ("366") despite the prompt, so tell Voice to normalise numbers.
- Idea to ablate: `first_max_pieces` 6 → 4 (about 60 ms earlier first chunk).

## 4. What other roles need to know / do (reply in your own handoff file)
| To | Ask | Why |
|---|---|---|
| **Spine** | `common/clock.py` (`now()`) and `common/log.py` (`EventLog`) exist, exactly the CONTRACT line format. Extend, don't change. Root `pyproject.toml` is pytest config only. | Everyone imports them. |
| **Spine** | Brain used a `--user` scope + `taskset` (no passwordless sudo in the VM). For the judged run, confirm the sudo `AllowedCPUs` form, and evict model files from page cache before reading `memory.peak` (G17). | `memory.peak` silently under-reports cached model pages. |
| **Ears** | `partial.stable`, `tentative_final.text` and `final.norm` must use the **same normalization** (lowercase, no punctuation, same filler handling). Brain builds the prompt from them. | If they differ, early prefill misses the KV cache and saves 0 ms. |
| **Voice** | `brain/intents.yaml` is pushed: each `clip` + exact `say` text is a reply to pre-synthesize (incl. `didnt_catch`, `low_power`). Brain sends a final **empty** chunk with `last:true` at reply end. | Cached replies skip the LLM; empty last = end of turn. |
| **Voice** | Normalise digits to words before TTS (the 0.6B model writes "366"). Every chunk ends with a space except the last; first chunk is cut at the first `, . ? ! ; :` after ≥ 2 words. | Phrase boundaries you can trust. |
| **All** | Hold-and-release (contract v2.1: `held:true`, `commit`) is Task 11, built only after all four agree. Brain will log `held_valid{gen, match}` so Spine knows when to send `commit`. | Contract changes need all four. |
| **Mobile** | llama.cpp b11501 ships `llama-b11501-bin-android-arm64.tar.gz`; may save the Termux build. | Phone spike speed. |

## 5. Multi-session setup
- Lead session: `hacknex-26-4b` (Opus). Workers (Sonnet) are launched with `claude --model sonnet --permission-mode acceptEdits "You are worker wN. Read brain/WORKER.md, then do Task X ..."`.
- Workers commit locally only (never pull/push); the lead verifies and pushes. Rules for workers: `brain/WORKER.md`. Workers report: `wN: Task X done | tests: N passed | commit <sha> | deviations | gotcha`.

## 6. Environment facts
- Laptop: i7-14650HX, 24 threads, 15.6 GB. Hyper-V is ON, so VirtualBox 7.2.6 may hide AVX2 from the VM (G9). Fix: `bcdedit /set hypervisorlaunchtype off` + Memory integrity off; Sir Jabin decides.
- Ubuntu VM: 6 vCPU, 6 GB. Likely no RAPL (energy would be labelled "not joules"). Check `grep -o -m1 avx2 /proc/cpuinfo` first.
- Judged numbers: Ubuntu under the 2 CPU / 2 GB cgroup only.

## 7. Open decisions (Sir Jabin / team)
1. ~~Contract v2.1~~ approved by all four; Task 11 done.
2. Dashboard owner. Proposal: local offline web page on :8765, served by Python reading the JSONL logs; panels: pipeline, transcript, C-vs-R race chart, CPU/RAM vs cap, controls.
3. Bake-off T0 choice (rule in `brain/SPEC.md`; default Qwen3-0.6B).
4. Hyper-V off or not (section 6).

## 8. In progress by the lead
Team Board Claude Code mod (pane + status line + contract-edit guard). Dev folder `~/.claude/dev-mods/<session>/team-board`, to be copied to `tools/mods/team-board`.

## Skills (optional)
`bash scripts/install_skills.sh` (see `docs/SKILLS.md`).
