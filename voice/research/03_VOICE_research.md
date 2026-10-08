# VOICE research: <your name>
Role 3 (Voice). Owns TTS, phrase streaming, low-latency playback, barge-in, and the pre-synthesized cache.

**Honesty line.** This is desk research from docs, vendor pages and blogs. **No numbers are measured on our laptop yet.**
- Section 4 gives the exact benchmark and an empty table. It is the first task of the build phase.
- **[verified]** means checked against official docs today.
- **(vendor)** or **(blog)** marks numbers that are not ours.

---

## 0. TL;DR

| Decision | Choice |
|---|---|
| Engine family | **Piper (VITS, ONNX)**. Fastest reasonable-sounding CPU TTS. |
| Runtime | **sherpa-onnx**. It gives one API for Piper, Kokoro, KittenTTS and MMS, sets `num_threads`, and runs on x86, ARM and Android. Fallback runtime: `piper-tts` (OHF-Voice/piper1-gpl). |
| Default voice | `en_US-lessac-medium` (22.05 kHz, ~60 MB). The same speaker exists as `-low`, so every tier and every cached clip is the same voice. |
| Quality option | Kokoro-82M. Only used at the top tier, and only if our A/B shows its first phrase stays inside budget. |
| Latency target (Voice share) | First chunk received → first sound at the speaker: **≤150 ms median, ≤250 ms p90** with Piper. Cached opener: **≤30 ms**. |
| Headline metric | **First audio of the real answer.** Filler audio is reported separately. |
| Contract additions (team must agree) | `turn` id on every message, plus `barge_in`, `cancel`, `playback_state` and `tier` messages (section 8). |

### What Voice does
Brain streams reply text in pieces. Voice:
1. Cleans the text.
2. Cuts it into speakable phrases.
3. Plays a cached clip if one exists, otherwise synthesizes it.
4. Streams the audio to the speaker with no gaps.
5. Stops instantly if the user talks.
6. Logs exactly when the first sound left the speaker.

---

## 1. Top options found

| Engine | Size | CPU speed (source) | Quality | License | Notes |
|---|---|---|---|---|---|
| **Piper** (VITS) | ~60 MB per voice (medium), smaller for low | ~26x real-time on an Intel laptop CPU, ~0.11 s for ~3 s of audio (vendor, TinyTTS comparison table) | Good, slightly mechanical on long text | Engine GPL-3 (piper1-gpl). **Each voice has its own dataset license.** | Real-time on Raspberry Pi 4 (widely reported). Maintained by Open Home Foundation, v1.8.0 Sep 2026. Hindi voices pratham, priyamvada and rohan are available as sherpa-onnx conversions **[verified]**. |
| **Kokoro-82M** (StyleTTS2) | fp32 326 MB, fp16 164 MB, int8 88–114 MB | ~3x real-time on the same laptop (vendor). Kokoro-FastAPI reports ~3.5 s to first output for 200 chars on an older i7 CPU (blog). | Best small open English voice | Apache-2.0 | int8 loses quality: spectral correlation ~0.92 vs fp32 (kokoro-onnx release notes). |
| **KittenTTS nano** | ~10M params | ~17x real-time (vendor) | Decent, 8 preset voices | Apache-2.0 | English only. Packaged in sherpa-onnx as `kitten-nano-en-v0_2-fp16` **[verified]**. A middle-tier candidate. |
| TinyTTS | 1.6M params, 3.4 MB | ~53x real-time (self-reported by the vendor) | Unknown | check | Watch list only. |
| **espeak-ng** (formant) | a few MB | near-zero CPU | Robotic | GPL-3 | Already bundled as Piper's phonemizer. Guaranteed bottom tier. |
| **Meta MMS VITS** (Tamil, Kannada) | ~138 MB per language | Same class as Piper | OK | **CC-BY-NC 4.0** | The only small offline Tamil voice found. sherpa-onnx lists MMS support **[verified]**. |

**Rejected:**
- XTTS-v2, Bark, F5-TTS, Parler / Indic-Parler: each is hundreds of MB to GBs and far too slow on 1–2 CPU cores, so they fail the budget.
- Cloud TTS: fails the pass/fail gate.

## 2. My pick and why

**Piper voices on sherpa-onnx, `en_US-lessac-medium` default.**
1. **Fastest first audio.** Roughly 8x faster than Kokoro on the same CPU (vendor table: 0.11 s vs 0.93 s).
2. **Small RAM.** About 60 MB of model plus the ONNX Runtime, so it fits beside ASR and the LLM inside 2 GB.
3. **Thread control.** sherpa-onnx exposes `num_threads`, which we need when 3 stages share 2 cores. The piper-tts Python API exposes no thread option, so we would have to use OS env vars instead **[verified: API doc shows only `use_cuda` on load]**.
4. **One runtime for everything.** Every tier, every language (Hindi via Piper, Tamil via MMS) and the Pi/phone stretch goal all use the same code path.
5. **One voice everywhere.** The same speaker in low and medium keeps the voice ladder and cache consistent.

**Decision rules after the A/B (pre-agreed so we don't argue later):**
- If Kokoro-int8 or Kokoro-fp32 first-phrase synth is **≤150 ms** on 1 thread under the limit **and** RAM fits, make it T0 and drop Piper-medium to T1. Otherwise Piper-medium stays T0.
- If int8 is **not at least 15% faster** than fp32 on our CPU, ship fp32 and report "int8 slower/no gain on our CPU" as a quantization finding.
- If KittenTTS-nano sounds better than Piper-low at a similar speed, it becomes T1.

## 3. How to install and run

```bash
pip install sherpa-onnx sounddevice numpy soxr rapidfuzz num2words
pip install piper-tts            # fallback runtime

# Download models ONCE into models/ before going offline. Never download at runtime.
cd models
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-lessac-medium.tar.bz2
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-lessac-low.tar.bz2
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-hi_IN-pratham-medium.tar.bz2
for f in *.tar.bz2; do tar xf "$f"; done
# piper-tts way: python3 -m piper.download_voices en_US-lessac-medium    [verified]
```

**sherpa-onnx synth** (field names from sherpa-onnx's Python examples; run once to confirm):
```python
import sherpa_onnx, time
d = "models/vits-piper-en_US-lessac-medium"
tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=f"{d}/en_US-lessac-medium.onnx",
            tokens=f"{d}/tokens.txt",
            data_dir=f"{d}/espeak-ng-data"),
        num_threads=1, provider="cpu"),
    max_num_sentences=1))
for _ in range(2): tts.generate("warm up the engine", sid=0, speed=1.0)   # cold start is slow
t = time.monotonic(); a = tts.generate("Sure, here is a quick answer.", sid=0, speed=1.0)
dt = time.monotonic() - t; dur = len(a.samples) / a.sample_rate
print(f"synth {dt*1000:.0f} ms  audio {dur:.2f}s  RTF {dt/dur:.3f}  sr {a.sample_rate}")
```

**piper-tts fallback** **[verified API]**:
```python
from piper import PiperVoice, SynthesisConfig
voice = PiperVoice.load("models/en_US-lessac-medium.onnx")
cfg = SynthesisConfig(length_scale=1.0, normalize_audio=True)   # length_scale <1 = faster speech
for chunk in voice.synthesize("Sure, here is a quick answer.", syn_config=cfg):
    pcm = chunk.audio_int16_bytes      # also chunk.sample_rate, chunk.sample_width, chunk.sample_channels
```
Threads for this path: set `OMP_NUM_THREADS=1` before import, and verify with `top`.

## 4. Measurement plan (numbers to fill first)

**Benchmark grid:**
- Engines: piper-low, piper-medium, kitten-nano, kokoro-int8, kokoro-fp32.
- Threads: 1 and 2.
- Text: 3, 8 and 20 words.
- Conditions: run under `taskset -c 0`, under `taskset -c 0,1`, and under Spine's real limit **while Brain is generating at the same time**. Contention is the realistic case.
- Repeats: 5 runs each, report median and p90.

| Engine | Thr | Synth ms 8w med/p90 | RTF | Peak RSS | Chunk→sound med/p90 | Notes |
|---|---|---|---|---|---|---|
| piper lessac-medium | 1 | | | | | |
| piper lessac-low | 1 | | | | | |
| kitten nano | 1 | | | | | |
| kokoro int8 | 1 | | | | | |
| kokoro fp32 | 1 | | | | | |

**Timestamps.** All use one shared clock, `time.monotonic()`, in seconds.
- `chunk_recv`, `synth_start`, `synth_end`, `first_audio_out`.
- `first_audio_out` is the moment the first **non-silent** sample reaches the DAC, not the moment we queue it. In the sounddevice callback:
  `t = time.monotonic() + (time_info.outputBufferDacTime - time_info.currentTime)`.
  This removes the device-buffer error. Spine cross-checks with a phone recording.
- Also logged: per-chunk RTF, **underruns** (playback ran dry mid-reply, which means an audible gap), barge-in stop delay, cache hit/miss and layer, voice tier, turn id.

---

## 5. Internal design (what the build file should implement)

```
 Brain chunks ─► [1 Turn filter + seq reorder] ─► [2 Text normalizer] ─► [3 Phrase chunker]
                                                                              │
                         ┌──────────── cache hit ◄── [4 Cache lookup] ◄───────┘
                         │                                │ miss
                         ▼                                ▼
                 [6 PCM ring buffer] ◄──────────── [5 Synth worker thread, ONNX, 1 thread]
                         │
                         ▼
          [7 Audio callback: memcpy only, fades, first-sample timestamp]  ─► speaker
 Control in : barge_in / cancel / tier   Control out: playback_state, logs
```

1. **Turn filter and reorder.** Drop any message whose `turn` is not the current turn. Reorder by `seq`. If a gap lasts more than 300 ms, continue and log it. Skip empty chunks. `last:true` marks the end of the turn.
2. **Normalizer.**
   - Strip markdown, emoji and URLs ("I'll skip the link").
   - Expand numbers with `num2words`, including Indian lakh and crore and ₹.
   - Expand times (3:45 → "three forty-five"), units (km, °C, %) and common abbreviations (Dr., etc.).
   - Never read code or symbols aloud.
3. **Adaptive phrase chunker.**
   - **First phrase:** cut at the first `, . ? ! ;` or after 4–6 words, with a minimum of 2 words. This gives a fast start.
   - **Later phrases:** grow up to one sentence or about 25 words while the audio buffer is more than 300 ms ahead. This gives better prosody and fewer synth calls.
   - If the buffer drops below 150 ms, cut shorter again.
4. **Cache lookup.** Exact hash of the normalized phrase. Layers are in section 7.
5. **Synth worker.** One thread with ONNX `num_threads=1`; ONNX Runtime releases the GIL. It checks the cancel flag before every phrase. Model loading and two warm-up synths happen in `start()`, never lazily.
6. **Ring buffer.**
   - Preallocated int16 at the model's sample rate.
   - Trim silence at both ends of each phrase, then add our own pause: about 100 ms after a comma, about 220 ms after a sentence.
   - Apply a 5–10 ms fade in and out on every phrase.
   - Normalize all clips to one loudness target.
7. **Audio callback.**
   - One `sounddevice.OutputStream`, opened at startup and kept running on silence.
   - `blocksize` 256–512 frames (about 12–23 ms at 22.05 kHz), `latency='low'`.
   - The callback only copies samples: no allocation, no logging, no locks held for long.
   - It stamps `first_audio_out` and counts underruns.

**Stage interface** (follows the Team Brief rule: `start()`, `feed(...)`, `stop()`):
```python
class VoiceStage:
    def start(self):        # load model, warm up, load cache into RAM, open audio stream
        ...
    def feed(self, msg: dict):  # chunk | barge_in | cancel | tier, routed by msg["type"]
        ...
    def stop(self):         # fade out, close stream, flush logs
        ...
    # outputs: log lines {"stage":"voice","event":...,"t":...}, playback_state messages
# Mock mode: python -m voice --mock sentences.txt   (feeds hardcoded chunks, prints chunk→sound latency)
```

---

## 6. Risks and how each is handled

### Latency
| # | Risk | Fix |
|---|---|---|
| L1 | Cold start: the first ONNX run is several times slower. | Load and run 2 dummy synths in `start()`. |
| L2 | Opening the audio device per reply costs 50–200 ms. | Keep one stream open from startup. |
| L3 | Big default audio buffers (Windows MME, PulseAudio). | Small `blocksize`, `latency='low'`. WASAPI on Windows. Check PipeWire/Pulse latency on Linux. Measure, don't assume. |
| L4 | **Bluetooth output adds 150–300 ms.** | Demo on built-in or wired speakers. Put it in the run sheet. |
| L5 | Waiting for a whole sentence before speaking. | Adaptive chunker with a short first phrase. |
| L6 | CPU contention with the LLM on 2 cores. | TTS gets 1 thread. Agree thread budgets with Brain and Spine. TTS gets priority for the first phrase only, since that is the critical path. |
| L7 | Sample-rate mismatch (model 22.05 kHz, device 48 kHz). | Open the stream at the model rate. If that is refused, resample with `soxr`. Pre-resample cache clips at build time. |
| L8 | CPU frequency scaling or battery saver adds variance. | Plug in power and use the performance mode. **State this in the write-up.** |

### Audio quality
| # | Risk | Fix |
|---|---|---|
| Q1 | Gaps between phrases (synth slower than playback). | Buffer-ahead target, underrun logging. Drop a tier if underruns appear. |
| Q2 | Clicks and uneven silences at joins. | Trim, controlled pauses, fades. |
| Q3 | Loudness jumps between cached and live audio. | Same voice and settings for both, one normalization target. |
| Q4 | Very short phrases sound odd. | Minimum 2 words unless the phrase is a known cached opener. |
| Q5 | Symbols, numbers and ₹ read out badly. | Voice-side normalizer, even though Brain promises clean text. |
| Q6 | Speech too slow for the judges. | Piper `length_scale` around 0.9 makes speech slightly faster and also shortens audio. Tune by ear. |

### Protocol and robustness
| # | Risk | Fix |
|---|---|---|
| P1 | Chunks out of order or missing. | Reorder buffer with a 300 ms gap timeout. |
| P2 | Empty or whitespace chunks, or a `last` chunk with no text. | Skip synthesis and treat as end-of-turn. |
| P3 | **Stale chunks play after a barge-in.** | `turn` id; drop anything that does not match the current turn. |
| P4 | Brain dies mid-reply and `last` never arrives. | After 2 s of silence mid-turn, finish what we have and log it. |
| P5 | Engine throws an exception. | Catch per phrase, fall back to the next tier or espeak for that phrase so the user still hears something, and log it. |
| P6 | A runtime download breaks airplane mode. | Models vendored in `models/`. Set `HF_HUB_OFFLINE=1`. Test with network off before every rehearsal. |

### Barge-in and echo
| # | Risk | Fix |
|---|---|---|
| B1 | User talks over us. | On `barge_in`: set the cancel flag, clear the ring buffer, 10 ms fade to zero (no click), skip pending phrases, send `cancel` to Brain. Target stop **<100 ms**, measured and logged. |
| B2 | **The mic hears our speaker and we interrupt ourselves.** This is the most likely live failure. | 1) Send `playback_state` so Ears raises its VAD threshold and requires about 250–300 ms of speech while we play. 2) If time allows, echo cancellation (WebRTC APM or speexdsp bindings) using our playback signal as reference. 3) **`--barge-in off` (half-duplex) switch** for the judged run if it misfires. |

### Resources and platform
| # | Risk | Fix |
|---|---|---|
| R1 | **Quantization trap.** int8 can be slower on CPUs without VNNI, VITS and Kokoro conv-transpose layers do not quantize well in ONNX Runtime, and Kokoro int8 loses quality. | A/B on our CPU using the decision rule in section 2. Report the result either way. It counts toward the 15% quantization score. |
| R2 | RAM: Kokoro fp32 path is ~400–500 MB; Piper ~100–150 MB total. | Piper default. One live TTS model plus the always-loaded tiny bottom tier. Load the next tier between turns. |
| R3 | **No sound inside Docker.** | Ask Spine for host cgroups (`systemd-run --scope -p CPUQuota=200% -p MemoryMax=2G …`), or pass `--device /dev/snd` or the Pulse/PipeWire socket into the container. Test early. |
| R4 | An always-open stream costs idle energy. | Keep the callback trivial. Measure idle CPU with the stream open vs closed and report it. |
| R5 | GIL or heavy callback causes glitches. | Callback only copies; synthesis runs in its own thread. |
| R6 | Licenses. | piper1-gpl is GPL-3, MMS is non-commercial, and some Piper voice datasets are restrictive. Fine for a hackathon; list them in the write-up. |

### Cache
| # | Risk | Fix |
|---|---|---|
| C1 | Fillers look like cheating. | Headline = first audio of the real answer. Fillers get their own column. |
| C2 | A wrong cached answer gets played. | Closed-domain intents only, conservative threshold, false-hit rate measured on the 30 clips. |
| C3 | Cached voice ≠ live voice. | Generate the cache with the exact live voice and settings. Regenerate whenever they change. |

---

## 7. Ideas that could be NEW (20% "what's new")

**1. Cache-first with honest accounting** (the assigned idea). The cache has four layers:

| Layer | What it holds | How it matches |
|---|---|---|
| L1 Fillers | "Mm-hm.", "Let me think." | Played while the LLM thinks, only if the real answer is slow. |
| L2 Openers and stock phrases | "Sure,", "I'm not sure, but", "Sorry, I didn't catch that." | Exact hash of the normalized phrase. |
| L3 Runtime memo | Every phrase we synthesize, in an LRU | Exact hash. Hit rate grows during a session for free. |
| L4 Full intent answers | Greeting, thanks, goodbye, who are you, what can you do, "I can't go online" | `rapidfuzz` on Ears' `final` text against templates. **Skips the LLM entirely**, so latency, energy and the 25% footprint score all improve. |

- **Ablation:** no cache / L1 / L1+L2 / L1–L4.
- **Metrics:** first-audio-any, first-audio-real-answer, hit rate, false-hit rate, energy per turn.
- **Memory:** 22.05 kHz mono int16 ≈ 44 KB/s, so 200 clips × 2 s ≈ 18 MB of RAM.

**2. Composed answers for dynamic facts.** "What time is it?" or "what's the date?" can be answered offline by joining cached word clips ("It's" + "three" + "forty-five" + "PM"). No LLM, no synthesis, and always correct because the clock is local.

**3. Buffer-aware adaptive chunking.** Ablate three ways to cut phrases: fixed sentence, fixed comma, and adaptive. Measure first-audio time, underruns and the number of synth calls.

**4. Speculative opener.** If Brain's first chunk starts with a cached opener, play the clip at once and synthesize only the rest.

## 8. Stretch goals

**Tighter limits: voice ladder.** Switch only between turns, never mid-reply. Spine sends `tier` and Voice logs the switch.

| Tier | Voice | RAM approx. | When |
|---|---|---|---|
| T0 | Piper lessac-medium (Kokoro only if the A/B allows) | ~150 MB | full budget |
| T1 | Piper lessac-low, same speaker, faster | ~100 MB | CPU or RAM pressure |
| T2 | Cache + composed answers; espeak-ng for anything else | ~20 MB | starved |

**Multilingual.**
- **Hindi:** Piper `hi_IN` pratham, priyamvada or rohan (medium) through sherpa-onnx **[verified available]**.
- **Telugu and Malayalam:** `te_IN-maya` and `ml_IN-arjun` appear in a Piper catalog. Verify they load.
- **Tamil and Kannada:** Meta MMS VITS, about 138 MB each, non-commercial license, loaded on demand.
- **Routing:** detect the script of each chunk by Unicode range (Devanagari → hi, Tamil → ta, Latin → en).
- **Known limitation, stated honestly:** romanized Hinglish or Tanglish sounds poor in any of these voices.

**Smaller device.** Piper is real-time on a Raspberry Pi 4. sherpa-onnx has ARM64 Linux and Android builds. On a Pi, use the T1 voice and ALSA directly, and check RAM with all three stages loaded.

## 9. Contract proposal and questions for other roles

**Proposed contract additions** (must be agreed by everyone):
```json
{"type":"chunk","text":"Sure, ","seq":0,"turn":7}
{"type":"barge_in","turn":7,"t":21.40}                     // Ears -> Voice, Brain
{"type":"cancel","turn":7}                                  // Voice/Spine -> Brain
{"type":"playback_state","playing":true,"turn":7,"t":21.02} // Voice -> Ears
{"type":"tier","voice":"T1"}                                // Spine -> Voice
```
Voice log events: `chunk_recv`, `synth_start`, `synth_end`, `first_audio_out`, `underrun`, `cache_hit`, `barge_in_stop`, `tier_switch`.

**Brain:**
- No markdown, lists or emoji, please.
- Send the first chunk at the first comma, even if it is only 3–5 words.
- Share your most common openers and stock replies so I can cache them.
- Can you stop within one token on `cancel`?
- How many threads do you need while I synthesize?

**Ears:**
- Can you emit `barge_in` during playback, with a raised threshold while I play?
- Can you take my playback signal as a reference for echo cancellation?
- Can you flag greeting, thanks and bye intents early?

**Spine:**
- Docker or host cgroups? Audio access depends on it.
- What is the core and thread budget per stage?
- Will you send `tier` to me directly?
- Can you do the phone-recording check of `first_audio_out`?

## 10. Build order and demo run sheet

**Build order:**
1. Mock harness and the latency print. (hour 1)
2. Engine A/B table, including int8 vs fp32.
3. Player: ring buffer, trim, fades, pauses, underrun log.
4. Normalizer.
5. Cache layers L2 and L3, then L4 intents, then L1 fillers, with the hit rate on the 30 clips.
6. Barge-in with measured stop delay, plus the half-duplex switch.
7. Voice ladder T0, T1 and T2 with a tested switch.
8. RAM and CPU under the limit, then the airplane-mode test.

**Demo run sheet (Voice items):**
- Wired or built-in speaker.
- Charger plugged in, performance mode on.
- Network off.
- Models present locally.
- Warm-up done before the judges speak.
- Barge-in mode decided: on, or the half-duplex fallback.
- Volume set so the mic does not pick up the speaker.

## 11. Sources
- OHF-Voice/piper1-gpl Python API doc (`synthesize`, `SynthesisConfig`, `download_voices`): github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md
- Piper TTS review 2026 (maintainer, v1.8.0): promptquorum.com/power-local-llm/piper-tts-review
- TinyTTS CPU comparison table (Piper, Kitten, Kokoro, same laptop; vendor): pypi.org/project/tiny-tts
- kokoro-onnx releases (model sizes, int8 quality loss): github.com/thewh1teagle/kokoro-onnx/releases
- Kokoro-FastAPI (CPU first-output timings; blog-grade): github.com/remsky/Kokoro-FastAPI
- sherpa-onnx TTS docs (Piper, Kokoro, Kitten, MMS support; Python examples): k2-fsa.github.io/sherpa/onnx/tts
- sherpa-onnx Hindi Piper conversions (hi_IN pratham, priyamvada, rohan): HF space model list
- Indic TTS catalog (Piper te/ml voices, MMS Tamil ~138 MB): huggingface.co/remiai3/TTS_MODELS_FOR_APP
- offlinetts.com Kokoro vs Piper vs Kitten comparison (blog)
