# Degradation at a tighter cap: Pecko vs B0, 1 CPU (measured 9 Oct 2026, ~03:12–03:27)

Same 24 synthetic WAVs (`data/clips/synthetic24/q*.wav`), same turn order, paired by turn, same LLM
(Qwen3-0.6B-Q4_K_M, 1 llama thread) in every run. One run per row. All runs are on CPU 4 (`taskset -c 4`)
with a user systemd scope: `CPUQuota=100%`, `MemoryMax` as listed, `MemorySwapMax=0`. Metric = end of speech
(t_eos) → first audio, from `scripts/compare_runs.py`. Failures = turns with no first audio (kept in n).
"Paired gap" = B0 − Pecko on the same turn (p50 / p90 / min). Peak RAM = cgroup `memory.peak` incl. model load.

| Cap | Stack | Tier | p50 ms | p90 ms | max ms | Paired gap p50 / p90 / min ms | Pecko faster | Failures | CPU-s/turn | Peak RAM MiB | oom_kill | git HEAD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 CPU / 2 GB (reference, earlier run) | B0 | – | 2059 | 2496 | 2815 | – | – | 0/24 | 1.96 | 917 | 0 | see `baseline-syn24-b0` |
| 2 CPU / 2 GB (reference, earlier run) | Pecko | T0 (ears T2) | 835 | 1280 | 1376 | 1199 / 1472 / 837 | 24/24 | 0/24 | 1.20 | 846 | 0 | see `run-syn24-pecko-ram` |
| **1 CPU / 2 GB** | B0 | – | 2643 | 3455 | 3880 | – | – | 0/24 | 2.05 | 974 | 0 | 3490460 |
| **1 CPU / 2 GB** | Pecko | T0 fixed (ears T2) | 1027 | 1458 | 3598 | 1596 / 1985 / **−52** | 23/24 | 0/24 | 1.21 | 836 | 0 | d0810ac |
| **1 CPU / 2 GB** | Pecko | T2 (ladder for ~1 CPU) | 996 | 1302 | 1464 | 1787 / 2244 / 1174 | 24/24 | 0/24 | 0.95 | 817 | 0 | 3490460 |
| **1 CPU / 1.25 GiB** | B0 | – | 2745 | 3195 | 3272 | – | – | 0/24 | 2.00 | 891 | 0 | 3490460 |
| **1 CPU / 1.25 GiB** | Pecko | T0 fixed (ears T2) | 980 | 1481 | 1526 | 1734 / 2050 / 1074 | 24/24 | 0/24 | 1.16 | 837 | 0 | 3490460 |
| **1 CPU / 1.25 GiB** | Pecko | T2 (ladder) | 947 | 1256 | 1537 | 1751 / 2014 / 1130 | 24/24 | 0/24 | 0.96 | 801 | 0 | 3490460 |

**Going from 2 CPUs to 1 CPU (2 GB):** B0 p50 +584 ms (2059 → 2643), p90 +959 ms. Pecko T0 p50 +192 ms
(835 → 1027), p90 +178 ms; Pecko T2 p50 +161 ms, p90 +22 ms. Pecko degrades less than B0 in absolute ms, and
uses about half B0's CPU-seconds per turn at T2 (0.95 vs 2.05).

**Adaptive (T2) vs fixed (T0) at 1 CPU:** T2 is better on every column we measure: p90 1302 vs 1458 (2 GB) and
1256 vs 1481 (1.25 GiB), max 1464 vs 3598, CPU-s/turn −0.26, peak RAM −19 to −36 MiB. These are single runs and
the p50 differences (31–33 ms) are inside run-to-run noise, so we claim only the tail, CPU, and RAM differences. T2
answers with n_predict 25 and ctx 512, which gives shorter answers; we did not score answer quality here.

**The one loss (honest):** at 1 CPU / 2 GB, fixed T0, turn 5 ("why is the sky blue") Pecko took 3598 ms vs B0
3546 ms (−52 ms). Timeline from `deg-1cpu-pecko-t0/events.jsonl`: the held chunk seq 0 ("The sky appears blue
because", 5 words) reached Voice at +300 ms after commit, but the next chunk did not arrive until +2803 ms. Voice
synthesized the merged clause only then (503 ms, lessac-medium) and first audio was at +3307 ms after endpoint. At T2
the same turn had first audio at +1005 ms. Cause of the 2.5 s gap between chunks: not diagnosed.

**Memory cap did not bind:** both stacks peak below 1 GiB (801–974 MiB), so 1.25 GiB caused no OOM and no
failures. A cap near ~0.9 GiB would be the next test (not run). B0 peaked at 974 MiB in one run and 891 MiB in the
other with the same code, so expect about ±40 MiB run-to-run variation in peak RAM.

## Tier switch (Ears only), `scripts/test_tier_switch.py`, 1 CPU / 2 GB scope on CPU 4, HEAD 3490460
Moonshine Small (T0) load 2.717 s, peak RSS during load 499.4 MB; T0→T1 (Moonshine Tiny) switch 1.432 s, peak RSS
during switch 646.1 MB. **Caveat:** both T0 and T1 transcripts of q01.wav came out empty (script's own sanity check
reports False), so the swap is timed but not validated as working. This covers Ears only, not a whole-stack tier
switch. Output: `deg-tier-switch/stdout.log`.

## Exact commands (repo root)
```
# 1 CPU / 2 GB
PECKO_CPUS=4 PECKO_MEM=2G scripts/run_pecko.sh --wav data/clips/synthetic24/q*.wav --ears-tier 2 --no-audio --port 8181 --out data/results/deg-1cpu-pecko-t0
PECKO_CPUS=4 PECKO_MEM=2G scripts/run_baseline.sh --wav data/clips/synthetic24/q*.wav --port 8191 --out data/results/deg-1cpu-b0
PECKO_CPUS=4 PECKO_MEM=2G scripts/run_pecko.sh --wav data/clips/synthetic24/q*.wav --tier 2 --no-audio --port 8181 --out data/results/deg-1cpu-pecko-t2
# 1 CPU / 1.25 GiB (1280M)
PECKO_CPUS=4 PECKO_MEM=1280M scripts/run_baseline.sh --wav data/clips/synthetic24/q*.wav --port 8191 --out data/results/deg-1cpu-1g25-b0
PECKO_CPUS=4 PECKO_MEM=1280M scripts/run_pecko.sh --wav data/clips/synthetic24/q*.wav --ears-tier 2 --no-audio --port 8181 --out data/results/deg-1cpu-1g25-pecko-t0
PECKO_CPUS=4 PECKO_MEM=1280M scripts/run_pecko.sh --wav data/clips/synthetic24/q*.wav --tier 2 --no-audio --port 8181 --out data/results/deg-1cpu-1g25-pecko-t2
# compare
.venv/bin/python scripts/compare_runs.py data/results/deg-1cpu-pecko-t0 data/results/deg-1cpu-b0   # etc., outputs in each pecko dir
# tier switch
systemd-run --user --scope -p CPUQuota=100% -p MemoryMax=2G -p MemorySwapMax=0 -- taskset -c 4 .venv/bin/python scripts/test_tier_switch.py data/clips/synthetic24/q01.wav
```
Ports 8181/8191 (not the default 8080/8090) were used only to avoid clashing with a concurrent ablation worker on
CPUs 2,3. The port has no effect on the measurement.

## Caveats
- **VM** (VirtualBox Ubuntu guest; `systemd-detect-virt` = oracle), not bare metal. Another worker ran ablations on
  CPUs 2,3 at the same time. Our runs were pinned to CPU 4, but the host may share caches and memory bandwidth.
- **Synthetic speech** (TTS-generated questions), 24 turns, **one run per row**. Not a held-out human set.
- p50/p90 are nearest-rank over 24 turns, so p90 is set by about the 22nd-ranked turn. Treat ±50 ms as noise.
- The 2-CPU reference rows are from earlier runs (`run-syn24-pecko-ram`, `baseline-syn24-b0`, on CPUs 2,3) and
  are not in the same session.
- The repo's T2 brain uses Qwen3-0.6B (same as T0) with ctx 512 / n_predict 25 / 1 thread, not the 350M-class model
  the ladder table names. T2 Voice uses Piper lessac-low. On its first T2 run the lessac-low cache was synthesized
  at startup (181 clips, 10.5 s; startup_s 13.7). This is before `ready`, so it is not in the per-turn numbers.
- `--no-audio`: first audio = PCM handed to the output path (no speaker); the same definition was used for every Pecko row.
- Energy: not measured in these runs (J/turn n/a). No estimate is given.
- Git HEAD moved during the session (d0810ac → 3490460, the other worker's ablation flags with defaults
  unchanged); recorded per run in each `git_head.txt`.
