# EARS: Optimizations (v2)

What changed from the first Ears plan, and why each change makes Ears faster, lighter or safer.
Numbers marked *estimate* are my expectations, not measurements. Confirm each one in the 30-clip test.

---

## Summary table

| # | Optimization | Helps | Effort | Expected gain (estimate) |
|---|---|---|---|---|
| O1 | Finish ASR speculatively during the pause | Latency | Low | Hides ~50-150 ms of ASR final decode |
| O2 | Start Smart Turn at the first silent frame, not after 200 ms | Latency | Low | ~50-100 ms off endpoint delay |
| O3 | Turn off ONNX Runtime thread spinning | Energy, CPU | Very low | Large drop in idle CPU (spinning threads burn CPU while waiting) |
| O4 | Warm up every model at startup | Latency (first turn) | Very low | Removes the slow first inference the judges would hit |
| O5 | Stamp times at audio capture, not at processing | Honest numbers | Very low | Correct `t_eos` (no hidden processing lag) |
| O6 | Per-speaker adaptive pause cap | Fewer cut-offs | Medium | Fewer false cut-offs for slow speakers, faster for quick ones |
| O7 | Throttle partials (only on change, max ~1 per 150 ms) | CPU, Brain load | Very low | Less queue traffic and less wasted Brain prefill |
| O8 | Cheap 48 kHz to 16 kHz decimation | CPU | Low | Avoids a heavy resampler running all the time |
| O9 | Echo-safe barge-in rule | Robustness | Medium | Assistant does not "hear itself" and interrupt its own reply |
| O10 | Normalised text + hotwords for Indian names and numbers | Accuracy | Low | Fewer wrong words on place names, numbers, rupees |

The three that matter most: **O1 + O2** (latency score), **O3** (energy score).

---

## O1. Finish ASR speculatively during the pause

**Problem.** A streaming ASR still holds back its last word or two until it sees a bit of silence or is told "input finished". If we only call `finish()` after the endpoint is confirmed, that final decode is added to latency.

**Fix.** At the first 200 ms pause, immediately run the ASR's finish/flush on a *copy* of the stream state while the turn decision runs in parallel.
- If the turn is confirmed done, the final text is already ready. Send `final` at once.
- If speech resumes, throw the copy away and keep feeding the live stream.

**Cost.** One extra short decode per pause. Cheap compared to the time saved.

## O2. Start Smart Turn at the first silent frame

**Problem.** Old plan: wait for 200 ms of silence, then run Smart Turn (~40-65 ms), then decide. That stacks two delays.

**Fix.** The first time VAD says "silence", start Smart Turn on a worker thread right away. By the time 150-200 ms of silence have passed, p(done) is already computed.
- Confident done (p >= 0.7, no dangling word) can now fire at ~150 ms of silence instead of ~260 ms.
- If speech comes back in that window, discard the result.

**Note.** Smart Turn should still see the whole current turn's audio (up to 8 s), not just the last chunk.

## O3. Turn off ONNX Runtime thread spinning

**Problem.** By default, ONNX Runtime worker threads "spin" (busy-wait) between calls to react faster. Ears calls models every 32 ms, so spinning threads can keep a core busy even in silence. That shows up directly in the energy score.

**Fix.** For every session Ears creates:
```python
so = ort.SessionOptions()
so.intra_op_num_threads = 1
so.inter_op_num_threads = 1
so.add_session_config_entry("session.intra_op.allow_spinning", "0")
so.add_session_config_entry("session.inter_op.allow_spinning", "0")
```
For sherpa-onnx and Moonshine, set `num_threads=1` and check their docs for a spinning option. Measure idle CPU before and after. This is one table row in the write-up.

## O4. Warm up every model at startup

**Problem.** The first inference of an ONNX model is much slower (memory allocation, graph optimisation). Judges usually test the *first* request.

**Fix.** At `start()`, push 1 s of silence plus one short dummy turn through VAD, KWS, ASR and Smart Turn. Report "ready" only after that.

## O5. Stamp times at audio capture

**Problem.** If `t_eos` is stamped when the VAD *finishes processing* a frame, it includes queue and processing delay, and our latency looks different from reality.

**Fix.** Stamp each 32 ms frame with the shared clock in the audio callback (capture time). `t_eos` = capture time of the end of the last speech frame. `t_endpoint` = clock time when `final` is sent. Then `t_endpoint - t_eos` is the true endpoint delay.

## O6. Per-speaker adaptive pause cap

**Problem.** One hard cap (1.0 s) is too long for fast talkers and too short for slow, thoughtful ones. Judges are unseen speakers.

**Fix.** During a session, keep a running median of each user's *mid-sentence* pauses (pauses where they then continued). Set the cap to about `median_pause x 1.5`, clamped between 0.5 s and 1.2 s. Reset when the wake word starts a new session.

**Why it is new.** It adapts to the judge in front of us within the first one or two turns, with no training.

## O7. Throttle partials

Send a `partial` only when the text actually changes, and at most about once per 150 ms. Add the `stable` prefix field (words agreed by two consecutive partials). Brain prefills only stable words.

## O8. Cheap resampling

Ask the mic for 16 kHz mono directly. If the device only gives 48 kHz, decimate by exactly 3 with a short low-pass filter (`scipy.signal.resample_poly(x, 1, 3)`), not a generic high-quality resampler.

## O9. Echo-safe barge-in

**Problem.** With laptop speakers, the mic hears our own TTS. VAD fires and the assistant interrupts itself.

**Fix (in order of reliability).**
1. Demo with headphones or a headset mic.
2. While Voice is playing, raise the VAD threshold (e.g. 0.5 to 0.8) and require ~250 ms of continuous speech before signalling barge-in.
3. Ignore the wake word while Voice is playing.

## O10. Normalised text and hotwords

- Hotword list for likely judge words: Coimbatore, Karunya, Chennai, Tamil Nadu, rupees, lakh, crore, the assistant's name.
- Normalise the final text (lowercase, strip fillers like "um", "uh") in a separate field so Voice's cache lookup and Brain's prompt stay clean.

---

## New latency budget (estimate, replaces v1)

| Segment | v1 plan | v2 plan |
|---|---|---|
| Endpoint delay (`t_endpoint - t_eos`), clear sentence | 150-350 ms | ~150-250 ms |
| ASR final decode after endpoint | 20-80 ms | ~0 ms (done during the pause) |
| **Ears share of latency** | ~0.2-0.4 s | **~0.15-0.25 s** |

## New ablation rows to add

| Config | Median endpoint delay | p90 | False cut-offs /30 | Idle CPU |
|---|---|---|---|---|
| D. Fusion endpointer (v1) | | | | |
| D + O1 + O2 (speculative ASR finish + early Smart Turn) | | | | |
| D + O6 (adaptive pause cap) | | | | |
| Idle CPU: spinning ON vs OFF (O3) | | | | |
