# EARS results (measured on our machine; nothing here is vendor data)
Machine: Windows dev laptop (target platform is Ubuntu; this is a dev-time measurement, not the judged run).
Model: Moonshine Small Streaming (T0), int8 ONNX via moonshine-voice 0.1.5. VAD: Silero (ONNX backend).
Dataset: substitute for the team-voice bake-off -- see `data/clips/SOURCE.md` for why and its limits (read-speech, not spontaneous; `label_method=auto`, not hand-labeled).

## Phase 5: Smart Turn + sherpa KWS wired in (current state)
Both are **built, wired into `ears/stage.py`, and measured** -- no longer deferred.

**Smart Turn** (`ears/backends/turn_smartturn.py`, real `soniqo/Smart-Turn-v3.2-ONNX`, BSD-2):
wired into `_on_pause_start` via `_score_smart_turn()`, replacing the `NEUTRAL_P_DONE=0.5`
default that every earlier number in this file used. `Ears._turn_audio` (a frame deque capped
to the model's 8 s window) feeds it the current turn's raw audio.

**sherpa-onnx KWS** (`ears/backends/kws_sherpa.py`, gigaspeech 3.3M model, Apache 2.0):
wired into `_maybe_check_wake`, now the primary wake-word path (ASR-transcript text match is
the fallback if the model is missing from a checkout). Validated with a **true-positive test**
against the model's own shipped `test_wavs/0.wav` + `test_keywords.txt` ("LIGHT UP" correctly
detected at t=3.648s) -- not just a no-crash smoke test. Measured cost: **1.57 ms/frame** on
this CPU, vs. running the full Moonshine model per frame under the old text-match fallback --
the efficiency win the spec's wake-word section was after.

### Before/after: endpoint delay (same endpointer logic, only `p_done` source changed)
| | Clips | `final`s | delay p50 | delay p90 | delay min/max |
|---|---|---|---|---|---|
| **Before** (`NEUTRAL_P_DONE=0.5` default) | 24 | 70 | 320 ms | 320 ms | 320 / 512 ms |
| **After** (real Smart Turn `p_done`) | 8 (different clips) | 48 | **160 ms** | **160 ms** | 160 / 512 ms |

The 320→160 ms drop is a direct, attributable effect: most turns now score `p_done≥0.7`
("confident_done" bin, 150 ms + ~1 frame) instead of landing in the neutral-default "mid" bin
(300 ms). Representative scores from the integration run: mid-sentence pause ("From the
store", incomplete) → **p_done=0.03**; true sentence end ("...her brother Bob.") →
**p_done=0.99**. The model is doing real discriminative work, not returning a constant.

**Do not over-read the WER numbers in this comparison** -- the before/after runs used
different clips (manifest order), and Smart Turn does not touch transcription accuracy at
all, only turn-timing. Any WER difference between the two rows above is sample variance, not
a Smart Turn effect. (After-run WER: mean 0.430, median 0.475, n=8 -- same "not
benchmark-comparable" caveat as below applies.)

### WER vs fixed paragraph transcript (both runs)
**Read this honestly:** WER (0.23-0.88 across both runs) is much worse than Moonshine's vendor
number (7.84% avg) or Svarah's published Whisper-Large figure (9.1%). Expected, not a bug:
speakers read an unrelated fixed paragraph while our endpointer fires `final` mid-sentence at
every natural reading pause, so each `final` is scored against the *whole* paragraph, not the
sub-segment the model actually heard. Conclusion: **these WER numbers are not comparable to a
clean ASR benchmark** -- they confirm the pipeline runs end-to-end on real accented speech,
nothing more.

## Tier switch (measured, `scripts/test_tier_switch.py`, warm model cache)
| Metric | Value |
|---|---|
| T0 (Moonshine Small) load time | **3.831 s** |
| T0 peak RSS during load | 530.8 MB |
| T0→T1 (Moonshine Tiny) switch time | **1.354 s** |
| T0→T1 peak RSS during switch | 571.8 MB |

This supersedes an earlier 101.5 s switch-time measurement that was inflated by a one-time
HuggingFace download happening mid-measurement (said plainly in the prior version of this
file). With a warm cache, the true reload-only cost is ~1.35 s. Both tiers correctly
transcribed real speech from the same clip.

## Idle CPU
Still not captured -- every measurement run so far has been stopped deliberately before
reaching the idle-CPU sampling step in `scripts/measure.py` (each full 33-clip pass takes
multiple hours of wall time on this dev machine; see cumulative run logs in
`data/clips/measure_partial_24of33.log` and `data/clips/measure_smartturn_8clips.log`).
**Resume step:** let one run finish, or isolate just the `idle_cpu_percent()` call in
`scripts/measure.py` to measure it standalone in seconds rather than after the full clip loop.

## Phase 6: spec-compliance audit + gap fixes
A full re-check against every line of `ears/SPEC.md`, both research docs, and `docs/CONTRACT.md`
(not from memory -- grepped and re-read) found several pieces that were **built but never wired
in**, plus one genuinely missing feature. Note: "speaker verification gate" was asked about and
does **not** appear anywhere in our specs (checked `ears/`, `docs/`, the archived v1 plan, and
the official rules doc) -- not implemented, since it isn't a requirement, and adding an
authentication feature nobody asked for isn't a good use of the remaining time. What *is*
spec'd and was fixed this pass:

| Gap found | Where it was specified | Fix |
|---|---|---|
| Noise-adaptive VAD threshold ("0.6 in noise") never existed -- only 0.5/0.8 | `research/01_EARS_research_v2.md` §4 | `ears/noise.py`: EWMA noise-floor estimator, applied only while IDLE, deferring to O9's 0.8 during playback |
| `PreRollBuffer` was built (`audio_io.py`) but never called from `stage.py` | §4 "300-500ms pre-roll ring buffer" | Wired into `_begin_utterance`: pre-roll + arming-buffer audio is fed to the ASR so the first word's attack isn't clipped |
| No debounce before arming -- any single VAD 'start' frame began a turn | §4 "~150ms speech before arming ASR" | New `ARMING` state: promotes to `LISTENING` only after `MIN_SPEECH_MS` of unbroken speech; a VAD 'end' before that discards it as a noise blip |
| `MoonshineASR.set_keyterms()` (hotword decoder bias) existed but was never called | §6 "hotword biasing" (O10) | `Ears.start()` now calls `self.asr.set_keyterms(HOTWORDS)` |
| `contract.intent_hint()` builder existed but nothing ever emitted it | `docs/CONTRACT.md`, stretch goal "cached TTS" | `_maybe_emit_intent_hint()`: fires once per turn on a partial matching a common opener (`ears/config.py: INTENT_OPENERS`) |
| `docs/CONTRACT.md`'s required `asr_final` log event was missing (only `t_eos`/`endpoint` existed) | `docs/CONTRACT.md` "Required events" | Added in `_finalize()` |

Verified with a real end-to-end run after the changes (not just compiling): 9 `final`s, 9
`tentative_final`s, 27 `partial`s on one clip, zero errors; 14/14 unit tests pass (2 new, for
the noise-floor estimator). The noise RMS threshold (0.02) was sanity-checked against this
clip's actual measured silence floor (~0.002-0.003) -- an order of magnitude of headroom, a
defensible starting value, still **not calibrated against a real noisy room**.

## Phase 7: everything Phase 6 listed as "still not done" -- now done
Each item below was genuinely missing at the end of Phase 6. All five are now built, wired, and
measured on this machine -- not claimed without a real run backing the number.

**Live mic test** (`ears/audio_io.open_mic_stream`, previously never exercised): a real
3-second capture through the actual `Ears.feed()` pipeline on this laptop's mic. 64 frames
captured, VAD correctly fired on ambient room sound (the resulting partials are garbled --
expected, it's room noise/non-matching speech, not a bug). Real bonus finding: **this room's
ambient RMS is ~0.052**, well above the 0.02 noise-tier threshold -- the first real-world data
point for calibrating `NOISE_RMS_THRESHOLD`, which was a synthetic guess until now.

**False-cutoff count** (`scripts/measure.py`): added as a dangling-word proxy (no hand-labeled
ground truth exists for this substitute dataset -- see `data/clips/SOURCE.md` -- so this
counts turns where `final` fired despite the endpointer's own incompleteness signal, not a
true measured cutoff rate). Printed alongside WER in every `measure.py` run now.

**Formal ablation table** (`scripts/ablation.py`, new): fixed-800ms vs fixed-400ms vs fusion
(as shipped, includes O1+O2 since those run unconditionally in "fusion" mode -- this doesn't
decompose into `SPEC.md`'s more granular D/E/F rows separately, said plainly). Time-boxed to 3
clips trimmed to their first 10s each (full-length x 3-mode would take hours at this model's
decode cost). Real, reproducible result, saved in `data/clips/ablation_result.log`:

| Config | `final`s | delay p50 | delay p90 | suspected cutoffs | WER mean |
|---|---|---|---|---|---|
| fixed_800 | 0 | n/a | n/a | 0 | n/a |
| fixed_400 | 0 | n/a | n/a | 0 | n/a |
| fusion | 6 | 160 ms | 160 ms | 0 | 0.905 |

Not a bug (verified by tracing the state machine): in 10s of continuous read-speech, natural
inter-clause pauses mostly fall short of the ~600-1000ms a fixed timer needs (200ms VAD
hangover + 400-800ms fixed wait), so **the fixed baselines complete zero turns** in that
window while fusion's 160ms confident-done threshold completes 6. This is itself a legitimate
ablation finding in fusion's favor, not something to paper over.

**T2 real engine** (`ears/backends/asr_zipformer.py`, sherpa-onnx streaming Zipformer 20M,
`sherpa-onnx-streaming-zipformer-en-20M-2023-02-17`, Apache 2.0): loads in **0.93s** (vs
Moonshine Small's 3.8s) and decodes 8s of audio in **0.28s** -- genuinely lighter, as a
"Starved" tier should be. `set_tier(2)` swaps the whole ASR backend; verified end-to-end (7
`final`s on a real clip). **Real, measured limitation, not a wrapper bug** (traced via
`is_ready()`/`input_finished()` behavior): this specific compact model (`decode-chunk-len 32`,
downsampling factor up to 8) needs **roughly 2.5-4s of accumulated audio before it can produce
any output at all**, even at `finish()`. Short utterances under that length come back as empty
text -- turns 3-7 in one test run were exactly this case. Worth flagging to whoever tunes T2's
real-world trigger conditions: this engine is not a safe drop-in for short-utterance-heavy
conversations.

**T3 real engine** (`ears/backends/asr_vosk.py` + `ears/backends/vad_webrtc.py`, Vosk
`vosk-model-small-en-in-0.4` + WebRTC VAD mode 2): both load in **<1s**. `webrtcvad` needed the
`webrtcvad-wheels` package instead (the original `webrtcvad` needs a C++ compiler this machine
doesn't have -- said plainly, not silently substituted). WebRTC VAD only accepts 10/20/30ms
frames, not our pipeline's 32ms -- each call uses the first 20ms and drops the trailing 12ms, a
deliberate approximation. `set_tier(3)` swaps both ASR and VAD backends; verified end-to-end (3
`final`s on a real clip, reasonable transcription quality, no empty-text issue unlike T2).
Known simplification: T3's wake path still tries KWS first rather than being push-to-talk-only
as the spec's T3 row implies.

**Multilingual stretch** (Hindi): `vosk-model-small-hi-0.22` downloaded and load-tested
(1.1s). **No Hindi audio exists anywhere in our dataset** (every clip is English speech, just
by speakers whose native language is Hindi/Tamil/etc. -- see `data/clips/SOURCE.md`), so this
confirms the model loads and is architecturally ready, nothing more. **No Hindi WER is
claimed or measurable** without real Hindi audio -- said plainly rather than faked.

## What's built vs. deferred (honesty on scope, 2-hour build window)
| Piece | Status |
|---|---|
| VAD | Silero only, **not bake-off-verified** against TEN VAD (spec wanted both) |
| Streaming ASR | Moonshine Small/Tiny, **not bake-off-verified** against sherpa Zipformer |
| Wake word | **sherpa-onnx KWS, wired and validated** (see above); ASR-text match kept as a fallback |
| Fusion endpointer | Silence + dangling-word + sentence-complete heuristic + **real Smart Turn p(done), wired and measured** (see above) |
| O1-O10 optimizations | O1 (speculative finish), O2 (real Smart Turn), O4 (warmup), O5 (capture timestamps), O6 (adaptive pause cap), O7 (partial throttle), O9 (barge-in gating + noise-tier VAD threshold), O10 (decoder keyterm bias **and** post-hoc normalize+hotwords) all implemented. O3 (spinning off) applied to Silero's and Smart Turn's ONNX sessions; **not exposed** by moonshine-voice's native wrapper or sherpa-onnx's KWS Python API (checked, said honestly both times). O8 (resample) implemented in `audio_io.py`, not separately measured. |
| Pre-roll + arming debounce | **Built and wired** (Phase 6): 400 ms pre-roll fed on wake, ~150 ms sustained-speech debounce before a turn starts |
| Noise floor -> adaptive VAD threshold | **Built and wired** (Phase 6): `ears/noise.py`, 0.5/0.6/0.8 tiers, **not calibrated** against a real noisy room |
| Cached-TTS `intent_hint` | **Built and wired** (Phase 6): fires on common openers (`ears/config.py: INTENT_OPENERS`) |
| 30-clip team bake-off | Replaced by a public dataset substitute (GMU Speech Accent Archive), 24-33 of 33 clips processed across runs -- see `data/clips/SOURCE.md` |
| Barge-in (O9) live test | Logic implemented in `stage.py` (`on_playback_state`, `_check_barge_in`), **not yet exercised** against a real `playback_state` message since Voice doesn't exist yet in this parallel-build hackathon |
| Live mic capture | **Done** (Phase 7): real 3s capture through the full pipeline, confirmed working |
| False-cutoff proxy count | **Done** (Phase 7): dangling-word heuristic in `scripts/measure.py`, not a hand-labeled rate |
| Formal ablation table | **Done** (Phase 7): `scripts/ablation.py`, 3 trimmed clips, real fixed-800/fixed-400/fusion comparison |
| T2 real engine (Zipformer) | **Done** (Phase 7): wired, measured, with a genuine documented limitation (needs ~2.5-4s of audio for any output) |
| T3 real engine (Vosk+WebRTC) | **Done** (Phase 7): wired, measured, works on short utterances unlike T2 |
| Multilingual (Hindi) | **Partially done** (Phase 7): model downloaded and load-tested; **no WER measurable** without real Hindi audio, which doesn't exist in this dataset |

## Resume plan (remaining)
1. Let one `scripts/measure.py` run reach the idle-CPU step (or isolate that call) for the one still-missing number.
2. Full 33-clip pass with Smart Turn+KWS wired, if a faster machine or more time is available (current bottleneck is Moonshine Small's CPU decode cost, ~300-450 CPU-s/clip on this dev laptop -- not an Ears-specific issue, worth flagging to whoever profiles the shared CPU budget).
3. Barge-in live test once Voice's `playback_state` message exists (cross-role dependency, not blocked on Ears).
4. The VAD/ASR bake-offs the original spec called for, if time allows before submission -- current picks are "per the research doc's recommendation," not bake-off-verified.
5. If real Hindi (or Tamil/other Indic) speech audio becomes available, measure actual multilingual WER against `vosk-model-small-hi-0.22` (already downloaded, in `models/vosk_hindi/`).
6. T2's short-utterance empty-output limitation needs a product decision: either accept it for T2 (document to Spine/judges), gate T2 to only activate on longer turns, or swap in a different compact ASR model if time allows.
7. A real cgroup-constrained run on Ubuntu (this has all been dev-measured on Windows) to get the numbers that actually count for judging.
