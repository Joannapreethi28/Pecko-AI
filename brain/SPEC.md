# BRAIN: build spec (v1 spec + v2 changes at the end)
> v2: this file is the source of truth for this role. Shared decisions, architecture and plan: ../docs/solution.md (v2). Contract: ../docs/CONTRACT.md.

**Runtime:** `llama-server` (llama.cpp, CPU build), one slot, streaming, localhost only.

**The bake-off (first task) and the decision rule.** Candidates, all GGUF:

| Candidate | Why it's in | Known risk |
|---|---|---|
| **Qwen3-0.6B Q4_K_M** (non-thinking, `/no_think`) | Full attention → **KV rewind works**, early prefill is safe. Multilingual (Hindi). ~0.4–0.5 GB. | Weakest answers of the three. |
| **Qwen3-1.7B Q4_K_M** | Same rewind safety, better answers. | ~1.1 GB weights, ~2× slower than 1.2B hybrids (vendor). May not fit with headroom. |
| **LFM2.5-1.2B-Instruct Q4_0** | Fastest per quality on CPU (vendor; independent Pi 5 data shows it modestly ahead of Gemma 3 1B). | **Hybrid conv layers: llama.cpp cannot cleanly rewind; a cache miss reprocesses the whole prompt.** Also check the LFM Open License. |
| LFM2.5-350M Q4_0 | Tier-down model, very fast. | Weak on facts. Same rewind risk. |

Measure for each, under the real cgroup with Ears running: TTFT with system prompt cached, TTFT after an early-prefill **rewind** (run `llama-server -lv 4` and check the log for "reprocessing"), decode tok/s at 1 thread, peak cgroup RAM, and answer quality on 20 fixed spoken-style questions (blind 1–5 score by a teammate).

**Pre-agreed rule:** T0 = the best-quality model whose (a) p50 TTFT after endpoint ≤ 300 ms, (b) rewind does not reprocess, (c) total stack peak RAM ≤ 1.6 GB. If LFM2.5 fails (b) but wins on speed, it is used **without** early prefill (append-only cache) and the comparison becomes a quantization/architecture finding for the 15% criterion. Default if short on time: **Qwen3-0.6B**.

**Settings (start here, then tune with `llama-bench` inside the cgroup):**
```
llama-server -m <model.gguf> -c 2048 -np 1 -t 1 -tb 2 --cache-prompt (default on)
             -ctk q8_0 -ctv q8_0 --mlock off (mmap on) --host 127.0.0.1
             (thinking off · temp 0.3–0.5 · n_predict 60 · stop after 2 sentences)
```
- **System prompt** ≤ 150 tokens, byte-identical every turn, warmed at startup (one dummy turn). Keep the last 2–3 turns of history, append only, never rewrite (rewriting kills the cache).
- **Prompt rules:** "Answer in one or two short spoken sentences. No lists, no markdown, no symbols, spell out numbers. If you don't know, say so in one sentence. You are offline and cannot browse."
- **Early prefill:** on each new `stable` text, send the prompt-so-far with `n_predict: 0`. On `tentative_final`, prefill the whole candidate. On `final`, only the delta remains. On `cancel` or a mismatch, rewind (works on full-attention models only).
- **Chunking to Voice:** flush the first chunk at the first `, . ? ! ;` after ≥ 2 words, or after 6 tokens. Then flush per clause or sentence. Strip anything unspeakable.
- **Cancel:** on `cancel` or `barge_in`, stop the stream within one token, bump `gen`.

**Router (tier 0 of the Brain, runs before the LLM):**
1. Exact match of `norm` against `intents.yaml` → `cached` clip (greeting, thanks, bye, who are you, what can you do, "I can't go online").
2. `rapidfuzz` ratio ≥ 90 against intent templates → `cached` clip. Require entity agreement. Log every hit.
3. **Composed answers** (time, date, day): computed from the local clock, sent as a chunk ("It's three forty-five PM"), Voice composes from cached word clips or synthesizes.
4. Everything else → LLM.
Seed `intents.yaml` with ~30–50 intents and agree it with Voice (Voice pre-synthesizes every reply). **False-hit rate is measured on held-out phrasing**, because judges speak unseen requests.

**Brain ablation rows:** no cache · system-prompt KV cache · + early prefill (stable) · + tentative_final prefill · + router/cache-first · model A vs B vs C at the same cap · Q4 vs Q8 (quality + speed).

**Done when:** TTFT and first-chunk p50/p90 logged; cache warm start verified; early prefill + ablation table; 2+ model tiers switch cleanly between turns; replies always speakable; peak RAM and tok/s under the cap.

---
## v2 changes
- **Hold-and-release:** on `tentative_final`, prepare the **first clause only** privately (`held:true`, own `gen`). Stop at the first-clause/buffer target; do not generate the whole reply early. On `final`, validate that the full serialized prompt tokens match. On match, Spine sends `commit`; on mismatch, rewind, recompute, new `gen`.
- Never share one mutable KV buffer between a speculative branch and committed history.
- **Answer first** in the prompt (answer, then a short reason). Keep the prompt identical across scheduler comparisons.
- Phone profile: Qwen3-0.6B **Q4_0**, ctx 512–1024, n_predict 25–40 (see ../mobile/SPEC.md).
