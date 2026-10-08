# Voice: Pecko's speaking stage

Voice turns Brain's reply text into sound. It starts speaking at the first phrase and plays common answers from pre-made audio. It stops when the user interrupts. When the CPU or RAM budget shrinks, it steps down to lighter voices. Everything runs offline on the CPU.

Owner: Joanna. Contract: `docs/CONTRACT.md` (v2 + v2.1 hold-and-release). Build spec: `voice/SPEC.md`. Team-facing status: `docs/handoff_voice.md`.

## How it works

```text
Brain chunk ─► turn/gen filter ─► seq reorder (skip a missing seq after 300 ms) ─► phrase chunker ─► normalize
          ─► cache (opener, memo, intent clip, composed time/date) or Piper synthesis (1 ONNX thread)
          ─► held? private hold buffer until `commit` : ring buffer ─► audio callback ─► speaker
```

- **Hold-and-release (v2.1)**: Brain can send chunks marked `held:true` before the user has finished. Voice synthesizes them privately and plays them the moment Spine sends `commit`. A `cancel` or a newer `gen` drops them unheard.
- **Phrase chunking**: The first phrase is cut at the first punctuation mark or after 6 words, so speech starts early. Later phrases grow to a full sentence while the audio buffer is more than 300 ms ahead.
- **Cache**: Every intent reply in `brain/intents.yaml`, 18 stock openers and 133 time/date pieces are pre-synthesized in the live voice. Every phrase spoken in a session is remembered.
- **Voice ladder**: T0 lessac-medium, T1 lessac-low, T2 lessac-low plus cache, T3 espeak-ng plus cached clips. Tiers change only between turns.
- **Safety**: A phrase that fails to synthesize is spoken by espeak-ng instead. A tier that fails to load falls down the ladder. Barge-in stops playback with a short fade. `barge_in=False` turns barge-in off (half-duplex).

## Setup

Windows (development) and Ubuntu (judged) use the same commands. Python 3.13 on Windows (3.12 has a 15.6 ms clock); any Python 3.10+ on Ubuntu.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r voice/requirements.txt -r brain/requirements.txt   # Windows: .venv\Scripts\python
sudo apt install libportaudio2 espeak-ng          # Ubuntu. Windows: winget install eSpeak-NG.eSpeak-NG
python voice/get_models.py --all                  # Piper lessac voices -> models/ (once, before going offline)
python -m voice.cache --build --pack vits-piper-en_US-lessac-medium   # pre-synthesize clips, ~10 s each, once
python -m voice.cache --build --pack vits-piper-en_US-lessac-low
```

## Run

| Command | What it does | Sound? |
|---|---|---|
| `python -m voice --mock voice/sentences.txt` | Standalone mock: Brain-like chunks plus Spine `commit`, A/B of hold-and-release vs plain v2, a cancel turn and a barge-in turn | **Yes** |
| `python -m voice --mock voice/sentences.txt --barge-in off` | Same, half-duplex | **Yes** |
| `python -m voice.bench [--tag ubuntu-cap]` | Benchmark grid: 3 voices × fp32/fp16/int8 × 1/2 threads × solo/co-run, ~8 min | No |
| `python -m voice.quality` | Relative quality distance of quantized voices vs fp32 | No |
| `python -m voice.eval_cache` | Cache ablation on Brain's held-out phrasings | No |
| `python -m voice.eval_tiers` | Walks the voice ladder T0→T1→T2→T3→T0 | No |
| `python -m voice.eval_chunking` | Chunking ablation (row A4) with Spine's playback math | No |
| `python -m pytest -q tests` | Whole team suite, incl. real Voice inside Spine's bus | No |

Use it from code:

```python
from voice.stage import VoiceStage
v = VoiceStage(on_event=print)            # audio=False for a silent NullPlayer; barge_in=False for half-duplex
v.start()
v.feed({"type": "chunk", "turn": 1, "gen": 1, "seq": 0, "text": "Sure, here it is.", "held": True, "last": True})
v.feed({"type": "commit", "turn": 1, "gen": 1})
v.stop()
```

In Spine's runtime, register `voice.team_adapter.create_stage` as `voice:team` (see `docs/handoff_voice.md`).

Events go to `logs/voice.jsonl` in the contract format through `common/log.py`: `chunk_recv`, `synth_start`, `synth_end`, `pcm_ready` (R), `commit_recv` (C), `first_audio_out`, `gap`, `underrun`, `barge_in_stop`, `cache_hit`, `tier_switch`, `turn_done`.

## Results so far

All numbers are `windows-dev, not judged`: an i7-1365U ultrabook on the charger, outside the cgroup. Full tables are in `voice/RESULTS.md`. Judged numbers come from Ubuntu under Spine's 2 CPU / 2 GB cap.

- **Precision**: fp32 wins. int8 is 2.4–3.2× slower on this CPU and sounds different. The low and medium fp16 packs do not load in sherpa-onnx 1.13.8.
- **Threads**: 1 ONNX thread. A second thread is slower while Brain shares the cores.
- **T0 voice**: lessac-medium is provisional. The 150 ms rule picks lessac-low on this ultrabook (medium is 177 ms for an 8-word phrase under co-run). Re-run the benchmark on the judged machine.
- **Hold-and-release**: First audio p50 736 ms vs 1204 ms without it (mock Brain, commit at 400 ms).
- **Cache**: On 39 unseen turns, 30 get their first audio with no synthesis. CPU per turn drops from 172 to 44 ms. Router false hits: 0/18.
- **Chunking**: The adaptive rule has the best p90 (460 ms vs 573 comma and 1326 sentence) with fewer synthesis calls than comma.
- **Ladder**: T3 runs the process in 95 MB (from 223 MB at T0), and cached answers keep the natural voice.
- **Barge-in**: Stops within one audio block (about 23 ms) plus the device buffer (93 ms with MME, the default Windows audio API).

## Ubuntu notes (judged machine)

- Install `libportaudio2` for sounddevice and `espeak-ng` for T3. Use wired or built-in speakers; Bluetooth adds 150–300 ms.
- PipeWire and PulseAudio can add buffering. Check `VoiceStage.start()["out_latency_ms"]`. If it is high, select the ALSA device directly with `VoiceStage(device=...)` (list devices with `python -m sounddevice`).
- Run the benchmark inside the cgroup: `python -m voice.bench --tag ubuntu-cap`. It picks two CPUs on different physical cores from `/sys/devices/system/cpu/*/topology`. Make sure Spine's `AllowedCPUs` are not hyperthread siblings.
- Use the charger and the performance power profile for every measured run. `voice.bench` records the power state.
- On Linux, `time.monotonic()` is fine on any Python version, so the log timestamps are accurate.
- Models and cache clips live in `models/` and `voice/cache/` (both gitignored). Copy them to the judged machine or run the setup commands there before going offline.

## Known limits

- The quality score in `voice.quality` is a simplified mel-cepstral distance. It is only valid for relative comparisons.
- Composed time/date answers depend on Brain's exact wording in `brain/router.py`. If it changes, update the patterns in `voice/cache.py`; unmatched text falls back to synthesis.
- Echo cancellation is not built. Use headphones or the half-duplex switch if Pecko hears itself.
- Licenses: Piper (piper1-gpl) is GPL-3, the lessac voice has its own dataset license, and espeak-ng is GPL-3.
