# MOBILE: Pecko on an Android phone (target 2)
> Source of truth for the phone track. Shared plan: ../docs/solution.md §4. Contract: ../docs/CONTRACT.md. **Never blocks the laptop.**

**Principle:** same JSONL contract, same Python orchestrator, router and cache. Only the engines and the limit change. The phone runs the laptop's **T2 profile**.

| Stage | Phone engine | Status |
|---|---|---|
| VAD + KWS "hey Pecko" + streaming ASR | sherpa-onnx (streaming Zipformer 20M int8) | Android arm64 + these functions listed in sherpa-onnx docs **[verified docs, not run]** |
| Endpointer | VAD + transcript cues + calibrated timer | same as laptop T2 |
| LLM | llama.cpp built in Termux, Qwen3-0.6B **Q4_0** (ARM-friendly), ctx 512–1024, n_predict 25–40 | Termux build documented for llama-cli; llama-server **[verify]** |
| TTS | sherpa-onnx Piper `lessac-low` + cached clips | **[verify]** on device |
| Audio I/O | Termux PulseAudio mic/speaker **[verify]**; fallback **WAV-in mode** (real-time stream of a recorded request) + playback, labelled | highest risk |

## Spike (45 min, after laptop L1) — go/no-go
1. Termux (from F-Droid): `pkg install git cmake clang python` → build llama.cpp → run Qwen3-0.6B Q4_0 → log prompt and decode tok/s, RSS.
2. `pip install sherpa-onnx` in Termux (else build from source) → streaming ASR on one WAV → log RTF.
3. Try mic capture via PulseAudio. **Go** if 1 and 2 work. Otherwise record what worked as component numbers (still bonus evidence) and stop.

## P1 build (after laptop L4)
- `mobile/run_phone.sh`: start llama-server (or llama-cli bridge), the orchestrator with `--profile phone`.
- Spine-lite telemetry every 1 s: tok/s, ASR RTF, `/sys/class/thermal/thermal_zone*/temp`, `/sys/class/power_supply/battery/{current_now,voltage_now}` if readable (record which are readable on this device).
- Pin to big cores with `taskset` if allowed. Report the SoC, RAM and Android version as **the declared limit**.
- Ladder triggered by **real throttling** (tok/s drop or temperature): shorter ctx/n_predict → cache-first → T3 (no LLM).

## Measure (same harness definitions as laptop)
first-content-audio p50/p90 from WAV-in turns, tok/s, peak RSS, CPU-s/turn, energy only if battery counters are readable (else say "not joules"), and a 10-minute sustained run plotting temperature, tok/s, tier and latency.

## Do not
Root the phone · build a native APK in this window · claim phone numbers that came from the laptop · let phone work delay laptop L4.
