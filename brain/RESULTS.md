# BRAIN results (measured on OUR machine under the cap; nothing here is vendor data)
Machine / OS / cap / llama.cpp commit / model hashes: _fill in_

## Bake-off
| Model + quant | TTFT p50 (cached sys prompt) | TTFT after early-prefill rewind | rewind reprocesses? | decode tok/s (1 thr) | peak cgroup RAM | quality /5 (20 q) |
|---|---|---|---|---|---|---|
| Qwen3-0.6B Q4_K_M | | | | | | |
| Qwen3-1.7B Q4_K_M | | | | | | |
| LFM2.5-1.2B Q4_0 | | | | | | |
| LFM2.5-350M Q4_0 | | | | | | |

Decision (apply the rule in SPEC.md): _fill in_

## Brain ablation
| Config | first_token p50/p90 | first_chunk p50/p90 | wasted prefill % | notes |
|---|---|---|---|---|
| no cache | | | | |
| + system-prompt KV cache | | | | |
| + early prefill (stable) | | | | |
| + tentative_final prefill | | | | |
| + router / cache-first | | | | |
| Q4 vs Q8 | | | | |
