# EARS research v2: On-Device Listening Stack (HNX26EPS08)

Role: **Ears** (wake word, VAD, streaming ASR, end-of-turn)
Version: v2, 8 Oct 2026. v2 adds the optimizations in section 9 (also in `EARS_optimizations.md`).
Honesty note: every number here is from vendor pages or papers unless marked *measured*. Nothing is measured yet. The 30-clip bake-off in the first 2 build hours replaces these figures.

---

## 1. What Ears does

Ears turns mic audio into one `final` text message. **The moment it sends that message is the biggest latency number we control.** Brain and Voice cannot start before it.

Four jobs:
1. **Wake word**: sleep until "hey Pecko" (or push-to-talk).
2. **VAD**: label every 32 ms frame as speech or silence.
3. **Streaming ASR**: turn speech into `partial` text while the user talks.
4. **End-of-turn**: decide "finished" vs "just pausing", then send `final`.

Two timestamps Ears owns:
- `t_eos`: capture time of the last speech frame (true end of speech).
- `t_endpoint`: time `final` is sent. `t_endpoint - t_eos` = **endpoint delay** (pure waiting).

| Segment | Default stack (Whisper + fixed 700-1000 ms silence) | Ears v2 target (estimate) |
|---|---|---|
| Endpoint delay | 700-1000 ms | ~150-250 ms |
| ASR final decode after endpoint | 300-1500 ms (whole clip decoded at the end) | ~0 ms (finished during the pause) |
| **Ears share** | **~1.0-2.5 s** | **~0.15-0.25 s** |

Ears also drives the **energy score**: it is the only stage running 100% of the time.

---

## 2. Workflow: a cascade where each layer wakes the next

```
ALWAYS ON (every 32 ms frame)
  Mic 16 kHz + 400 ms pre-roll -> Energy gate (RMS) -> VAD -> Wake word (sherpa KWS / push-to-talk)
                                                                  |
                                              wake heard + speech starts
                                                                  v
ONLY WHILE ARMED AND SPEAKING
  Streaming ASR (Moonshine Small) -> Smart Turn v3.2 -> Fusion endpointer -> `final` to Brain
          ^                                                   |
          +------------- speech resumes: cancel, keep listening

```

States: `IDLE -> ARMED -> LISTENING -> PAUSED -> (final) -> ARMED (follow-up window ~8 s) -> IDLE`

Threads (2-core budget):
- Audio callback: only copies frames and stamps capture time. No model work.
- One Ears worker thread: VAD, KWS, ASR in sequence, 1 ONNX thread each, spinning OFF.
- One short-lived helper for Smart Turn + speculative ASR finish during a pause (v2).
- Output queue to Brain (JSON lines).

---

## 3. Wake word

**Pick: sherpa-onnx open-vocabulary KWS (gigaspeech 3.3M).** Any phrase in `keywords.txt`, no training. Same runtime as our VAD and fallback ASR. Apache 2.0.

| Option | Custom phrase | Offline, no key | Verdict |
|---|---|---|---|
| sherpa-onnx KWS 3.3M | Any phrase, no retraining | Yes | **Pick** |
| openWakeWord | Pretrained ("hey jarvis"); custom needs ~1 h Colab training | Yes | Backup |
| Porcupine | Typed in their Console | Needs AccessKey | **Rejected** (account required) |
| ASR + string match | Anything | Yes | Rejected (ASR always on burns idle CPU) |

Usage: rare 2+ syllable phrase ("hey Pecko") with 2-3 pronunciation variants; KWS runs only when VAD says speech; ~8 s follow-up window after each reply; **push-to-talk key as demo safety net**. Ignore wake word while Voice is playing (v2).

---

## 4. VAD

**Pick: bake-off TEN VAD vs Silero on our clips; ship whichever flips to "silence" faster.** Both cost < 1 ms per frame.

| VAD | Size | Cost per frame | Notes |
|---|---|---|---|
| Silero v5/v6 | ~2.2 / ~1.2 MB | < 1 ms per 32 ms chunk | MIT; F1 0.806 on CHiME-Home |
| TEN VAD | smaller than Silero (vendor) | ~0.17 ms | Vendor says much faster speech-to-silence transition; in sherpa-onnx |
| WebRTC VAD | < 0.1 M params | < 5 ms | F1 0.708; emergency tier |
| PulseVAD | 2.1k params, 27 KB | 0.73 ms / 200 ms | Too new; Pi tier experiment only |

Settings: 512 samples at 16 kHz; threshold 0.5 (0.6 in noise; 0.8 while Voice plays); ~150 ms speech before arming ASR; VAD min-silence ~200 ms (it only triggers the turn check); 300-500 ms pre-roll ring buffer.

---

## 5. End-of-turn: the fusion endpointer (our main idea)

**Pick: Smart Turn v3.2 int8** (8 MB, raw audio, ~37-65 ms CPU, 23 languages, BSD-2, 93% on its 1,000-clip test set), fused with silence length and transcript cues.

| Detector | Input | RAM | Verdict |
|---|---|---|---|
| Smart Turn v3.2 | Audio | 8 MB | **Pick** |
| LiveKit turn detector | Text | ~400 MB | Only if 4 GB budget |
| Namo turn detector | Text | ~400 MB | Same |
| Parakeet-EOU-120M | Audio inside ASR | ~232 MB | 640 ms chunks, too slow; watch only |
| Fixed silence timer | VAD | 0 | The baseline we beat |

Decision (v2 timing):
1. First silent frame: stamp `t_eos`; **start Smart Turn and a speculative ASR finish immediately** (O1, O2).
2. Read transcript cues: dangling word ("and", "the", "of", "um", "so")? complete question?
3. p(done) >= 0.7 and no dangling word -> send `final` at ~150 ms of silence.
4. p(done) 0.4-0.7 -> wait ~300 ms more, re-check.
5. Below 0.4 or dangling word -> wait up to the **adaptive cap** (O6: ~1.5x this speaker's median pause, 0.5-1.2 s).
6. Speech resumes -> discard speculative work, keep listening.

Thresholds are starting values to tune on the 30 clips.

---

## 6. Streaming ASR

**Lead: Moonshine v2 Small Streaming. Challenger: sherpa-onnx streaming Zipformer.** Whisper is the baseline, not a contender (fixed 30 s window, decodes everything after the user stops).

| ASR | Params | Streaming | Avg WER (English) | Latency Linux x86 (vendor) | License |
|---|---|---|---|---|---|
| Moonshine Tiny Streaming | 34M | Yes | 12.00% | 69 ms (237 ms on Pi 5) | MIT |
| **Moonshine Small Streaming** | 123M | Yes | 7.84% | 165 ms | MIT |
| Moonshine Medium Streaming | 245M | Yes | 6.65% | 269 ms | MIT |
| sherpa-onnx streaming Zipformer | 20-66M | Yes | base: 41% on Indian English (Svarah) | RTF ~0.1-0.2 | Apache 2.0 |
| Zipformer fine-tuned Indian English | 66M | Yes (640 ms chunks) | ~28% Svarah (int8) | - | community |
| Parakeet TDT 0.6B int8 | 600M | No | very low | 0.67 GB | rejected (RAM) |
| Vosk small en-in | 36 MB | Yes | 49% NPTEL | very low | last resort |
| Whisper tiny/base | 39/74M | No | tiny ~22% Indian lectures | grows with clip | **baseline** |

**Main risk: Indian accents.** Svarah: Whisper Large 9.1% WER, Medium 11.2%, LibriSpeech-only Zipformer 41%. Moonshine has no published Svarah score, so we measure it.

**Bake-off (first 2 build hours):** Moonshine Tiny, Moonshine Small, sherpa Zipformer on the same 30 clips from all four teammates, pinned to 1 core. Record WER, last word -> final delay, peak RAM. Pick on numbers.

Free tricks: hotword biasing (Coimbatore, Karunya, Chennai, rupees, lakh, crore, assistant name); stable-prefix partials; 1 ONNX thread.

---

## 7. Stack and tier ladder

| Tier | When | VAD | Wake | ASR | End-of-turn | RAM (estimate) |
|---|---|---|---|---|---|---|
| T0 Full | >= 2 cores, >= 2 GB | TEN/Silero | sherpa KWS | Moonshine Small | Smart Turn fusion | ~300-350 MB |
| T1 Tight | ~1 core, ~1.5 GB | same | sherpa KWS | Moonshine Tiny | Smart Turn at pauses | ~150 MB |
| T2 Starved | < 1 core, ~1 GB | same | sherpa KWS | sherpa Zipformer 20M int8 | text cues + 600 ms timer | ~80 MB |
| T3 Survival | worse | WebRTC VAD | push-to-talk | Vosk small en-in | key release | ~60 MB |

Spine calls `set_tier(n)` between turns only. Models load lazily, old tier is freed.

Rejected: Whisper as main ASR (not streaming), Porcupine (key), LiveKit/Namo at T0 (~400 MB), Parakeet 0.6B (0.67 GB, offline), 1B+ streaming models (GPU-oriented).

---

## 8. What makes Ears unique ("what's new")

Headline claim: **"Ears ends the turn sooner than a silence timer while cutting off fewer speakers, and idles at near-zero CPU."**

1. **Fusion endpointer**: prosody (Smart Turn) + silence + transcript cues, adaptive wait.
2. **Speculative endpoint**: send `tentative_final` early so Brain starts; `cancel` if speech resumes. Needs agreement with Brain and Spine:
   ```json
   {"type":"tentative_final","text":"what is the weather like","t_eos":13.02,"p_done":0.81}
   {"type":"cancel","t":13.25}
   ```
3. **Cascade gating**: RMS gate -> VAD -> KWS -> ASR -> Smart Turn; each wakes the next.
4. **Stable-prefix partials**: optional `stable` field so Brain's early prefill is rarely wasted.
5. **Early intent hints**: `intent_hint` log event when a partial matches a common opener, so Voice preloads a cached clip.
6. **(v2) Per-speaker adaptive pause cap**: adapts to each judge within one or two turns.
7. **(v2) Speculative ASR finish + early Smart Turn**: hides decode and model time inside the pause.

### Ablation table (30 clips, same laptop, same limit; at least 10 clips with mid-sentence pauses)

| Config | Median endpoint delay (ms) | p90 | False cut-offs /30 | Idle CPU (% of 1 core) |
|---|---|---|---|---|
| A. Fixed 800 ms silence | | | | |
| B. Fixed 400 ms silence | | | | |
| C. Smart Turn + 200 ms VAD | | | | |
| D. Fusion endpointer | | | | |
| E. D + O1 + O2 (speculative finish, early Smart Turn) | | | | |
| F. E + O6 (adaptive pause cap) | | | | |
| G. E + speculative endpoint (delay seen by Brain) | | | | |
| H. Cascade gating off (always-on ASR) | | | | |
| I. ONNX spinning ON vs OFF (O3) | | | | |

Endpoint delay is measured against a **hand-labelled** last-word time per clip, not VAD's guess.

---

## 9. Optimizations added in v2 (details in `EARS_optimizations.md`)

| # | Optimization | Helps |
|---|---|---|
| O1 | Finish ASR speculatively during the pause | Latency |
| O2 | Start Smart Turn at the first silent frame | Latency |
| O3 | ONNX Runtime thread spinning OFF, 1 thread per session | Energy |
| O4 | Warm up all models at startup | First-turn latency |
| O5 | Stamp times at audio capture | Honest numbers |
| O6 | Per-speaker adaptive pause cap | Fewer cut-offs |
| O7 | Throttle partials (on change, max ~1 per 150 ms) | CPU, Brain load |
| O8 | Cheap 48 -> 16 kHz decimation | CPU |
| O9 | Echo-safe barge-in (headphones, higher VAD threshold during playback) | Robustness |
| O10 | Normalised text + Indian hotwords | Accuracy |

ONNX Runtime settings for every Ears session:
```python
so = ort.SessionOptions()
so.intra_op_num_threads = 1
so.inter_op_num_threads = 1
so.add_session_config_entry("session.intra_op.allow_spinning", "0")
so.add_session_config_entry("session.inter_op.allow_spinning", "0")
```

---

## 10. Stretch goals

**Multilingual.**
| Language | Option | Size | Streaming | Accuracy |
|---|---|---|---|---|
| Hindi | Vosk small hi 0.22 | 42 MB | Yes | 20.89% WER (IITM), 24.72% (MUCS) |
| Hindi, Tamil + 20 more | IndicConformer 600M int8 | ~0.6B | No | WER unchanged after int8; CPU ~0.29x audio length |
| 8 Indic languages | IndicConformer CTC int8 for sherpa-onnx | ~140 MB each | No | not reported |

- One wake phrase per language in the KWS file; the wake word selects the ASR. No language-ID model needed.
- Check whether Smart Turn's 23 languages include Hindi/Tamil; if not, use text cues + timer there.
- Report Hindi/Tamil latency separately; they are slower (not streaming).

**Smaller device.** All ONNX with ARM builds; Pi tier = Moonshine Tiny (237 ms on Pi 5). No PyTorch/CUDA at runtime; audio via `sounddevice`.

**Tighter limits.** Tier ladder + `set_tier(n)`.

**Cached TTS.** Early `intent_hint` + normalised final text for fast cache lookup.

---

## 11. Install and code

Run online first, then rehearse in airplane mode. Commands are from project docs, not yet run by me.

```bash
python -m venv .venv && source .venv/bin/activate
pip install numpy scipy sounddevice psutil jiwer onnxruntime sherpa-onnx silero-vad moonshine-voice
pip install -U git+https://github.com/TEN-framework/ten-vad.git
moonshine-voice mic --language en          # smoke test
curl -SL -O https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2
tar xf sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2
huggingface-cli download pipecat-ai/smart-turn-v3 --local-dir models/smart-turn
```

Skeleton (start / feed / stop contract, v2 pause handling):

```python
class Ears:
    """IDLE -> ARMED -> LISTENING -> PAUSED -> ARMED"""
    def __init__(self, out_queue, clock, tier=0):
        self.out, self.clock = out_queue, clock
        self.vad, self.kws = load_vad(), load_kws()
        self.asr, self.turn = load_asr(tier), load_smart_turn()
        self.ring = PreRollBuffer(ms=400)
        self.state = "IDLE"
        self.warm_up()                                   # O4

    def start(self): self.mic = open_stream(self.on_audio)

    def on_audio(self, frame):                           # audio callback: copy + stamp only (O5)
        self.inbox.put((frame, self.clock()))

    def feed(self, frame, t_cap):                        # worker thread, 512 samples @16 kHz
        self.ring.push(frame)
        speech = self.vad(frame)
        if self.state == "IDLE":
            if speech and self.kws(frame): self.state = "ARMED"
            return
        if speech:
            if self.state == "PAUSED": self.cancel_speculation()
            if self.state not in ("LISTENING",): self.asr.begin(self.ring.drain())
            self.state, self.t_last = "LISTENING", t_cap + 0.032
            self.maybe_emit_partial(self.asr.accept(frame))   # O7 throttle
        elif self.state == "LISTENING":
            self.state = "PAUSED"
            self.speculate(t_eos=self.t_last)            # O1 + O2: ASR finish + Smart Turn now
        elif self.state == "PAUSED":
            self.decide_end(now=t_cap)                   # fusion + adaptive cap (O6)

    def stop(self): self.mic.close()
```

Measurement:
| Metric | How |
|---|---|
| Endpoint delay | `t_endpoint` - hand-labelled last-word time |
| WER | `jiwer` on 30 clips, lowercase, no punctuation |
| False cut-offs | `final` sent while labelled speech remains |
| Idle CPU | 60 s silence, `psutil` process CPU % |
| Peak RAM | max RSS over the 30-clip run |

WAV mock must feed frames at real-time speed (32 ms per frame).

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Indian-accent errors | Bake-off on our voices; hotwords; Small not Tiny at T0 |
| Noisy hall | Higher VAD threshold; push-to-talk fallback |
| Hearing our own TTS | Headphones; VAD 0.8 + 250 ms during playback; ignore wake word |
| Smart Turn wrong on long pauses | Adaptive cap, dangling-word rule, re-check on resume |
| CPU fight with Brain | 1 thread, spinning off, core pinning by Spine |
| Slow first request | Warm-up at startup |
| Downloads at venue | Pre-download; airplane-mode rehearsal |
| Mic at 44.1/48 kHz | Resample once at capture |
| Vendor numbers wrong on our laptop | Replace every figure with measurements in hour 1-2 |

---

## 13. Questions for other roles

- **Brain:** accept `tentative_final` + `cancel`? Want the `stable` field? Partial rate?
- **Voice:** which 10-20 openers trigger `intent_hint`? Barge-in as log event or direct call? Can you tell Ears when playback starts/stops (needed for O9)?
- **Spine:** declared limit (2 cores / 2 GB?), which core Ears gets, `set_tier` triggers, shared clock, 30-clip recording session with labelled pauses.

---

## 14. Research return (Team Brief template)

```
# EARS research: <your name>
## 1. Top 3 options
- Moonshine v2 Small Streaming: 123M, 7.84% avg WER, 165 ms Linux x86 (vendor), MIT
- sherpa-onnx (KWS + VAD + streaming Zipformer), Apache 2.0
- Smart Turn v3.2 int8: 8 MB, ~37-65 ms CPU (vendor), BSD-2
## 2. Pick
VAD -> sherpa KWS -> Moonshine Small Streaming -> Smart Turn fusion endpointer.
Rejected: Whisper (not streaming), Porcupine (key), text turn models (~400 MB), Parakeet 0.6B (RAM).
## 3. Install: section 11
## 4. Measured: none yet; 30-clip bake-off in hour 1-2
## 5. Risks: Indian-accent WER, hall noise, TTS echo, CPU contention, offline downloads
## 6. NEW idea: fusion endpointer + speculative ASR finish + adaptive per-speaker cap
   + tentative_final for Brain; ablation table in section 8
## 7. Stretch: Hindi (Vosk 42 MB), Tamil (IndicConformer, offline), wake phrase picks language,
   Pi = Moonshine Tiny, tiers T0-T3, intent_hint for cached TTS
## 8. Questions: section 13
```

---

## Sources

- Moonshine: https://github.com/moonshine-ai/moonshine
- Moonshine vs Whisper table: https://moonshine-voice.readthedocs.io/en/latest/moonshine-vs-whisper/
- Moonshine v2 paper: https://arxiv.org/abs/2602.12241
- Smart Turn: https://github.com/pipecat-ai/smart-turn
- Smart Turn v3.2 ONNX numbers: https://huggingface.co/soniqo/Smart-Turn-v3.2-ONNX
- Pipecat Smart Turn guide: https://docs.pipecat.ai/pipecat-cloud/guides/smart-turn
- LiveKit turn detector: https://pypi.org/project/livekit-plugins-turn-detector
- Namo turn detector: https://pypi.org/project/livekit-plugins-namo-turn-detector/
- TEN VAD: https://github.com/TEN-framework/ten-vad
- TEN VAD LiveKit plugin: https://pypi.org/project/livekit-plugins-tenvad/
- Silero VAD timing: https://voiceclean.readthedocs.io/en/latest/api/vad/
- PulseVAD: https://pypi.org/project/pulsevad/0.1.1/
- VAD demo (WASPAA 2025): https://www.huggingface.co/spaces/gbibbo/vad_demo/blob/main/README.md
- sherpa-onnx KWS: https://k2-fsa.github.io/sherpa/onnx/kws
- sherpa streaming Zipformer models: https://k2-fsa.github.io/sherpa/ncnn/pretrained_models/zipformer-transucer-models.html
- openWakeWord: https://awesome.ecosyste.ms/projects/github.com%2Fdscripka%2FopenWakeWord
- Porcupine: https://picovoice.ai/blog/porcupine-wake-word-engine-v1-8-feature-tour/
- Svarah: https://arxiv.org/pdf/2305.15760
- Indian-English Zipformer: https://huggingface.co/Akshatkasera007/STT-streaming-zipformer-indian-en
- Parakeet runtimes: https://huggingface.co/suryatmodulus/parakeet-redux
- Parakeet-EOU-120M: https://soniqo.audio/guides/parakeet
- Vosk models: https://alphacephei.com/vosk/models
- IndicConformer int8: https://huggingface.co/hazardscarn10/indic-conformer-600m-int8
- IndicConformer CTC for sherpa-onnx: https://huggingface.co/mobilebytesensei/betterflow-indicconformer-ctc
