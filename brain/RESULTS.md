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
| Config | first_token p50/p90 | first_chunk p50/p90 | wasted prefill % | notes |
|---|---|---|---|---|
| no cache | | | | |
| + system-prompt KV cache | | | | |
| + early prefill (stable) | | | | |
| + tentative_final prefill | | | | |
| + router / cache-first | | | | |
| Q4 vs Q8 | | | | |
