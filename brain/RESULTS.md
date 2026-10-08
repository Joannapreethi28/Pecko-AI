# BRAIN results (measured on OUR machine under the cap; nothing here is vendor data)
Machine / OS / cap / llama.cpp commit / model hashes:
- **ubuntu-vm, 2 CPU / 2 GB cgroup** (8 Oct): VirtualBox VM (6 vCPU, ~6 GB) on i7-14650HX, Ubuntu kernel 6.17.0-14, llama.cpp b11501 (`b11501-ubuntu`), Qwen3-0.6B-Q4_K_M.gguf sha256 `ac2d97712095a558...`.
- Cap: `systemd-run --user --scope -p CPUQuota=200% -p MemoryMax=2G -p MemorySwapMax=0 -- taskset -c 0,1 ...`. Verified inside the scope: `cpu.max = 200000 100000`, `memory.max = 2147483648`, `memory.swap.max = 0`. CPU pinning is `taskset`, not `AllowedCPUs` (a user scope has no cpuset controller; the sudo form in `spine/SPEC.md` uses `AllowedCPUs`). Network was not disabled for this run.
- Model file evicted from the page cache before the run (otherwise `memory.peak` under-reports, see `gotcha.md` G17).

## Bake-off
| Model + quant | TTFT p50 (cached sys prompt) | TTFT after early-prefill rewind | rewind reprocesses? | decode tok/s (1 thr) | peak cgroup RAM | quality /5 (20 q) |
|---|---|---|---|---|---|---|
| Qwen3-0.6B Q4_K_M (ubuntu-vm, 2 CPU / 2 GB cgroup) | p50 103 ms, p90 123 ms (n=20) | p50 103 ms (n=5) | no | 34.1 (median) | 814 MB (server + harness) | not scored yet |
| Qwen3-1.7B Q4_K_M (ubuntu-vm, 2 CPU / 2 GB cgroup) | p50 256 ms, p90 276 ms (n=20) | p50 238 ms (n=5) | no | 13.6 | 2012 MB (at the 2 GB cap; no OOM kill) | not scored yet |
| LFM2.5-1.2B-Instruct Q4_0 (ubuntu-vm, 2 CPU / 2 GB cgroup) | p50 232 ms, p90 264 ms (n=20) | p50 221 ms (n=5) | **yes** | 19.8 | 1370 MB | not scored yet |
| LFM2.5-350M Q4_0 (ubuntu-vm, 2 CPU / 2 GB cgroup) | p50 69 ms, p90 78 ms (n=20) | p50 71 ms (n=5) | **yes** | 58.7 | 450 MB | not scored yet |

Downloads (9 Oct): `unsloth/Qwen3-1.7B-GGUF`, `LiquidAI/LFM2.5-1.2B-Instruct-GGUF`, `LiquidAI/LFM2.5-350M-GGUF` (plain Q4_0, not QAD). sha256 prefixes: 1.7B `b139949c5bd74937`, LFM2.5-1.2B `2ea801949d760cdf`, LFM2.5-350M `85e32858daafad55`. Each model evicted from page cache before its run (G17). Peak RAM = Brain alone (server + harness), not the full stack.

Decision (rule in SPEC.md; **provisional until the blind quality scores are in**, `data/results/blind_scores.csv`, 80 rows):
- Qwen3-1.7B fails (c): Brain alone fills the 2 GB cap (2012 MB), so it cannot fit a 1.6 GB stack. Also 2.5x slower TTFT than 0.6B.
- LFM2.5-1.2B and LFM2.5-350M fail (b): the rewind reprocesses the prompt, so early prefill would waste work. Per the rule they are usable only without early prefill (append-only cache).
- Qwen3-0.6B passes (a), (b), (c) → **T0 stays Qwen3-0.6B Q4_K_M**.
- Observation, not a decision: LFM2.5-350M is the fastest (69 ms TTFT, 58.7 tok/s, 450 MB), which fits T2 where speculation is already off. Tier changes need team agreement.
- Quality note: both LFM models invented live weather for Coimbatore ("partly cloudy, 28 °C"); Qwen3 models said they have no live data.

## Brain ablation
**ubuntu-vm, 2 CPU / 2 GB cgroup** (9 Oct). Qwen3-0.6B, temperature 0, `brain/ablation_turns.jsonl` (12 turns: 5 plain, 3 hesitations, 2 corrections, 2 router intents), each played through `sim.speak` at real-time speed, 3 reps → n = 36 per row. llama-server (flags as in the bake-off) and `brain.ablate` ran **in the same capped scope** (`CPUQuota=200%`, `MemoryMax=2G`, `MemorySwapMax=0`, `taskset -c 0,1`); model evicted from page cache first. Times are from `final` fed to Brain. "first chunk" = `first_chunk`, or `cache_hit` for router answers. Nearest-rank percentiles. Raw: `data/results/ablation_q4-ubuntu-vm-cg.jsonl`, `ablation_q8-ubuntu-vm-cg.jsonl`.

| Config | first_token p50/p90 | first chunk p50/p90 | wasted prefill % | n | notes |
|---|---|---|---|---|---|
| no cache | 878 / 1041 ms | 1024 / 1198 ms | n/a | 36 | whole prompt recomputed every turn |
| + system-prompt KV cache | 131 / 671 ms | 290 / 813 ms | n/a | 36 | p90 tail: see finding 1 |
| + early prefill (stable) | 80 / 93 ms | 231 / 265 ms | 0.0% | 36 | |
| + tentative_final prefill | 36 / 39 ms | 177 / 213 ms | 10.8% | 36 | best LLM-path config |
| + router / cache-first | 37 / 40 ms | 182 / 216 ms | 11.9% | 36 | only 2/12 turns are router intents |
| Q8: + system-prompt KV cache | 139 / 788 ms | 316 / 976 ms | n/a | 36 | |
| Q8: + tentative_final prefill | 51 / 61 ms | 261 / 319 ms | 0.0% | 36 | Q4 is 84 ms faster at p50 first chunk |

Cgroup `memory.peak` (server + harness, whole run): Q4 981 MB, Q8 933 MB; `oom_kill 0` both.

Findings:
1. **History rewrite breaks the cache.** In `sys_cache`, from turn 5 on `cache_n` falls back to ≈ 106-110 (system prompt only) and 90-100 tokens are recomputed per turn → the 671 ms p90. Likely the history window drops the oldest turn and shifts everything after the system prompt. Early prefill hides it (recompute happens during speech), but T2 (speculation off) would pay it. Not fixed yet.
2. Each feature cuts first-chunk p50: 1024 → 290 → 231 → 177 ms. Early prefill on `tentative_final` costs 10.8% wasted prefill (correction turns).
3. Q4_K_M beats Q8_0 on latency (first chunk p50 177 vs 261 ms). Q8 quality on the 20 questions is not scored yet.
4. Not understood yet (do not quote): Q8 `early_tentative` wasted 0.0% vs Q4 10.8% on the same turns; Q8 cgroup peak lower than Q4 despite the larger file (the Q4 run also ran 3 more configs).
