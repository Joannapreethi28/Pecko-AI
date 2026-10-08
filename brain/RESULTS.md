# BRAIN results (measured on OUR machine under the cap; nothing here is vendor data)
Machine / OS / cap / llama.cpp commit / model hashes:
- **ubuntu-vm, 2 CPU / 2 GB cgroup** (8 Oct): VirtualBox VM (6 vCPU, ~6 GB) on i7-14650HX, Ubuntu kernel 6.17.0-14, llama.cpp b11501 (`b11501-ubuntu`), Qwen3-0.6B-Q4_K_M.gguf sha256 `ac2d97712095a558...`.
- Cap: `systemd-run --user --scope -p CPUQuota=200% -p MemoryMax=2G -p MemorySwapMax=0 -- taskset -c 0,1 ...`. Verified inside the scope: `cpu.max = 200000 100000`, `memory.max = 2147483648`, `memory.swap.max = 0`. CPU pinning is `taskset`, not `AllowedCPUs` (a user scope has no cpuset controller; the sudo form in `spine/SPEC.md` uses `AllowedCPUs`). Network was not disabled for this run.
- Model file evicted from the page cache before the run (otherwise `memory.peak` under-reports, see `gotcha.md` G17).

## Bake-off
| Model + quant | TTFT p50 (cached sys prompt) | TTFT after early-prefill rewind | rewind reprocesses? | decode tok/s (1 thr) | peak cgroup RAM | quality /5 (20 q) |
|---|---|---|---|---|---|---|
| Qwen3-0.6B Q4_K_M (ubuntu-vm, 2 CPU / 2 GB cgroup) | p50 103 ms, p90 123 ms (n=20) | p50 103 ms (n=5) | no | 34.1 (median) | 814 MB (server + harness) | not scored yet |
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
