# VOICE CONTEXT (living file, owner: Joanna)
Update after every phase. Source of truth for the role: `voice/SPEC.md`, `docs/solution.md` (v2), `docs/CONTRACT.md` (v2 + **v2.1 hold-and-release, adopted for Voice**).

## Setup facts
- **Dev machine: Windows.** **Judged machine: Ubuntu (Sir Jabin runs it).** Code must be cross-platform: `pathlib`, sounddevice/PortAudio, no Windows-only libs, LF line endings (`.gitattributes`).
- Venv: `Pecko-AI/.venv` (gitignored). Install: `python -m pip install -r voice/requirements.txt`. Ubuntu also: `sudo apt install libportaudio2`.
- Models: `python voice/get_models.py --all` → `models/vits-piper-en_US-lessac-{low,medium,high}{,-fp16,-int8}`. Never downloaded at runtime.
- Logs: `voice/vlog.py` → `logs/voice.jsonl` (switches to `common/log.py` automatically once Spine adds it).
- Nothing is pushed until the team decides. The earlier Windows prototype (`../voice`, `../demo.py`) is reference only, not reused.

## Phase plan (2 h budget)
| Phase | Scope | Status |
|---|---|---|
| P0 | setup: venv, requirements, model script, log shim, gitignore, docs | **done** |
| P1 | core VoiceStage: contract v2 + v2.1 hold/commit, reorder + 300 ms gap timeout, normalizer, chunker, synth worker, ring buffer, event-driven events, standalone mock | **done** |
| P2 | benchmark grid + quantization (fp32/fp16/int8 × low/medium/high × threads × lengths) → `voice/RESULTS.md` | **done** (final T0 needs the Ubuntu run) |
| P3 | cache L2/L3/L4 + composed time/date (from Brain's `intents.yaml`) + hit/false-hit + ablation | **done** |
| P4 | tiers T0–T3 lazy switch, espeak bottom tier, per-phrase fallback, half-duplex | **done** |
| P5 | chunking ablation, pytest, Ubuntu notes, handoff | **done** |

## Work log
- 2026-10-08 P0: repo venv + deps (sherpa-onnx 1.13.8), all lessac variants downloaded, `vlog.py`, gitignore (`logs/`, `voice/cache/`, `*.npy`), docs created.
- 2026-10-08 P1: core stage built. Files: `voice/text.py` (normalize + v1 chunker), `voice/engine.py` (Piper/sherpa, 1 thread, warm-up, finish_clip),
  `voice/player.py` (preallocated 60 s ring buffer, callback copies only, events via SimpleQueue → blocking consumer),
  `voice/stage.py` (contract v2 + v2.1 hold/commit/cancel/supersede, seq reorder + 300 ms skip, 2 s stall finish, tier switch between turns),
  `voice/__main__.py` (mock: `python -m voice --mock voice/sentences.txt`), `tests/test_voice_text.py` (5 pass).

### P1 mock results (Windows, lessac-medium, 1 thread, built-in speakers, MME device buffer 92.9 ms, NOT under a cap)
Mock timing: Brain TTFT 250 ms, 60 ms/word, Spine commit C = 400 ms after acoustic end. 8 replies per mode.
| Mode | first audio p50 / p90 (from acoustic end) | chunk→sound p50 / p90 | gaps |
|---|---|---|---|
| v2.1 hold-and-release | **768 / 842 ms** | 246 / 282 ms | 0 / 8 turns |
| v2 (start after commit) | 1204 / 1233 ms | 260 / 312 ms | 0 / 8 turns |
- Hold-and-release saved ~436 ms p50 in this mock (Brain text generation hidden behind C). R > C on 7/8 turns → R (Brain+Voice) is the critical path with these mock timings.
- Cancel scenario: held "wrong guess" gen 1 synthesized, dropped on Ears `cancel`, never audible; gen 2 played. Barge-in stop 93–124 ms (≈ device buffer).
- 2026-10-08 P2: pulled Jabin's push (Brain stage, common/clock+log, skills). Venv rebuilt on **Python 3.13.15** (QPC clock; team standard).
  Installed skills: impeccable, writing-guidelines (pinned commits). `voice/bench.py` + `voice/quality.py`. Results in `voice/RESULTS.md`:
  fp32 everywhere, 1 thread, high rejected, provisional T0 medium / T1 low pending the Ubuntu run (rule picks low on this ultrabook).
- 2026-10-08 P3: `voice/cache.py` (L4 intents from brain/intents.yaml, C composed time/date/day pieces, L2 openers, L3 memo,
  per-pack manifest), `NullPlayer`, chunker opener exception, `voice/eval_cache.py`, `tests/test_voice_stage.py` (10 tests).
  Pass 1 (unseen): full cache = first PCM from cache 30/39 turns, synth calls 58→27, CPU 172→44 ms/turn. Router false hits 0/18.
  Full suite: 115 passed, 3 skipped (live llama).
- 2026-10-08 P4: voice ladder in `voice/engine.py` (`TIERS`: T0 medium · T1 low · T2 low+cache (no reload) · T3 espeak-ng + low's
  cached clips; `PHONE_TIER = 2`), `EspeakEngine` (CLI, installed via winget eSpeak-NG 1.52.0), `make_engine()`.
  Stage: `_load_tier` (unload first, fall down the ladder, recover previous voice if nothing loads), per-phrase fallback to
  espeak-ng, half-duplex `barge_in=False` / `--barge-in off`. `voice/eval_tiers.py`, `tests/test_voice_tiers.py` (8 tests).
  Measured (windows-dev): T0→T1 748 ms (223→198 MB) · T1→T2 31 ms no reload · T2→T3 92 ms (213→95 MB, uncached 8 words 38 ms)
  · T3→T0 768 ms · cached intents stay L4 on every tier. Full suite 123 passed, 3 skipped.
- 2026-10-08 P5: chunking ablation `voice/eval_chunking.py` (A4; real synthesis times + Spine's `playback_gaps`/`playback_start`):
  adaptive p50/p90 409/460 ms vs comma 409/573, sentence 813/1326 (sentence gaps 1.3 s with a slow Brain); word-by-word fastest
  start but +75 % synthesis CPU and choppy. `PhraseChunker(policy=...)` for the ablation only. `voice/README.md` (reviewed with the
  writing-guidelines skill), Ubuntu notes, final handoff. Full suite 124 passed, 3 skipped. Spoken check after P3/P4: 8 replies, 0 gaps, 0 errors.
- **All five phases done. Nothing pushed yet**: push list to be agreed with the team.
- 2026-10-08 P5 (cont.): pulled 7 team commits (contract v2.1 approved by all four, Brain hold-and-release, Spine runtime/bus,
  EventLog emit+event). Added `voice/team_adapter.py` (Spine `StageContext` contract), Spine-required event fields, `on_error` → `ctx.fail`.
  Fixed: cancelled speculative gen marked the whole turn failed. Real Voice inside Spine's bus: scripted plan 3/3.
  Full suite 225 passed, 3 skipped.
