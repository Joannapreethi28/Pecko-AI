# VOICE GOTCHAS (what bit us, why, fix)

## Platform
- **Dev on Windows, judged on Ubuntu.** Windows MME audio adds ~93 ms output latency (measured in the prototype). Never quote Windows latency as the Pecko number; Ubuntu numbers come from Sir Jabin's run.
- **Ubuntu needs `libportaudio2`** for sounddevice. PipeWire/Pulse may add buffer latency: measure `stream.latency` there.
- **Windows `time_info.currentTime` can be 0** (MME), so the DAC-time correction falls back to `monotonic() + stream.latency`.
- **Path has an apostrophe** (`Hacknex'26`): always quote it in shells.

## Engine
- **sherpa-onnx exposes `num_threads` but no `allow_spinning`** for TTS (checked `OfflineTtsModelConfig` fields in 1.13.8). The team rule asks for spinning off: measure idle CPU and report it instead of claiming it is off.
- **Cold start**: first ONNX synth is several times slower → 2 warm-up synths in `start()`.
- **Sample rates differ** (low = 16 kHz, medium/high = 22.05 kHz). The playback stream has one fixed rate → resample the others.
- Quantized packs exist upstream: `-fp16`, `-int8` for low/medium/high. int8 can be **slower** on CPUs without VNNI → benchmark, don't assume (P2).

## Learned in the prototype (still true)
- num2words puts commas inside numbers ("four thousand, five hundred") → strip them, or the chunker cuts mid-number.
- Brain's first-chunk rule (6 words) and Voice's chunker must agree (`>=` not `>`), otherwise Voice waits for the next chunk (+760 ms seen).
- Keep one output stream open from startup (device open costs 50–200 ms). No Bluetooth (+150–300 ms).
- Cache clips must be regenerated whenever voice, speed or post-processing changes.

## Learned in P5
- **Spine's scoring only counts a turn if Voice's events carry specific fields**: `first_audio_out` needs `gen`, `content`, `sustained`; `pcm_ready` needs `seq: 0` and `gen` (`spine/report.py`). Without them every integrated turn is `missing_sustained_content_audio`.
- **A cancelled speculative gen is not a cancelled turn.** Ears' `cancel` killed gen 0, gen 1 played fine, but Voice still reported the turn as cancelled → Spine marked it failed (1/3 scripted cases). Fixed: a new gen clears the earlier cancel; only barge-in kills a whole turn. Caught by `tests/test_voice_spine_integration.py`.
- **Pull before calling a phase done.** The team pushed 7 commits during P5 (Brain v2.1, Spine runtime, logger change); integration bugs only showed up against their real code.
- **"Smallest chunk" is not automatically a gap problem on a fast CPU.** One-word chunks synthesize (~40 ms) far faster than they play (~350 ms), so the buffer never runs dry here. Their real costs are +75 % synthesis CPU and choppy prosody. Always report CPU and listen; gaps alone do not tell the story.
- **Sentence-only chunking breaks with a slow Brain**: first audio doubles and 3/12 turns had audible gaps (1.3 s total) under the slow-Brain profile.
- The README is shared by the team; Voice docs live in `voice/README.md` and the handoff gives Sir Jabin a block to link.

## Learned in P4
- **Unload-first can leave Voice with no voice.** If the target tier and every tier below it fail to load (e.g. espeak-ng missing for T3), the old engine is already gone. Fixed: `_load_tier` reloads the previous tier and logs `tier_load_recovered` (test: `test_unloadable_survival_tier_recovers_previous_voice`).
- **Cached clips must come from the matching voice only.** T3's engine is espeak-ng but it plays lessac-low clips; `AudioCache.build(pack=...)` never synthesizes clips with a different voice, it only counts them as `missing`. Prebuild lessac-low before relying on T3.
- **espeak-ng on Windows needs two admin prompts** (VC++ runtime, then the MSI) via `winget install eSpeak-NG.eSpeak-NG`. Ubuntu: `sudo apt install espeak-ng`. Calling it through the CLI costs ~35–40 ms per phrase (process start included).
- **Long heredoc edit scripts break in Git Bash** (brain/gotcha.md G12/G13). Write the edit script to a file and run it.

## Learned in P2
- **Windows Python 3.12 `time.monotonic()` = GetTickCount64, 15.6 ms resolution** (brain/gotcha.md G8). All P1 Windows timings are ±16 ms. Benchmarks use `time.perf_counter()` (QPC, 0.1 µs). Team standard for the Windows venv is Python 3.13; Ubuntu is fine on any version. `tests/common/test_clock_log.py` fails on 3.12 on purpose.
- **Quantization trap is real on our CPU:** first probe, lessac-medium **int8 = 1215 ms** for 8 words under co-run vs ~125 ms fp32 (≈10× slower). ONNX Runtime's int8 conv/conv-transpose kernels are slow for VITS. Never pick a precision without the bench.
- **Benchmark on battery = garbage.** On battery + Balanced, low-voice synth was 220 ms; on charger 112 ms. bench.py records the power state; never quote a battery number.
- **Hyperthread siblings are not 2 CPUs.** Logical 2,3 = one physical core here (i7-1365U: 2 P-cores with HT + 8 E-cores). bench.py picks two different physical cores ([0,2]); Spine's `AllowedCPUs=2,3` has the same trap.
- **fp16 low/medium packs fail to load** in sherpa-onnx 1.13.8 (ORT type error on /enc_p/Cast_1); high-fp16 loads but is only 7 % faster. Ship fp32.
- **2 ONNX threads is SLOWER under co-run** (low 117 → 266 ms): the second thread fights Brain for the same cores. Voice stays at 1 thread.
- **Cold cache build costs ~10 s per voice** (181 clips). Prebuild both tiers before a demo: `python -m voice.cache --build --pack <pack>`; afterwards load is ~40 ms.
- **Ablations can lie through the test set:** my first cache session reused 8 LLM replies, so the L3 memo looked magical. Use distinct replies and report pass 1 (unseen) as the headline.
- **My first MCD numbers were nonsense** (113 dB): unnormalized DCT on log power plus silent frames. Always sanity-check a metric (identical files = 0, known pairs ranked sensibly) before reporting it.
- **Composed answers depend on Brain's exact wording** (`brain/router.py` time_words/date_words/day_words). If Brain changes them, `voice/cache.py` regexes must change too (unmatched text just falls back to synthesis).
- `common/log.py` exposes a class `EventLog(stage, path)`, not a `log()` function; `voice/vlog.py` wraps it.

## Learned in P1
- **Chunk raw text, normalize each phrase after.** Normalizing per Brain chunk breaks numbers split across chunks. And LLM tokenizers stream digits one by one: "4," at the end of the buffer must not be cut (it may become "4,500").
- **Commit can arrive before the gen's first chunk** (C earlier than Brain's first clause). Voice stores it (`precommit`) and releases the gen on arrival.
- **Metrics after a cancelled gen:** R and chunk→sound must restart from the gen that is actually heard, or the numbers include the discarded guess.
- **The mock plays real audio** through the speakers. Warn people before running it; stop with Ctrl+C or kill the python process.
- Windows MME barge-in "stop" ≈ device buffer (93 ms); the callback itself stops within one block (≤ 23 ms).
