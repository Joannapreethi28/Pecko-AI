"""Brain model bake-off: TTFT, rewind behaviour, decode speed and peak RAM for one GGUF.

python -m brain.bakeoff --model models/<file>.gguf --family qwen3|lfm2 --label <label> [--port 8080]
Run it inside Spine's cap on the Ubuntu VM (see docs/superpowers/plans/2026-10-08-brain-stage.md, Task 9).
Numbers from any other machine are printed with the platform label so they cannot pass as judged.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from brain.llama_client import LlamaClient
from brain.llama_server import LlamaServer
from brain.prompt import PromptBuilder, normalize
from common.clock import now

QUESTIONS_PATH = Path(__file__).with_name("bakeoff_questions.txt")
N_PREDICT = 60
REWIND_RUNS = 5


def percentile(values, p: float):
    """Nearest-rank percentile (no interpolation): the value at rank ceil(p/100 * n)."""
    if not values:
        return None
    xs = sorted(values)
    return xs[max(1, math.ceil(p / 100.0 * len(xs))) - 1]


def common_prefix_len(a, b) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def load_questions(path: Path = QUESTIONS_PATH) -> list[str]:
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


def cgroup_memory_peak(proc_cgroup: Path = Path("/proc/self/cgroup"),
                       sys_root: Path = Path("/sys/fs/cgroup")) -> Optional[int]:
    """Peak bytes of the cgroup (v2) this process is in, or None (Windows, cgroup v1, no file)."""
    try:
        for line in Path(proc_cgroup).read_text().splitlines():
            if line.startswith("0::"):
                rel = line[3:].strip().lstrip("/")
                return int((Path(sys_root) / rel / "memory.peak").read_text().strip())
    except (OSError, ValueError):
        pass
    return None


class RssSampler:
    """Samples RSS of a process tree every 50 ms in a thread; .peak_mb is the max seen."""

    def __init__(self, pid: int, period: float = 0.05):
        self.pid, self.period, self.peak_mb = pid, period, 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import psutil
        try:
            proc = psutil.Process(self.pid)
        except psutil.Error:
            return
        while not self._stop.is_set():
            try:
                total = proc.memory_info().rss + sum(c.memory_info().rss for c in proc.children(recursive=True))
                self.peak_mb = max(self.peak_mb, total / 1e6)
            except psutil.Error:
                return
            self._stop.wait(self.period)

    def start(self):
        self._thread.start()
        return self

    def stop(self) -> float:
        self._stop.set()
        self._thread.join(timeout=2)
        return self.peak_mb


def platform_label() -> str:
    if sys.platform == "win32":
        return "windows-dev, not judged"
    return f"{platform.system().lower()} {platform.machine()}"


def summarize(label, questions, rewinds, peak_rss_mb, cgroup_peak, platform_label) -> dict:
    ttft = [r["ttft_ms"] for r in questions]
    tps = [r["decode_tps"] for r in questions if r["decode_tps"] > 0]
    peak_mb = cgroup_peak / 1e6 if cgroup_peak else peak_rss_mb
    return {
        "label": label,
        "n_questions": len(questions),
        "ttft_p50_ms": percentile(ttft, 50),
        "ttft_p90_ms": percentile(ttft, 90),
        "rewind_ttft_p50_ms": percentile([r["ttft_ms"] for r in rewinds], 50),
        # a rewind "reprocesses" if the server kept clearly less than the shared token prefix
        "rewind_reprocesses": any(r["cache_n"] < r["lcp"] - 1 for r in rewinds),
        "decode_tps_median": statistics.median(tps) if tps else None,
        "peak_rss_mb": round(peak_rss_mb, 1),
        "cgroup_peak_mb": round(cgroup_peak / 1e6, 1) if cgroup_peak else None,
        "peak_mb": round(peak_mb, 1),
        "platform": platform_label,
    }


def _f(x, nd=0):
    return "n/a" if x is None else f"{x:.{nd}f}"


def format_row(s: dict) -> str:
    """One RESULTS.md table row."""
    return (f"| {s['label']} | {_f(s['ttft_p50_ms'])} | {_f(s['ttft_p90_ms'])} | {_f(s['rewind_ttft_p50_ms'])} | "
            f"{'yes' if s['rewind_reprocesses'] else 'no'} | {_f(s['decode_tps_median'], 1)} | "
            f"{_f(s['peak_mb'])} | {s['platform']} |")


def _ttft_stream(client: LlamaClient, prompt: str, n_predict: int):
    """-> (ttft_ms, reply, Timings) for one streamed request."""
    t0 = now()
    ttft, parts, timings = None, [], None
    for piece in client.stream(prompt, n_predict=n_predict):
        if piece.text and ttft is None:
            ttft = (now() - t0) * 1000.0
        parts.append(piece.text)
        if piece.timings is not None:
            timings = piece.timings
    return (ttft if ttft is not None else (now() - t0) * 1000.0), "".join(parts), timings


def run(model: Path, family: str, label: str, port: int, out_dir: Path = Path("data/results")) -> dict:
    questions = load_questions()
    builder = PromptBuilder(family)            # never add_turn: every question is asked with no history
    client = LlamaClient(port=port)
    server = LlamaServer(model, port=port, log_path=out_dir / f"llama-server-{label}.log")
    start_s = server.start()
    sampler = RssSampler(server.pid).start()
    records = []
    try:
        client.prefill(builder.base())          # warm: system prompt now sits in the KV cache
        for i, q in enumerate(questions):
            ttft, reply, tm = _ttft_stream(client, builder.final(normalize(q)), N_PREDICT)
            records.append({"kind": "question", "i": i, "question": q, "reply": reply.strip(),
                            "ttft_ms": round(ttft, 1), "cache_n": tm.cache_n, "prompt_n": tm.prompt_n,
                            "decode_tps": round(tm.decode_tps, 2)})
        for k in range(REWIND_RUNS):            # early-prefill A, then the user "changes" to B
            a, b = normalize(questions[k]), normalize(questions[k + 5])
            pa, pb = builder.final(a), builder.final(b)
            client.prefill(pa)
            ttft, _, tm = _ttft_stream(client, pb, 4)
            lcp = common_prefix_len(client.tokenize(pa), client.tokenize(pb))
            records.append({"kind": "rewind", "k": k, "a": a, "b": b, "ttft_ms": round(ttft, 1),
                            "cache_n": tm.cache_n, "prompt_n": tm.prompt_n, "lcp": lcp})
    finally:
        peak_rss = sampler.stop()
        server.stop()
    qs = [r for r in records if r["kind"] == "question"]
    rw = [r for r in records if r["kind"] == "rewind"]
    summary = summarize(label, qs, rw, peak_rss, cgroup_memory_peak(), platform_label())
    summary["server_start_s"] = round(start_s, 2)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"bakeoff_{label}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    (out_dir / f"bakeoff_{label}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--family", choices=["qwen3", "lfm2"], default="qwen3")
    ap.add_argument("--label", required=True)
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    s = run(args.model, args.family, args.label, args.port)
    print("| model | TTFT p50 ms | TTFT p90 ms | rewind TTFT p50 ms | rewind reprocesses? | decode tok/s | peak RAM MB | platform |")
    print(format_row(s))
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
