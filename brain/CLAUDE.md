# BRAIN (Sir Jabin's role)
Read `SPEC.md` (build spec), `../docs/CONTRACT.md`, and `../docs/solution.md` §3, §5.2, §6, §7 first.

## Mission
Take `partial`/`tentative_final`/`final` from Ears, return short spoken-style `chunk`s to Voice as fast as possible. First chunk speed matters far more than long-answer quality. A router answers common intents without the LLM.

## Why the design is what it is (explain this to Sir Jabin as you go)
- **Prefill** (reading the prompt) is compute-bound → can be done early on stable words. **Decode** (writing tokens) is memory-bandwidth-bound → fewer/lighter weights = faster.
- Early prefill only works if the KV cache can **rewind** on a mismatch. Full-attention models (Qwen3) rewind cleanly; hybrid models (LFM2) reportedly do not in llama.cpp (unverified, test with `-lv 4` and look for "reprocessing").
- System prompt must be **byte-identical** every turn or the cache is lost.
- Qwen3 **thinking mode must be off** (pre-fill an empty think block / `/no_think`), otherwise silent seconds. Check this first.

## First tasks, in order (stop and show Sir Jabin the result of each)
1. `common/clock.py` + `common/log.py` agreed with the team (shared by all stages).
2. Get a CPU `llama-server` running with Qwen3-0.6B Q4_K_M; confirm flags with `llama-server --help` (flags in SPEC.md come from research, not yet run).
3. `brain/mock_cli.py`: type text → stream chunks with `first_token` / `first_chunk` timestamps. Verify system-prompt cache works (second turn prefill ≈ delta only).
4. Chunker (first chunk at first `, . ? ! ;` after ≥2 words or 6 tokens) + speakable-text filter + cancel within one token (bump `gen`).
5. Bake-off script (20 fixed spoken-style questions; TTFT, rewind behaviour, tok/s, peak RAM; blind 1-5 quality score by a teammate) → write results to `RESULTS.md`. Apply the pre-agreed rule in SPEC.md. Default if short on time: Qwen3-0.6B.
6. Early prefill on `stable`, `tentative_final` handling, `cancel` rewind; ablation rows.
7. Router + `intents.yaml` (30-50 intents, agree with Voice), measure false-hit rate on held-out phrasing.
8. Model tiers T0/T1/T2 switch between turns only; measure switch time + peak memory.

## Do not
Use Laya/CLM/Jev as the generator (rejected, see docs/solution.md §12) · enable thinking · rewrite the system prompt between turns · use draft-model speculative decoding · claim a speed/RAM number we did not measure.
