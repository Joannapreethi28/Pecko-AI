"""Build the evaluator UI's data from committed component results.

Run from any directory: python frontend/build_evidence.py
No engine, network, model weights or third-party dependencies are needed.
"""

import ast
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).with_name("evidence.json")


def reject_constant(value):
    raise ValueError(f"non-finite JSON value {value}")


def read_json(path):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"), parse_constant=reject_constant)
    except (OSError, ValueError) as error:
        raise ValueError(f"{path}: {error}") from error


def read_jsonl(path):
    rows = []
    for number, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line, parse_constant=reject_constant))
            except ValueError as error:
                raise ValueError(f"{path}:{number}: {error}") from error
    return rows


def require_metrics(data, path, fields):
    for field in fields:
        value = data.get(field) if isinstance(data, dict) else None
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{path}: {field} must be a finite, non-negative number")


def sample_text():
    """Read the benchmark's recorded sentence without importing engine dependencies."""
    tree = ast.parse((ROOT / "voice/bench.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SAMPLE_TEXT" for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("voice/bench.py no longer declares SAMPLE_TEXT")


def build_evidence():
    model_specs = [
        ("qwen3-0.6b-q4km", "Qwen3 0.6B", "Q4_K_M", True),
        ("qwen3-1.7b-q4km", "Qwen3 1.7B", "Q4_K_M", False),
        ("lfm2.5-1.2b-q40", "LFM2.5 1.2B", "Q4_0", False),
        ("lfm2.5-350m-q40", "LFM2.5 350M", "Q4_0", False),
    ]
    sources = []

    def source(name, path, kind):
        if not (ROOT / path).is_file():
            raise FileNotFoundError(path)
        if not any(item["path"] == path for item in sources):
            sources.append({"name": name, "path": path, "kind": kind})
        return path

    models = []
    for model_id, name, quantization, selected in model_specs:
        path = source(name + " benchmark", f"data/results/bakeoff_{model_id}-ubuntu-vm-cg_summary.json", "measured")
        data = read_json(path)
        require_metrics(data, path, ("ttft_p50_ms", "ttft_p90_ms", "decode_tps_median", "peak_mb", "n_questions"))
        if type(data["n_questions"]) is not int or data["n_questions"] < 1 or data["ttft_p50_ms"] > data["ttft_p90_ms"]:
            raise ValueError(f"{path}: invalid question count or percentile order")
        models.append({
            "id": model_id,
            "name": name,
            "quantization": quantization,
            "ttft_p50_ms": data["ttft_p50_ms"],
            "ttft_p90_ms": data["ttft_p90_ms"],
            "decode_tps": data["decode_tps_median"],
            "peak_memory_mb": data["peak_mb"],
            "turns": data["n_questions"],
            "selected": selected,
            "rewind_reprocesses": data["rewind_reprocesses"],
            "source": path,
        })

    cache_source = source("Voice cache ablation", "data/results/voice_cache_windows-dev.json", "measured")
    cache_data = read_json(cache_source)
    cache_full = cache_data["results"]["L2+L3+L4+C (full)"]["pass1"]
    cache_baseline = cache_data["results"]["no cache"]["pass1"]
    for row in (cache_full, cache_baseline):
        require_metrics(row, cache_source, ("turns", "R_p50_ms", "R_p90_ms", "cpu_ms_per_turn"))
    hit_count, turn_count = map(int, cache_full["first_pcm_from_cache"].split("/"))
    if not (0 <= hit_count <= turn_count and turn_count > 0 and turn_count == cache_full["turns"] == cache_baseline["turns"]):
        raise ValueError(f"{cache_source}: inconsistent cache hit or comparison turn counts")
    if cache_baseline["cpu_ms_per_turn"] <= 0:
        raise ValueError(f"{cache_source}: baseline CPU time must be positive")
    chunk_source = source("Voice chunking experiment", "data/results/voice_chunking_windows-dev.json", "component-simulation")
    chunk_data = read_json(chunk_source)
    for policy in ("word", "sentence", "comma", "adaptive"):
        require_metrics(chunk_data[f"brain-measured|{policy}"], chunk_source, ("first_p50", "first_p90", "synth_calls", "n", "turns_with_gaps"))
    tier_source = source("Voice resource ladder", "data/results/voice_tiers_windows-dev.json", "measured")
    tier_data = read_json(tier_source)
    if [row["tier"] for row in tier_data["rows"][:4]] != [0, 1, 2, 3]:
        raise ValueError(f"{tier_source}: expected one initial row for each tier T0 through T3")
    for row in tier_data["rows"][:4]:
        require_metrics(row, tier_source, ("rss_after_mb", "uncached_8w_ms"))
    source("Voice benchmark conditions", "voice/RESULTS.md", "documentation")
    source("Brain benchmark conditions", "brain/RESULTS.md", "documentation")
    voice = {
        "label": "Windows component measurements",
        "summary": "Recorded Piper speech, cache reuse and a working voice resource ladder.",
        "cache": {
            "turns": cache_full["turns"],
            "first_pcm_from_cache": cache_full["first_pcm_from_cache"],
            "cache_hit_percent": round(hit_count / turn_count * 100, 1),
            "p50_ms": cache_full["R_p50_ms"],
            "p90_ms": cache_full["R_p90_ms"],
            "cpu_ms_per_turn": cache_full["cpu_ms_per_turn"],
            "baseline_cpu_ms_per_turn": cache_baseline["cpu_ms_per_turn"],
            "baseline_p50_ms": cache_baseline["R_p50_ms"],
            "baseline_p90_ms": cache_baseline["R_p90_ms"],
            "cpu_reduction_percent": round((1 - cache_full["cpu_ms_per_turn"] / cache_baseline["cpu_ms_per_turn"]) * 100, 1),
            "false_router_hits": cache_data["router"]["false_hits"],
            "router_miss_cases": cache_data["router"]["should_miss"],
            "source": cache_source,
            "caveat": "First pass: 39 unseen questions. Time is chunk received to first PCM ready; no speaker/device delay. Windows development machine, outside the judged cgroup.",
        },
        "chunking": [{
            "policy": policy,
            "p50_ms": row["first_p50"],
            "p90_ms": row["first_p90"],
            "synth_calls": row["synth_calls"],
            "turns": row["n"],
            "turns_with_gaps": row["turns_with_gaps"],
            "source": chunk_source,
        } for policy in ("word", "sentence", "comma", "adaptive") for row in [chunk_data[f"brain-measured|{policy}"]]],
        "chunking_caveat": "Real TTS synthesis with simulated Brain word arrivals, a fixed 400 ms commit gate and no device delay. This is a component experiment, not an end-to-end conversation benchmark.",
        "tiers": [{
            "tier": row["tier"],
            "engine": row["engine"],
            "memory_mb": row["rss_after_mb"],
            "phrase_ms": row["uncached_8w_ms"],
            "switch_ms": row["switch_ms"],
            "source": tier_source,
        } for row in tier_data["rows"][:4]],
        "tiers_caveat": "Whole Python process RSS with silent NullPlayer on Windows; each phrase has eight words. Switches happen between turns.",
        "sources": [cache_source, chunk_source, tier_source, "voice/RESULTS.md"],
        "caveat": "Voice component evidence comes from Windows development runs. Ubuntu capped whole-stack latency, memory and energy remain unmeasured.",
    }

    sentence = sample_text()
    samples = []
    for pack, name in [
        ("medium", "Lessac medium · fp32"),
        ("low", "Lessac low · fp32"),
        ("high", "Lessac high · fp32"),
        ("medium-int8", "Lessac medium · int8"),
        ("low-int8", "Lessac low · int8"),
        ("high-fp16", "Lessac high · fp16"),
        ("high-int8", "Lessac high · int8"),
    ]:
        path = source(name + " audio", f"data/results/voice_samples/vits-piper-en_US-lessac-{pack}.wav", "recorded-audio")
        samples.append({"name": name, "description": sentence, "url": f"/source/{path}", "source": path})

    plan_path = source("Contract replay scenarios", "data/results/mock-placeholder-runtime-20261008-02/plan.json", "synthetic")
    trace_path = source("Recorded contract trace", "data/results/mock-placeholder-runtime-20261008-02/events.jsonl", "synthetic")
    report_path = source("Contract replay report", "data/results/mock-placeholder-runtime-20261008-02/report.json", "synthetic")
    plan = read_json(plan_path)
    report = read_json(report_path)
    trace = read_jsonl(trace_path)
    if plan.get("synthetic") is not True or report.get("synthetic") is not True or report.get("headline_ready") is not False:
        raise ValueError("Contract replay sources no longer describe a non-headline synthetic run")
    replay = {
        "label": "Recorded contract replay",
        "synthetic": True,
        "source": trace_path,
        "plan_source": plan_path,
        "report_source": report_path,
        "caveat": "Placeholder engines demonstrate event routing, cancellation and commit checks. This trace produced no audible speech; its timing is not a voice benchmark.",
        "turns": [{
            "id": index,
            "label": case["case_id"].replace("-", " ").capitalize(),
            "text": case.get("text") or next((event["text"] for event in reversed(case.get("script", [])) if event.get("type") == "final"), ""),
            "events": case.get("script", []),
            "trace": [event for event in trace if event.get("turn") == index],
        } for index, case in enumerate(plan["cases"])],
        "events": trace,
        "headline_ready": report["headline_ready"],
    }

    source("Project overview", "README.md", "documentation")
    source("Architecture and critical-path design", "docs/solution.md", "documentation")
    source("Message contract", "docs/CONTRACT.md", "documentation")
    source("Spine implementation status", "spine/BUILD_STATUS.md", "documentation")
    source("Voice implementation and setup", "voice/README.md", "documentation")
    source("Brain implementation handoff", "brain/handoff_brain.md", "documentation")
    source("Speech recognition specification", "ears/SPEC.md", "documentation")
    source("Phone target specification", "mobile/SPEC.md", "documentation")

    return {
        "schema_version": 1,
        "title": "Pecko evaluator console",
        "provenance": "Generated from committed repository results by frontend/build_evidence.py.",
        "models": models,
        "model_conditions": {
            "label": "Brain only · Ubuntu VM · 2 CPU / 2 GB cgroup",
            "summary": "Twenty questions per model; CPU, memory and swap caps verified in the benchmark scope. Network was not disabled during these runs. Quality scores are pending; the selected model is provisional.",
            "source": "brain/RESULTS.md",
        },
        "voice": voice,
        "samples": samples,
        "replay": replay,
        "sources": sources,
        "capabilities": [
            {"name": "Intent routing", "status": "implemented", "detail": "Common requests use cached intents; time and date are composed locally. Other questions need a local language model.", "source": "brain/handoff_brain.md"},
            {"name": "Brain", "status": "component-measured", "detail": "Four local language models benchmarked under an Ubuntu 2 CPU / 2 GB cap. Qwen3 0.6B is the provisional choice.", "source": "brain/RESULTS.md"},
            {"name": "Voice", "status": "component-measured", "detail": "Piper synthesis, held speech, caching and resource tiers implemented. Recorded samples and Windows component results are available.", "source": "voice/README.md"},
            {"name": "Spine", "status": "synthetic-verified", "detail": "Event bus, exact-token commit validation, cancellation and experiment tooling verified with placeholder runs.", "source": "spine/BUILD_STATUS.md"},
            {"name": "Ears", "status": "planned", "detail": "Speech recognition and microphone input are specified; this checkout contains no Ears engine implementation.", "source": "ears/SPEC.md"},
            {"name": "Phone", "status": "planned", "detail": "Android profile is a target; phone integration is not demonstrated in this checkout.", "source": "mobile/SPEC.md"},
            {"name": "End-to-end benchmark", "status": "pending", "detail": "A real full voice loop, paired baseline and whole-stack energy measurements remain pending.", "source": "spine/BUILD_STATUS.md"},
        ],
    }


def main():
    try:
        evidence = build_evidence()
        payload = json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        raise SystemExit(f"Evidence build failed; existing evidence.json was not changed. {error}") from error
    OUTPUT.write_text(payload, encoding="utf-8")
    print(f"Built {OUTPUT.name}: {len(evidence['models'])} model results, {len(evidence['samples'])} audio samples, {len(evidence['sources'])} sources.")


if __name__ == "__main__":
    main()
