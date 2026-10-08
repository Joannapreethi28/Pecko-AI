# CONTRACT v2 + TIER LADDER (frozen; change only with all four agreeing)
> Extracted verbatim from docs/solution.md §4 and §7.

All messages are one JSON object per line. All times are `time.monotonic()` seconds (same clock in every process on this machine). Every message carries `turn`. Brain output also carries `gen` (generation id), so stale output after a cancel is dropped.

**Ears → Brain**
```json
{"type":"partial","turn":7,"text":"what is the capital of","stable":"what is the capital","t":12.31}
{"type":"tentative_final","turn":7,"text":"what is the capital of france","t_eos":13.02,"p_done":0.81}
{"type":"final","turn":7,"text":"What is the capital of France?","norm":"what is the capital of france","t_eos":13.02,"t_endpoint":13.20}
{"type":"cancel","turn":7,"t":13.25}
```
- `stable` = words agreed by two consecutive partials. Brain prefills only `stable`.
- `tentative_final` lets Brain prefill the whole candidate early. **Nothing audible happens before `final`.**
- `cancel` = user kept talking after a `tentative_final`. Brain drops speculative state.

**Ears → Voice, Brain** · `{"type":"barge_in","turn":7,"t":21.40}`
**Ears → Voice (log hint)** · `{"type":"intent_hint","turn":7,"intent":"greeting","t":12.40}` (Voice may preload the clip)

**Brain → Voice**
```json
{"type":"chunk","turn":7,"gen":1,"seq":0,"text":"Paris is the capital, "}
{"type":"chunk","turn":7,"gen":1,"seq":1,"text":"and its largest city.","last":true}
{"type":"cached","turn":7,"gen":1,"clip":"who_are_you","last":true}
```
**Voice → Ears, Spine** · `{"type":"playback_state","turn":7,"playing":true,"t":21.02}`
**Voice/Spine → Brain** · `{"type":"cancel","turn":7,"gen":1}`
**Spine → all** · `{"type":"tier","tier":1}` (applied **between turns only**; each stage maps the number to its own ladder in §7)

**Log line (every stage, Spine reads):** `{"stage":"brain","event":"first_token","turn":7,"t":13.41,"extra":{}}`

Required events: Ears `t_eos`, `endpoint`, `asr_final`; Brain `prompt_ready`, `first_token`, `first_chunk`, `cache_hit`; Voice `chunk_recv`, `synth_start`, `synth_end`, `first_audio_out`, `underrun`, `barge_in_stop`; Spine `tier_switch`, `pressure`.

**Stage interface (all roles):** `start()` (load + warm up, report ready), `feed(msg)`, `stop()`, `set_tier(n)`. Each stage runs standalone with a mock: Ears from a WAV at real-time speed, Brain from typed text, Voice from a sentence file.

## v2.1: hold-and-release (team approval confirmed)

Sir Jabin confirmed all four roles agreed to this extension in the Spine build
chat on 8 Oct 2026. Message shapes and rules below are unchanged.
```json
{"type":"chunk","turn":7,"gen":2,"seq":0,"text":"Paris is the capital, ","held":true}   // Brain → Voice: prepare privately, do not play
{"type":"commit","turn":7,"gen":2,"t":13.21}                                          // Spine → Voice, Brain: final validated, release gen 2
{"type":"cancel","turn":7,"gen":2}                                                     // drop held text/PCM for gen 2
```
Rules: nothing with `held:true` is audible before `commit` for the same `turn` and `gen`. A new `gen` invalidates older ones. Log events: Spine `commit` (= C), Voice `pcm_ready` (= R).

## Tier ladder (Spine sends one number; stages map it)

| Tier | When | Ears | Brain | Voice | Speculation |
|---|---|---|---|---|---|
| **T0 Full** | ≥ 2 CPU, ≥ 2 GB | Moonshine Small + fusion endpointer | bake-off winner, ctx 2048, n_predict 60 | Piper lessac-medium | early prefill on |
| **T1 Tight** | ~1.5 CPU or ~1.5 GB, or PSI high | Moonshine Tiny | smaller model (Qwen3-0.6B / LFM2.5-350M), ctx 1024, n_predict 40 | Piper lessac-low | stable-prefix prefill only |
| **T2 Starved** | ~1 CPU or ~1.25 GB | Zipformer 20M int8, text cues + 600 ms timer | 350M-class, 1 thread, ctx 512, n_predict 25, cache-first threshold lowered | Piper low + cache | off |
| **T3 Survival** | < 1 CPU or < 1 GB, OOM risk | WebRTC VAD, push-to-talk, Vosk small | **no LLM**: cache + composed answers + "I'm in low-power mode" | cache + espeak-ng | off |
| **Phone profile** | Android device | sherpa Zipformer + VAD + text cues + timer | Qwen3-0.6B Q4_0, ctx 512–1024, n_predict 25–40 | Piper low + cache | off until measured |

Load the next tier's models lazily between turns; free the old ones. Measure each switch's time and peak memory (Spine's transition check).
