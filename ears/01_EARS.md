> **Original role brief (v1).** The build spec is `SPEC.md` in this folder; the shared contract is `../docs/CONTRACT.md` (v2). Research ideas below are folded into the master ablation in `../docs/solution.md` §6.

# ROLE 1: EARS (listening)

## In plain words
You are the ear. You notice when someone starts talking, catch the wake word, understand the speech as it happens, and **decide the exact moment the person has finished**. That last part matters most: every millisecond you wait to decide is added to the total latency.

## You own
- Wake word (e.g. "hey assistant")
- VAD (voice activity detection: speech vs silence)
- End-of-turn detection (did they finish, or just pause?)
- Streaming ASR (speech → text while they are still talking)

## Output you must produce (see the Team Brief contract)
- `partial` messages while speaking
- one `final` message with `t_eos` and `t_endpoint` timestamps

## Test alone with a mock
Feed a recorded WAV file as if it were the microphone. Print the partials, the final, and the endpoint delay.

## Solo research questions
1. Which VAD is lightest and gives the **fastest** speech-end detection? What silence wait (hangover) is safe?
2. How can we tell "finished" from "paused" **faster than a fixed silence timer**? (look for turn-detection models)
3. Which ASR gives true **streaming** text on 1 to 2 CPU cores with the lowest RAM and delay after the last word?
4. Which wake-word option works fully offline with no account or key?
5. How accurate is each choice on **accented Indian English**? (we're being tested live by judges)
6. How much CPU does the whole Ears stage use while idle and listening? (this runs all the time, so it hurts the energy score)

## Your research idea to test (the "what's new" score)
**Smarter end-of-turn detection.** Compare a fixed silence timer against a turn-detection model plus a short silence timer. Measure latency saved and how often we cut someone off mid-sentence. This one table can be a headline result.

## Stretch goals for Ears
- **Multilingual:** which ASR handles Hindi, Tamil or other languages at our footprint? Streaming or not? What accuracy?
- **Smaller device:** does your stack run on a Raspberry Pi or phone? (check ARM support and RAM)
- **Tighter limits:** have a lighter fallback ASR for when the budget shrinks (smaller model, lower sample rate).
- **Cached TTS:** nothing for you directly, but tell Voice when you can detect "common phrase" cases early.

## Definition of done (for the build phase)
- Runs under the declared limit alongside the other stages
- Median delay from last word → `final` message is measured and logged
- Zero false cut-offs on our 30-clip test set (or the rate is reported)
- Idle CPU while listening is measured
- Works from both a live mic and a WAV file
