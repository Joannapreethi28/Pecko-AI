# HANDOFF: VOICE (owner: Joanna)
For teammates. Each role keeps its own `docs/handoff_<role>.md`. Status as of the latest phase.

## Status
- Spine-ready: `voice/team_adapter.py` (`create_stage`) passes Spine's scripted plan 3/3 inside the real bus (`tests/test_voice_spine_integration.py`).
- P0–P5 done: VoiceStage (contract v2 + v2.1 hold/commit), benchmark + quantization study, cache (L2/L3/L4 + composed time/date), voice ladder T0–T3 + fallback + half-duplex, chunking ablation (A4). Full guide: `voice/README.md`.
- Voice decisions: fp32, 1 ONNX thread, T0 lessac-medium / T1 lessac-low **provisional until the Ubuntu-under-cap bench**.
- Cache: full cache serves first audio for 30/39 unseen held-out turns with no synthesis; CPU per turn 172 → 44 ms (windows-dev).

## Contract Voice implements
v2 (`docs/CONTRACT.md`) **plus v2.1 hold-and-release**:
- `chunk` with `held:true` → synthesized into a private buffer, **not played** until `{"type":"commit","turn","gen"}`.
- `cancel` for that `gen`, or any newer `gen`, drops held text/PCM.
- Voice logs `pcm_ready` (= **R**, first clause PCM ready) and `first_audio_out`.

## Setup (Windows or Ubuntu)
```
python -m venv .venv && .venv/bin/python -m pip install -r voice/requirements.txt   # Windows: .venv\Scripts\python
python voice/get_models.py --all        # downloads Piper lessac voices into models/ (once, before going offline)
sudo apt install libportaudio2 espeak-ng   # Ubuntu only (Windows: winget install eSpeak-NG.eSpeak-NG)
python -m voice.cache --build --pack vits-piper-en_US-lessac-medium   # prebuild clips (~10 s each, once)
python -m voice.cache --build --pack vits-piper-en_US-lessac-low
python -m voice.bench --tag ubuntu-cap  # Sir Jabin/Spine: run INSIDE the cgroup on the judged machine (~8 min, silent)
```

## Asks
- **Spine:** send `commit` (C) for the turn/gen; Voice will play held PCM immediately on it. Voice now logs through `common/log.py` (`EventLog("voice", logs/voice.jsonl)`).
- **Spine (cgroup trap, please check):** `AllowedCPUs=2,3` may be **two hyperthreads of one physical core** (Intel numbering on Windows is sibling pairs 0,1 | 2,3; on Linux check `/sys/devices/system/cpu/cpu2/topology/thread_siblings_list`). That silently halves the real CPU of the "2 CPU" cap and makes every stage look slower. Pick two CPUs whose sibling lists differ (and both P-cores on a hybrid CPU). `voice/bench.py::bench_cores()` does this automatically.
- **Brain:** first chunk at the first `, . ? ! ;` after ≥2 words or 6 tokens; mark pre-final chunks `held:true`; `intents.yaml` agreed with Voice (P3).
- **Ears:** read `playback_state` to raise the VAD threshold while Pecko speaks; send `barge_in`.

## Use it
```python
from voice.stage import VoiceStage
v = VoiceStage(on_event=print, tier=0)   # on_event gets playback_state, tier_switch, turn_summary
v.start()                                # loads + warms the voice, opens the audio stream (~1.3 s)
v.feed({"type":"chunk","turn":1,"gen":1,"seq":0,"text":"Sure, ","held":True})
v.feed({"type":"commit","turn":1,"gen":1})
v.stop()
```
Standalone mock (plays audio): `python -m voice --mock voice/sentences.txt`. Log: `logs/voice.jsonl`.
Mock result on Windows (not under cap): hold-and-release first audio p50 768 ms vs 1204 ms without it, 0 gaps.

## For Brain (Sir Jabin)
- Voice consumes `brain/intents.yaml` directly: every `say` is pre-synthesized per voice and played on `{"type":"cached","clip":...}`. Add/edit intents freely; Voice regenerates only changed clips (manifest).
- Composed time/date/day sentences are rebuilt from pre-made pieces, matching `time_words` / `date_words` / `day_words` **exactly**. Please tell Voice if that wording changes.
- One-word stock openers ("Sure.", "Okay,", "Sorry,") are played instantly from cache when they start a reply.

## For Spine
- `VoiceStage(audio=False)` uses a silent `NullPlayer` (WAV-in runs, CI, the harness): same events, no device.
- Measured on this Windows ultrabook: 2 ONNX threads is slower than 1 under co-run. Please keep Voice at 1 thread in the core plan.

## Voice ladder (Spine sends `{"type":"tier","tier":n}`; applied between turns only)
| Tier | Uncached text spoken by | Cached clips | Switch cost (windows-dev) | Process RSS |
|---|---|---|---|---|
| T0 | Piper lessac-medium | lessac-medium | (start) | ~223 MB |
| T1 | Piper lessac-low | lessac-low | ~750 ms (reload) | ~198 MB |
| T2 (= phone profile) | Piper lessac-low | lessac-low | ~30 ms (no reload) | ~211 MB |
| T3 | espeak-ng (robotic, ~38 ms / 8 words) | lessac-low | ~90 ms | ~95 MB |
- If a tier cannot load, Voice falls down the ladder; if nothing loads, it keeps its previous voice (`tier_load_failed`, `tier_load_recovered` events).
- If one phrase fails to synthesize, espeak-ng speaks that phrase (`synth_fallback`), so the user never hears silence.
- **Half-duplex switch for the judged run:** `VoiceStage(barge_in=False)` or `python -m voice --barge-in off` ignores `barge_in` (logs `barge_in_ignored`). Use it if speaker echo makes Pecko stop itself.

## Master ablation rows Voice owns (solution.md §7), windows-dev numbers
| Row | Measured | Where |
|---|---|---|
| A4 clause-streamed TTS | adaptive p50/p90 409/460 ms vs sentence 813/1326 ms (measured Brain speed, C = 400 ms); sentence-only gaps 1.3 s with a slow Brain | `python -m voice.eval_chunking`, `voice/RESULTS.md` |
| A6 hold-and-release (Voice side) | first audio p50 736 ms vs 1204 ms without it (mock Brain/Spine timing) | `python -m voice --mock voice/sentences.txt` |
| A7 router + cache-first (Voice side) | 30/39 unseen turns start with no synthesis; CPU 172 → 44 ms/turn; router false hits 0/18 | `python -m voice.eval_cache` |
| Quantization (15 %) | fp32 beats int8 by 2.4–3.2×; int8 sounds different; fp16 low/medium fail to load | `python -m voice.bench`, `python -m voice.quality` |

## For Sir Jabin: block to link from the main README
```markdown
### Voice (speaking)
Piper lessac voices on sherpa-onnx (1 thread, fp32), phrase streaming, hold-and-release (contract v2.1), a pre-synthesized cache
(intents, openers, composed time/date) and a T0-T3 voice ladder down to espeak-ng. Setup, commands and results: [voice/README.md](voice/README.md).
```

## Still open (needs the team)
- Final T0 voice: run `python -m voice.bench --tag ubuntu-cap` inside the cgroup on the judged machine and apply the rule in `voice/RESULTS.md`.
- Spine: confirm `AllowedCPUs` are not hyperthread siblings; send `commit`; keep Voice at 1 thread.
- Ears: `barge_in` + raise the VAD threshold during `playback_state.playing` (no echo cancellation yet).

## Spine integration (`voice:team`)
```python
from voice.team_adapter import create_stage as create_voice
registry["voice:team"] = create_voice
# profile: "voice": {"adapter": "team", "config": {"tier": 0, "audio": true, "barge_in": true, "device": null, "threads": 1}}
```
- `playback_state` → `ctx.publish`; every Voice log event is mirrored to `ctx.log` (except `turn_done`, `cache_ready`).
- `first_audio_out` carries `gen`, `content: true`, `sustained: true` (first clip ≥ 100 ms of speech); `pcm_ready` carries `gen`, `seq: 0`. These are exactly what `spine/report.py` needs for the headline and for R.
- Turn end → `ctx.complete(turn, gen, success, reason, gap_s)`: success = audio played and no barge-in; `gap_s` = total measured playback gaps.
- Unexpected worker errors → `ctx.fail`. Per-phrase synthesis errors are handled inside Voice (espeak fallback) and are not fatal.
- `config.audio=false` uses the silent NullPlayer (WAV-in / CI runs).
