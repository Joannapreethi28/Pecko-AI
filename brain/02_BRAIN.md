> **Original role brief (v1).** The build spec is `SPEC.md` in this folder; the shared contract is `../docs/CONTRACT.md` (v2). Research ideas below are folded into the master ablation in `../docs/solution.md` §7.

# ROLE 2: BRAIN (thinking)

## In plain words
You are the thinker. You read the user's words and write a **short, spoken-style reply**, sending it out **in small pieces while still writing**, so the voice can start talking before the full answer exists. Speed to the **first piece** matters far more than quality of long answers.

## You own
- The small language model (LLM) and how it is quantized
- The runtime that runs it on CPU
- Prompt design: short spoken replies, no lists, no markdown
- Streaming output and the rule for when to cut a chunk
- Early start: begin preparing before the user has fully finished

## Input / Output (see the Team Brief contract)
- In: `partial` and `final` text from Ears
- Out: `chunk` messages (with `seq` and `last`) to Voice

## Test alone with a mock
Type text into a terminal and watch chunks stream out with timestamps for `first_token` and `first_chunk`.

## Solo research questions
1. Which small models (roughly 0.3B to 1.5B params) give **coherent short replies** on CPU? Compare size, speed and quality.
2. Which runtime gives the fastest **time to first token** on 1 to 2 cores? (llama.cpp, ONNX Runtime GenAI, others). Which quantization level is best at this size, and does harder quantization actually help speed?
3. How do we **cache the system prompt** so only the new user words are processed each turn?
4. How do we start the model **before the user finishes speaking** (early prefill from partial text), and when must we throw that work away?
5. What are the right thread settings when ASR and TTS share the same 2 cores?
6. How do we keep replies short and spoken-style without losing usefulness? (prompt design, max tokens, stop rules)
7. Does speculative decoding help or hurt on 2 cores?

## Your research idea to test (the "what's new" score)
**Early prefill on partial transcripts.** While the user is still speaking, push the stable part of the transcript into the model's cache. At end of speech, only process the leftover words. Ablate: off / prefill only / prefill plus look-ahead. Report first-token time saved, extra compute wasted, and how often the early work is invalidated.

## Stretch goals for Brain
- **Multilingual:** which small model replies well in Hindi/Tamil/English? Does it stay coherent at our size?
- **Smaller device:** which model and quantization fit a Pi or phone RAM, and what tokens/sec do they reach?
- **Tighter limits (quality kept):** define a **model ladder**: 2 or 3 sizes, each with its own context length and max reply length, so Spine can switch tiers as the budget shrinks. Switch between turns, never mid-reply.
- **Cached TTS:** help Voice with a list of the most common reply types so the cache covers them. Consider letting the model pick a cached reply instead of generating one when the question is common.

## Definition of done (for the build phase)
- Time to first chunk, measured and logged, median and p90
- System prompt cache working (warm start, no re-processing)
- Early prefill implemented with the ablation table
- At least 2 model tiers with a tested switch
- Replies always short and speakable (no symbols, lists, or markdown read out loud)
- Peak RAM and tokens/sec measured under the declared limit
