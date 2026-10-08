> **Original role brief (v1).** The build spec is `SPEC.md` in this folder; the shared contract is `../docs/CONTRACT.md` (v2). Research ideas below are folded into the master ablation in `../docs/solution.md` §6.

# ROLE 3: VOICE (speaking)

## In plain words
You are the mouth. You turn the reply pieces into sound and play them **as early as possible**, without gaps or glitches. You also keep a **library of ready-made audio** for common replies, so those play instantly with zero synthesis time.

## You own
- The text-to-speech (TTS) engine and its quantization
- Splitting incoming text into speakable pieces (phrases)
- Audio playback with low delay (and stopping when the user interrupts)
- The cache of pre-synthesized audio (greetings, fillers, common answers) and the logic that decides when to use it

## Input / Output (see the Team Brief contract)
- In: `chunk` messages from Brain
- Out: audio to the speaker, plus a logged `t_first_audio_out`

## Test alone with a mock
Hardcode a list of sentences, feed them as chunks, and measure time from "chunk received" to "first sound out".

## Solo research questions
1. Which TTS gives the **fastest first audio** on 1 to 2 CPU cores with a small RAM footprint? Compare real numbers, not claims.
2. Quantization trap check: does the smaller / int8 version actually run faster on **our** CPU, or slower? Test it.
3. How do we stream audio **phrase by phrase** (cut at commas and periods) without choppy joins?
4. How do we play audio with the lowest delay? (buffer sizes, audio library, how to stamp the exact first-sample time)
5. How do we handle **barge-in**: the user speaks while the assistant is talking, so we stop instantly.
6. Cache design: what to pre-generate, how big is it, how do we match a reply to a cached clip quickly?
7. How natural does it sound? Pick a voice the judges will not wince at.

## Your research idea to test (the "what's new" score)
**Cache-first responses with a filler.** Compare four cases: no cache / fillers only / fillers plus common answers / full cache with intent matching. Measure first-audio latency, hit rate, energy per turn, and the rate of wrong cached answers. Be honest about the difference between "first audio of any kind" and "first audio of the real answer". Judges may treat a filler as cheating if we only report the first.

## Stretch goals for Voice
- **Cached / pre-synthesized TTS (priority):** this is your main bonus. Build it early, because it is cheap and visible.
- **Multilingual:** which TTS has voices for Hindi/Tamil/other languages at a small size? Quality honestly rated.
- **Smaller device:** does your TTS run on a Pi or phone? Check RAM and speed on ARM.
- **Tighter limits (quality kept):** define a **voice ladder**: a good voice at full budget, a lighter voice when starved, and a last-resort tiny engine or cached clips only.

## Definition of done (for the build phase)
- Median time from first chunk → first sound, measured and logged
- Phrase streaming with no audible gaps
- Barge-in works (stops within a short, measured delay)
- Cache built with a measured hit rate on the 30-clip test set
- At least 2 voice tiers with a tested switch
- Peak RAM and CPU measured under the declared limit
