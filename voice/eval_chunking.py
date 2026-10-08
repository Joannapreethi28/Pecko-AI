"""Chunking ablation, master-ablation row A4 (solution.md §7, V8 "chunking is a decision"). No audio is played.

    python -m voice.eval_chunking
    python -m voice.eval_chunking --tag ubuntu-cap

Policies (voice/text.py PhraseChunker): word (every word; the known failure case) · comma · sentence · adaptive (shipped).
For every reply, Brain words arrive at t_i = ttft + i·word_s after acoustic end (two Brain profiles below). Each phrase
the policy cuts is synthesized FOR REAL by the T0 engine (1 thread, cache off) to get its synthesis time T_k and audio
length D_k; one synthesis lane: F_k = max(text_ready_k, F_{k-1}) + T_k. Playback is greedy (a phrase plays as soon as it
is ready, never before commit C): first audio P_1 = max(C, F_1) + d; gaps and the earliest gap-free start come from
Spine's verified primitives in spine/research/latency_v2/spine_latency_core.py (playback_gaps, playback_start).
"""
import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

from .engine import OUT_SR, TIERS, finish_clip, make_engine
from .text import PhraseChunker, normalize

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "spine" / "research" / "latency_v2"))
from spine_latency_core import playback_gaps, playback_start  # noqa: E402

BRAIN = {  # (ttft s, seconds per word)
    "brain-measured": (0.13, 0.037),   # brain/handoff_brain.md: first_token 110-157 ms, 32-37 tok/s (windows-dev)
    "brain-slow (assumed)": (0.30, 0.08),  # ASSUMPTION for a contended 2-CPU cap; replace with the Ubuntu number
}
COMMIT = 0.40          # C after acoustic end (Ears endpoint + ASR target, solution.md §6)
LONG = ["Sure. The train leaves at nine, it takes about four hours, and you should book a window seat on the left side.",
        "Here is the short version. Plants take in sunlight, water and air, and turn them into sugar, which feeds the whole plant.",
        "I'm not sure about today, but in general the museum opens at ten, closes at six, and stays open late on Fridays.",
        "Good question. Most phones last a full day, but heavy video, games and navigation can drain the battery by evening."]


def simulate(text, policy, ttft, word_s, synth, d):
    words = text.split()
    F, D, ready_text, phrases, Ts = [], [], [], [], []

    def buffered_ms(t):                           # audio synthesized by t and not yet played (greedy schedule)
        done = [(f, dd) for f, dd in zip(F, D) if f <= t]
        if not done:
            return 0.0
        p, end = None, None
        for f, dd in done:
            p = max(COMMIT, f) + d if p is None else max(f + d, end)
            end = p + dd
        return max(0.0, end - max(t, done[0][0])) * 1000

    now = [0.0]
    ch = PhraseChunker(lambda: buffered_ms(now[0]), policy=policy)

    def add(ps, t):
        for p in ps:
            T, dur = synth(p)
            start = max(t, F[-1] if F else 0.0)
            F.append(start + T)
            Ts.append(T)
            D.append(dur)
            ready_text.append(t)
            phrases.append(p)

    for i, w in enumerate(words):
        now[0] = ttft + i * word_s
        add(ch.feed(w + " "), now[0])
    add(ch.flush(), now[0])
    first = max(COMMIT, F[0]) + d
    gaps = playback_gaps(F, D, first, output_delay=d)
    return {"first_audio_ms": first * 1000, "gap_ms": sum(gaps[1:]) * 1000, "gaps": sum(1 for g in gaps[1:] if g > 0.005),
            "gapfree_start_ms": playback_start(F, D, commit=COMMIT, output_delay=d) * 1000,
            "phrases": len(phrases), "synth_s": sum(Ts), "words_per_phrase": len(words) / len(phrases), "first_phrase": phrases[0]}


def main():
    ap = argparse.ArgumentParser(prog="python -m voice.eval_chunking")
    ap.add_argument("--tag", default=f"{platform.system().lower()}-dev")
    ap.add_argument("--device-ms", type=float, default=0.0, help="audio output delay d added to every start")
    a = ap.parse_args()
    replies = [l.strip() for l in (ROOT / "voice" / "sentences.txt").read_text(encoding="utf-8").splitlines() if l.strip()] + LONG
    eng = make_engine(TIERS[0]["engine"])
    memo = {}

    def synth(phrase):                             # real synthesis time, measured once per distinct phrase
        if phrase not in memo:
            t = time.perf_counter()
            pcm = finish_clip(eng.synth(normalize(phrase)), phrase)
            memo[phrase] = (time.perf_counter() - t, len(pcm) / OUT_SR)
        return memo[phrase]

    d = a.device_ms / 1000
    results = {}
    for bname, (ttft, ws) in BRAIN.items():
        for pol in PhraseChunker.POLICIES[::-1]:
            rows = [simulate(r, pol, ttft, ws, synth, d) for r in replies]
            fa = sorted(x["first_audio_ms"] for x in rows)
            results[(bname, pol)] = {
                "first_p50": statistics.median(fa), "first_p90": fa[min(len(fa) - 1, round(0.9 * (len(fa) - 1)))],
                "gap_total_ms": sum(x["gap_ms"] for x in rows), "turns_with_gaps": sum(1 for x in rows if x["gaps"]),
                "gaps": sum(x["gaps"] for x in rows), "synth_calls": sum(x["phrases"] for x in rows),
                "synth_s": sum(x["synth_s"] for x in rows),
                "words_per_phrase": statistics.mean(x["words_per_phrase"] for x in rows), "n": len(rows)}
            r = results[(bname, pol)]
            print(f"  {bname:22s} {pol:9s} first audio p50 {r['first_p50']:5.0f} / p90 {r['first_p90']:5.0f} ms · gaps "
                  f"{r['turns_with_gaps']}/{r['n']} turns, {r['gap_total_ms']:6.0f} ms total · synth calls {r['synth_calls']:3d} "
                  f"({r['synth_s']:.1f} s) · "
                  f"{r['words_per_phrase']:.1f} words/phrase")
    out = ROOT / "data" / "results" / f"voice_chunking_{a.tag}.json"
    out.write_text(json.dumps({f"{b}|{p}": v for (b, p), v in results.items()}, indent=1), encoding="utf-8")
    md = [f"## Chunking ablation (A4) · {a.tag} · {time.strftime('%Y-%m-%d %H:%M')}",
          f"{len(replies)} replies (voice/sentences.txt + 4 long ones). Brain words arrive at ttft + i·word_s; every phrase "
          f"synthesized for real by {TIERS[0]['engine'].replace('vits-piper-en_US-', '')} (1 thread, cache off); one synthesis lane; "
          f"greedy playback never before commit C = {COMMIT * 1000:.0f} ms; device delay d = {a.device_ms:.0f} ms. Gaps via Spine's "
          "`playback_gaps`. First audio is measured from acoustic end.", "",
          "| Brain profile | Policy | first audio p50 / p90 ms | turns with gaps | total gap ms | synth calls | synth CPU s | words / phrase |",
          "|---|---|---|---|---|---|---|---|"]
    for (b, p), r in results.items():
        md.append(f"| {b} | {'**' + p + '**' if p == 'adaptive' else p} | {r['first_p50']:.0f} / {r['first_p90']:.0f} | "
                  f"{r['turns_with_gaps']}/{r['n']} | {r['gap_total_ms']:.0f} | {r['synth_calls']} | {r['synth_s']:.1f} | {r['words_per_phrase']:.1f} |")
    res = ROOT / "voice" / "RESULTS.md"
    txt = res.read_text(encoding="utf-8")
    i = txt.find("## Chunking ablation")
    j = txt.find("\n## ", i + 1) if i >= 0 else -1
    txt = (txt[:i] + (txt[j + 1:] if j >= 0 else "")).rstrip() + "\n" if i >= 0 else txt.rstrip() + "\n"
    res.write_text(txt + "\n" + "\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
