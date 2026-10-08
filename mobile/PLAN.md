# MOBILE PLAN v3: Pecko as a Flutter Android app (9 Oct, re-planned ~01:40 at Sir Jabin's request)
> Replaces the Termux and Kotlin plans (Termux kept only as fallback F3). Reads with `SPEC.md`, `../docs/solution.md` §4, `../docs/CONTRACT.md`.
> Rules: the phone **never blocks the laptop**; phone work lives only in `mobile/`; all app code is written by us tonight
> (pub packages are libraries = OK; copying an example app as our project = template = **not OK**). Nothing below is measured:
> numbers are [MEASURE] or "estimate".
> **Outdated docs (not edited, this plan wins):** `mobile/SPEC.md` and `mobile/CLAUDE.md` still describe Termux scripts, the Python
> orchestrator `--profile phone` and "do not build a native APK". Sir Jabin overrode that: the phone version is a Flutter app.

## 1. Architecture (decision)
Flutter (Dart) app `mobile/pecko_app`, Android arm64-v8a only, **release build for every measured number** (debug Dart is JIT, slower).
- **Speech: `sherpa_onnx` from pub.dev** (k2-fsa; ships prebuilt Android native libs, so no C++ build by us). One runtime for
  Silero VAD + streaming Zipformer 20M int8 ASR + KWS + Piper/VITS TTS. Pin the version closest to laptop's 1.13.8 (verify on pub.dev).
  Reference examples (read, don't copy), in k2-fsa/sherpa-onnx: `flutter-examples/streaming_asr` and `flutter-examples/tts`
  (Flutter apps), `dart-api-examples/{vad,streaming-asr,keyword-spotter,tts}` (CLI Dart). Names from memory: **verify**.
- **LLM: bundled llama-server (recommended).** From `llama-b11501-bin-android-arm64.tar.gz` (handoff_brain.md). Android 10+ forbids
  executing files from app data, so ship it as `android/app/src/main/jniLibs/arm64-v8a/libllama_server.so` (+ the tarball's
  `libllama.so`, `libggml*.so`), set `packaging { jniLibs { useLegacyPackaging = true } }` in `android/app/build.gradle(.kts)` so Android
  extracts them, get `nativeLibraryDir` through a ~10-line `MethodChannel` in `MainActivity.kt`, then from Dart
  `Process.start("$dir/libllama_server.so", [...], environment: {"LD_LIBRARY_PATH": dir})`. Needs `INTERNET` permission even for
  `127.0.0.1` (fine in airplane mode). Dart `http` streams `POST /completion` exactly like `brain/llama_client.py` (`stream:true`,
  `cache_prompt:true`, `n_predict`, same system prompt). Why this over FFI: same server + flags as the laptop baseline, no C++ glue.
- **LLM fallback (only if exec fails in the spike):** a Flutter llama.cpp FFI package: `llama_cpp_dart` or `fllama` (pub.dev).
  Maturity, llama.cpp version and Qwen3 support **unknown, verify**; costs a version mismatch with the laptop (say so).
- Audio: mic via `record` package PCM16 16 kHz stream (sherpa's streaming example uses it: verify); output via a PCM-stream player
  (`flutter_pcm_sound` or `flutter_sound`, verify) so the first clause plays while the next synthesizes. Last-resort output: WAV file +
  `audioplayers` (higher start latency, labelled).
- **Isolates (important):** sherpa calls are synchronous FFI. ASR runs in one isolate, TTS in another, the bus + UI in the main one,
  connected by `SendPort`s. Otherwise the dashboard freezes during synthesis.

## 2. Contract inside the app (same messages, Dart bus)
`bus.dart` mirrors `spine/app.py`: `FROM_EARS = {partial, tentative_final, final, cancel → brain; barge_in → voice+brain; intent_hint → voice}`,
`FROM_BRAIN = {chunk, cached, cancel → voice}`, `playback_state` voice → ears. **Commit gate:** Spine sends `{"type":"commit","turn","gen","t"}`
after `final`; Voice plays nothing for a `(turn, gen)` before its commit; a newer `gen` drops older ones (v2.1 rules). Messages are
`Map<String,dynamic>` with the exact contract fields. Every routed message → `bus.jsonl`, every stage event → `events.jsonl` in the laptop
format `{"stage","event","turn","t","extra"}`, pulled with adb for the same report scripts (which ones parse cleanly: verify).
Clock: one `Stopwatch` started at app launch, seconds as double (monotonic, one process).
| Dart file | Phone profile (contract row) | Ported from |
|---|---|---|
| `ears.dart` | mic or WAV-in → sherpa Silero VAD → Zipformer 20M int8; push-to-talk release = `t_eos`; tail-pad ~0.66 s before `inputFinished` | `ears/` (simplified) |
| `brain.dart` | Qwen3-0.6B **Q4_0**, ctx 1024 / n_predict 40 (T2: 512 / 25), system prompt warmed at start, first-clause chunker | `brain/prompt.py` text, `brain/chunker.py` rule |
| `voice.dart` | Piper lessac-low, 1 thread, cached clips (WAVs from `voice/cache/`), hold-until-commit | `voice/` |
| `spine.dart` | commit gate, 1 s telemetry, tier number | `spine/app.py` |
| `llama_process.dart` | start, wait for `/health`, kill | `brain/llama_server.py` |
Speculation **off** until measured on the phone. Note for Ears owner: laptop `asr_zipformer.finish()` has no tail padding; sherpa's examples
pad first, which may explain RESULTS.md's "needs 2.5–4 s of audio" limitation (hypothesis, verify).

## 3. Minimum demo by 07:30 (nothing else until this works)
1. **Push-to-talk** button (hold = listen, release = end of speech).
2. **Live dashboard:** state (LISTENING / THINKING / SPEAKING), partial + final transcript, answer text, **first-audio latency** (this turn,
   p50/p90, n), RAM (`ProcessInfo.currentRss`/`maxRss` for the app + llama-server `VmRSS`/`VmHWM` from `/proc/<pid>/status`), tok/s
   (from llama-server `timings`), tier, device line (model, Android version, RAM via a MethodChannel).
3. **WAV-in button:** streams a pushed `req_N.wav` at real-time speed instead of the mic (labelled), so a measured run exists even if the mic misbehaves.
Stretch, in order: cached greeting clips, temperature + tier step-down on throttling, KWS "hey Pecko", battery current.

## 4. Models via adb (no runtime download)
Release builds are not debuggable, so `run-as` is out. Push into the app's external files dir (path_provider `getExternalStorageDirectory()`):
```
adb shell mkdir -p /sdcard/Android/data/com.plumbers.pecko_app/files/models
adb push models/Qwen3-0.6B-Q4_0.gguf silero_vad.onnx models/zipformer_asr/<dir> <piper lessac-low dir incl. espeak-ng-data> \
         /sdcard/Android/data/com.plumbers.pecko_app/files/models/
```
(`mobile/push_models.sh`; adb write access there on Android 11+: **verify in spike**; fallback = mark the release build `debuggable` and use
`run-as` into internal storage). sherpa loads from file paths, not assets. **Download now while online:** `Qwen3-0.6B-Q4_0.gguf` (we only have
Q4_K_M; exact repo/filename verify), `silero_vad.onnx`, the android-arm64 llama tarball. Speed fallback: LFM2.5-350M Q4_0 (already in `models/`; it invented weather on laptop).

## 5. Build machine
**This VM (checked 01:40, `taskset -c 2-5`): no `flutter`, `dart`, `adb`, `java`, no `~/Android`, no `~/flutter`.** 13 GB disk free, 5 GB RAM shared with the running benchmark.
**Recommendation: build on a teammate's machine that already has Flutter + Android SDK** (run `flutter doctor` there first). Installing here is the fallback:
```
sudo apt install -y openjdk-17-jdk-headless adb git unzip xz-utils
# Flutter stable tarball from flutter.dev → ~/flutter ; Android cmdline-tools → ~/Android/cmdline-tools/latest
sdkmanager --sdk_root=$HOME/Android "platform-tools" "platforms;android-34" "build-tools;34.0.0"
flutter config --android-sdk $HOME/Android && flutter doctor --android-licenses
```
Size/time **estimates, not measured:** Flutter SDK ~1–2 GB after first run, Android SDK parts ~1 GB, Gradle deps ~1 GB, plus an NDK
(~1+ GB) if Gradle decides a plugin needs it. Roughly 3–5 GB and 30–60 min on good Wi-Fi. Run builds with `taskset -c 2-5`.
App commands:
```
cd mobile && flutter create --org com.plumbers --platforms android pecko_app      # tool scaffold, not a template project
cd pecko_app && flutter pub add sherpa_onnx record http path_provider
flutter build apk --release --split-per-abi --target-platform android-arm64
adb install -r build/app/outputs/flutter-apk/app-arm64-v8a-release.apk
```
VirtualBox needs a USB filter for the phone; else wireless debugging (`adb pair` / `adb connect`) before airplane mode.

## 6. Steps, time boxes, owner
Owner: **one Mobile person** on the build machine (+1 helper for the dashboard after 03:30 only if laptop L4 is safe). Laptop wins every conflict.
- **S0 (01:40–02:00):** pick the build machine (`flutter doctor` green for Android), start downloads, `flutter create`.
- **Spike (02:00–02:45, 45 min, GO/NO-GO):** a release APK that (1) installs, (2) execs `libllama_server.so` and streams a completion from
  Qwen3-0.6B Q4_0 (log prompt/decode tok/s, sweep `-t 2` vs `-t 4`), (3) runs sherpa Zipformer on one pushed WAV (log RTF) and speaks one
  Piper sentence (log RTF). **GO** = all three. Else F1/F2/F3. Results → `mobile/RESULTS.md`, labelled.
- **P1a (02:45–04:00):** bus + Ears (WAV-in first, then mic) + Brain + Voice → one end-to-end audible turn.
- **Kill criterion 04:00:** no end-to-end turn → stop features; ship the spike APK with a component-bench screen (F1).
- **P1b (04:00–05:15):** dashboard fields, p50/p90 counter, telemetry, cached greetings.
- **Measure (05:15–05:50):** 20 WAV-in turns × 2 (failures kept) + 10 live push-to-talk turns + 10-min sustained run.
- **06:00 phone frozen:** screen recording, `RESULTS.md`, numbers to README/deck owner.
Files (new, all under `mobile/`): `pecko_app/` (`lib/{main,bus,ears,brain,voice,spine,llama_process,event_log,telemetry,dashboard}.dart`,
`android/.../MainActivity.kt` channel), `fetch_libs.sh` (unpacks llama libs into `jniLibs/arm64-v8a/`, gitignored), `push_models.sh`, `RESULTS.md`.
Native libs and models are not committed; the scripts that fetch them are.

## 7. What we can honestly measure
| Metric | How |
|---|---|
| first audio p50/p90 + n | `t_eos` (button release, or labelled end in WAV-in) → first PCM handed to the player; player output latency measured once separately (method depends on plugin: verify), never hidden |
| tok/s, TTFT | llama-server `timings` + Brain `first_token` |
| ASR / TTS RTF | decode time / audio seconds per call |
| RAM | app `maxRss` + llama-server `VmHWM` (sum of peaks = upper bound, say so) |
| CPU | `/proc/self/stat` + `/proc/<pid>/stat` utime+stime per turn |
| temperature / energy | thermal status or `/sys/class/thermal` if readable; `BatteryManager` current × voltage unplugged minus idle, **only if it updates ≥ 1 Hz**, else "not joules" |
**No cgroup** (no root): the phone is the limit. Declare model, SoC, RAM, Android version, llama threads.

## 8. Risks and fallbacks
| Risk | Fallback |
|---|---|
| no machine with Flutter + Android SDK ready by 02:00 | install on VM (§5) or **F3** |
| `libllama_server.so` won't exec/link | **F2**: `llama_cpp_dart` / `fllama` FFI (maturity unknown) |
| sherpa_onnx pub version lacks an API we need | the matching `dart-api-examples` show the call; ASR first, TTS second |
| UI freezes / jank | move the blocking call into its isolate |
| mic or PCM player plugin issues | WAV-in + WAV-file playback, labelled |
| Qwen3-0.6B too slow, or throttling | LFM2.5-350M Q4_0, n_predict 25; foreground + wake lock; temperature shown with every number |
**F1** (builds, no full loop): APK with a component-bench screen (tok/s, RTF, RAM). Still an installable, on-device app.
**F3** (no toolchain at all): Termux: native android-arm64 `llama-bench`/`llama-server`, sherpa-onnx in `proot-distro` Ubuntu, WAV-in, component numbers. Said plainly: "not an app".

**README (phone):** device line; "Flutter Android app, fully offline, airplane mode, no root"; build (`fetch_libs.sh`, `flutter build apk`,
`adb install`, `push_models.sh`); push-to-talk + WAV-in modes; "no cgroup on phone; the phone is the limit".
**Deck (one slide):** "same contract laptop → phone app", dashboard screenshot, measured table (p50/p90 + n, tok/s, RAM, temperature,
energy or "not joules"). No laptop number on that slide.
