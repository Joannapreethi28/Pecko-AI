# End-to-end ablation on synthetic24 (measured 9 Oct 2026, 03:14–03:40)

Same 24 synthetic WAVs (`data/clips/synthetic24/q*.wav`), same cap as every headline run
(2 logical CPUs `PECKO_CPUS=2,3`, CPUQuota 200%, MemoryMax 2G, swap 0), `--ears-tier 2` (Zipformer 20M),
`--no-audio` (Voice still synthesizes; first audio = PCM handed to the player). Same LLM in all rows and in B0.
Baseline B0 = `data/results/baseline-syn24-b0` (p50 2059 / p90 2496 ms, CPU-s/turn 1.96, peak 917 MiB).
Leave-one-out from full Pecko: each row turns ONE technique off (except the two combined rows).
**Each row is ONE run of 24 turns.** Run-to-run noise: full Pecko p50 was 835 / 882 / 880 ms over three runs
(p90 1280 / 1375 / 1225), so treat p50 differences under ~±50 ms and p90 differences under ~±150 ms as noise.
Peak RAM also moves ~±90 MiB between identical runs (928 vs 839 MiB for full Pecko). Failures are kept in n (there were none).
"C (commit) p50" = median ms from end of speech to the commit gate / endpoint (compare_runs `P C/endp` column).

| config | flags | first audio p50 / p90 (ms) | C (commit) p50 (ms) | paired gap B0-Pecko p50 / p90 (ms) | Pecko faster | CPU-s/turn | peak RAM MiB | failures |
|---|---|---|---|---|---|---|---|---|
| full Pecko (all on) | `` | n=24: 882 / 1375 | 299 | 1179 / 1454 | 24/24 | 1.33 | 928 | none |
| - hold-and-release | `--no-hold` | n=24: 872 / 1425 | 298 | 1172 / 1435 | 24/24 | 1.28 | 855 | none |
| - early prefill (no speculation at all) | `--no-early-prefill` | n=24: 828 / 1156 | 295 | 1180 / 1549 | 24/24 | 1.04 | 939 | none |
| - system-prompt KV cache | `--no-cache-prompt` | n=24: 2256 / 3604 | 367 | -349 / 240 | 6/24 | 6.15 | 849 | none |
| - answer cache/router | `--no-router` | n=24: 956 / 1282 | 296 | 1111 / 1406 | 24/24 | 1.28 | 909 | none |
| - fusion endpointer (fixed 800 ms timer) | `--endpointer fixed_800` | n=24: 1400 / 1796 | 815 | 673 / 985 | 24/24 | 1.24 | 815 | none |
| - KV cache AND early prefill | `--no-cache-prompt --no-early-prefill` | n=24: 1374 / 1717 | 294 | 634 / 986 | 24/24 | 1.97 | 860 | none |
| all four off (bottom of ladder) | `--no-cache-prompt --no-early-prefill --no-router --endpointer fixed_800` | n=24: 1810 / 2180 | 816 | 191 / 505 | 22/24 | 1.87 | 871 | none |
| repeat: full Pecko | `` | n=24: 880 / 1225 | 297 | 1180 / 1459 | 24/24 | 1.26 | 839 | none |
| repeat: - early prefill | `--no-early-prefill` | n=24: 851 / 1360 | 295 | 1162 / 1434 | 24/24 | 1.15 | 837 | none |
| repeat: - hold-and-release | `--no-hold` | n=24: 901 / 1318 | 295 | 1178 / 1416 | 24/24 | 1.25 | 840 | none |
| reference: earlier full run (run-syn24-pecko-ram) | `` | n=24: 835 / 1280 | 296 | 1199 / 1472 | 24/24 | 1.20 | 846 | none |

## What it says (honest reading)

- **Fusion endpointer is the biggest Pecko-specific step**: fixed 800 ms timer moves C from ~297 to 815 ms
  and first audio p50 882 -> 1400 ms (+518 ms), p90 1375 -> 1796 ms. Note `fixed_800` also suppresses
  `tentative_final`, so this row also has no tentative-final speculation (by design of ears/endpointer.py).
- **System-prompt KV cache (`cache_prompt`) is the biggest single number**, but the plain leave-one-out row
  (2256 ms, worse than B0) is inflated: with the cache off, early prefill keeps re-prefilling the full prompt
  for nothing (CPU-s/turn 6.15) and starves the real answer. The fair row is "KV cache AND early prefill off":
  1374 ms p50 (+492 ms vs full), CPU-s/turn 1.97 vs 1.33. B0 also runs with `cache_prompt=False`.
- **Early prefill / hold-and-release speculation: no measurable gain on this set.** Without early prefill:
  828 and 851 ms p50 (two runs) vs 835/882/880 for full; without hold: 872 and 901 ms. All within noise,
  and speculation costs ~0.1–0.3 CPU-s/turn. Why (our reading, not measured separately): with the
  system prompt already cached, prefilling a ~10-token question after C is cheap, and C (~300 ms) is
  rarely the later of max(C, R). Short synthetic questions are the easy case for "no speculation".
- **Answer cache/router: 0 cache hits on synthetic24** (all factual questions), so the `--no-router` delta
  (956 vs 882 ms p50) is run-to-run noise, not an effect of the router. It needs a set with greetings/identity turns.
- **All four off** (no KV cache, no early prefill, no router, fixed 800 ms) is still 191 ms p50 faster than B0
  (1810 vs 2059 ms). That leftover is what was NOT ablated here: streaming ASR (vs B0's whole-utterance decode),
  first-clause chunking to Voice, and Voice pipeline differences. No switch exists for those yet
  (whole-reply TTS would need Brain and Voice changes; not done in this window).

## Exact commands

```bash
# one config (the runner below does exactly this for each name)
PECKO_CPUS=2,3 scripts/run_pecko.sh --wav data/clips/synthetic24/q*.wav --ears-tier 2 --no-audio <flags> \
  --out data/results/ablation-e2e-<name>
.venv/bin/python scripts/compare_runs.py data/results/ablation-e2e-<name> data/results/baseline-syn24-b0

# what was run, in this order, one at a time:
scripts/run_ablation_e2e.sh                                   # full no-hold no-early-prefill no-cache-prompt no-router fixed800
scripts/run_ablation_e2e.sh full-r2 no-early-prefill-r2 no-hold-r2
scripts/run_ablation_e2e.sh no-cache-no-prefill all-off
```

Flags (spine/app.py; absent = shipped behaviour, unchanged): `--no-hold` (existed), `--no-early-prefill`,
`--no-cache-prompt`, `--no-router`, `--endpointer {fusion,fixed_800,fixed_400}`.
Per-turn detail: `data/results/ablation-e2e-<name>/compare_vs_baseline-syn24-b0.txt`.
