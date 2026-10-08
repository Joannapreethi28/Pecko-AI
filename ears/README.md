# Ears: Pecko's listening stage

Ears turns mic audio into one `final` text message per turn. The moment it sends that message is the biggest latency number the team controls — Brain and Voice can't start before it. Four jobs: wake word, VAD, streaming ASR, end-of-turn decision. Everything runs offline on the CPU.

Owner: Reshma. Contract: `docs/CONTRACT.md` (v2). Build spec: `ears/SPEC.md`. Team-facing status + full measured numbers: `ears/RESULTS.md`.

## How it works

```text
mic 16k ─► pre-roll ring buffer (400ms) ─► Silero VAD (torch-free ONNX port) ─► ARMING (≥150ms debounce) ─► LISTENING
              │ (noise-floor EWMA sets VAD threshold: 0.5 / 0.6 noisy / 0.8 while Voice plays)
LISTENING ─► streaming ASR (tier-selected: Moonshine/Zipformer/Vosk) ─► sherpa KWS wake check ─► partial (stable prefix, O7-throttled)
         ─► VAD silence (true t_eos from the VAD end sample) ─► PAUSED ─► Smart Turn p(done) + ASR speculative finish (O1+O2)
         ─► fusion endpointer (evidence bins → calibrated threshold) ─► tentative_final / final
         ─► FOLLOWUP (~8s window) ─► IDLE
```

- **Wake word**: sherpa-onnx KWS ("hey Pecko", any phrase, no retraining) is primary; falls back to a fuzzy regex match against the ASR's own transcript if the model isn't on this checkout. `push_to_talk()` force-arms regardless; `disable_wake()` (CLI: `--no-wake`) arms every turn with no phrase needed — the real-voice/VM-mic live demo runs this way because the KWS model never fired on real (non-synthetic) speech.
- **Fusion endpointer**: a calibrated-threshold lookup (not one fixed timer) keyed on Smart Turn's real `p(done)`, a dangling-word check, and sentence-completeness — plus O6's per-speaker adaptive pause cap. Confident turns fire at ~160ms; uncertain ones wait up to a 1.2s adaptive cap. The ASR stream finalizes once, at pause start (not again at the deadline).
- **Tier ladder**: the constructor builds the requested tier's backends directly — T0/T1 Moonshine Small/Tiny, T2 sherpa Zipformer, T3 Vosk + WebRTC VAD — instead of always loading Moonshine first and discarding it, which used to inflate T2/T3 startup RAM for nothing. Zipformer's `finish()` now pads ~0.66s of tail silence (the streaming encoder otherwise drops the last word on short utterances — sherpa-onnx's own examples do the same). `set_tier(n)` swaps backends between turns.
- **Safety**: every heavy backend (Smart Turn, KWS) loads best-effort — missing model weights degrade to a documented fallback (neutral `p_done`, ASR-text wake match) instead of crashing.

## Setup

Python 3.12+, Windows (dev) or Ubuntu (judged).

```bash
pip install -r requirements.txt
```

First run of `MoonshineASR` downloads ONNX weights from Hugging Face (one-time, cached after). Test clips are already provided in `data/clips/` (33 real WAVs + `MANIFEST.csv` — see `data/clips/SOURCE.md` for why this dataset, not the original team-voice plan). Model weights for Smart Turn, sherpa KWS, Zipformer, and Vosk live in `models/` (gitignored) — re-download via the fetch steps noted in `ears/RESULTS.md` if missing.

## Run

| Command | What it does |
|---|---|
| `python -m ears.mock data/clips/hindi10.wav --push-to-talk --fast` | Standalone mock: WAV in, pure contract JSONL on stdout, diagnostics on stderr |
| `python -m ears.mock --mic --push-to-talk` | Live microphone, real-time |
| `python scripts/measure.py` | WER + endpoint-delay + false-cutoff proxy + peak RSS + idle CPU over the clip set |
| `python scripts/ablation.py` | Fixed-800ms vs fixed-400ms vs fusion endpointer, real measured comparison |
| `python scripts/test_tier_switch.py` | Tier-switch timing + peak RSS, sanity-checks each tier transcribes |
| `python -m pytest tests/test_ears_contract.py -q` | Unit tests for the endpointer, normalizer, noise estimator, contract shapes |

`--push-to-talk` force-arms immediately (the substitute dataset clips don't say "hey pecko"); `--fast` uses a virtual clock instead of real-time pacing; `--tier N` selects T0-T3.

Use it from code:

```python
from ears.stage import Ears
e = Ears(tier=0)
e.start()
e.push_to_talk()
e.feed(frame, t_capture)   # frame: 512 samples @16kHz float32, called per audio-callback chunk
```

Diagnostic events go to stderr via `common.log.EventLog` in the contract format: `ready`, `wake_detected`, `t_eos`, `smart_turn_score`, `asr_final`, `endpoint`, `tier_switch`, `noise_tier_changed`, `barge_in`.

## Results so far

Two different evidence trails exist — my own isolated Ears measurements (Windows dev laptop, no cgroup, full detail + caveats in `ears/RESULTS.md`), and the team's end-to-end integrated run (VirtualBox Ubuntu VM, 2 CPU/2 GB cgroup, see root `README.md`'s Results section for the full conditions). Both say the same thing from different angles:

**End-to-end, with Ears in the real loop** (24 paired turns, synthetic Piper-voice questions, `--ears-tier 2`): first audio p50 **835ms** vs B0's 2059ms, p90 1280ms vs 2496ms, Pecko faster on 24/24 pairs, 1.63x less CPU-seconds/turn. On a real voice through the VM mic (not a benchmark, one session): first audio ~1.9-2.3s, mostly the endpointer waiting 1.4-2s — slower than the synthetic numbers, measured and reported as such, not hidden.

**Ears in isolation** (my own runs, pre-integration):
- Endpoint delay p50 160ms with real Smart Turn `p(done)` wired in (vs 320ms with a neutral default) — a direct, attributable improvement.
- Ablation: in 10s of continuous speech, fixed-800ms/fixed-400ms silence timers completed **zero** turns while the fusion endpointer completed 6.
- Wake word: sherpa KWS validated with a true-positive test, 1.57ms/frame.
- WER 0.23-0.88 across runs — not comparable to a clean ASR benchmark (see "Known limits"), but confirms the pipeline runs on real accented speech.

## Known limits

- **No hand-labeled ground truth.** The original plan called for a 30-clip team-voice bake-off; the build window made that impossible, so a public dataset substitute (GMU Speech Accent Archive, CC BY-NC-SA 4.0) stands in for my own measurements. It's read-speech, not spontaneous conversation — `data/clips/SOURCE.md` has the full reasoning.
- **No VAD/ASR bake-off.** Silero VAD and Moonshine were picked directly from the research doc's recommendation, not measured against TEN VAD / sherpa Zipformer head-to-head.
- **sherpa KWS never fired on real voice** through the VM mic — the live demo runs `--no-wake` instead. Works on synthetic Piper-voice audio.
- **T2's Zipformer engine needed ~2.5-4s of audio before producing any output** in my own earlier testing (traced to `decode-chunk-len`/downsampling, not a wrapper bug). A tail-silence pad was since added to fix last-word loss on short utterances — whether that also resolves the zero-output case on very short turns hasn't been re-verified by me.
- **Idle CPU over 60s is not captured** in my own isolated runs — Moonshine Small's decode cost makes a full clip-set run take hours on this dev laptop.
- **Multilingual (Hindi) model loads but has no measured WER** — no Hindi audio exists anywhere in my dataset to test against.
- My own numbers above are dev-time, Windows-laptop, no cgroup. The team's integrated numbers (root `README.md`) are measured on the judged-platform VM under the real cap — check there for anything that needs to be cap-accurate.
