"""Blind quality scoring for the bake-off.

python -m brain.score_sheet --build data/results/bakeoff_*.jsonl   # writes blind_scores.csv + blind_scores_key.csv
(teammate fills the `score` column, 1-5, without seeing which model wrote which reply)
python -m brain.score_sheet --tally                                # mean score per model
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

SHEET = Path("data/results/blind_scores.csv")
KEY = Path("data/results/blind_scores_key.csv")


def build(jsonl_paths, sheet: Path = SHEET, key: Path = KEY, seed: int | None = None) -> int:
    items = []
    for p in map(Path, jsonl_paths):
        label = p.stem.removeprefix("bakeoff_")
        for line in p.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line) if line.strip() else {}
            if rec.get("kind") == "question":
                items.append((label, rec["question"], rec["reply"]))
    random.Random(seed).shuffle(items)
    sheet.parent.mkdir(parents=True, exist_ok=True)
    with open(sheet, "w", newline="", encoding="utf-8") as fs, open(key, "w", newline="", encoding="utf-8") as fk:
        ws, wk = csv.writer(fs), csv.writer(fk)
        ws.writerow(["id", "question", "reply", "score"])
        wk.writerow(["id", "label"])
        for n, (label, q, reply) in enumerate(items, 1):
            ws.writerow([n, q, reply, ""])
            wk.writerow([n, label])
    return len(items)


def tally(sheet: Path = SHEET, key: Path = KEY) -> dict:
    """Mean score per model over the rows that have a score. Scores must be integers 1-5."""
    labels = {r["id"]: r["label"] for r in csv.DictReader(open(key, encoding="utf-8"))}
    scores: dict[str, list[int]] = {}
    for r in csv.DictReader(open(sheet, encoding="utf-8")):
        raw = (r["score"] or "").strip()
        if not raw:
            continue
        if raw not in {"1", "2", "3", "4", "5"}:
            raise ValueError(f"row {r['id']}: score must be 1-5, got {raw!r}")
        scores.setdefault(labels[r["id"]], []).append(int(raw))
    return {label: sum(v) / len(v) for label, v in scores.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", nargs="+", metavar="JSONL")
    ap.add_argument("--tally", action="store_true")
    args = ap.parse_args()
    if args.build:
        print(f"wrote {build(args.build)} rows to {SHEET} (key: {KEY}; do not show the key to the scorer)")
    if args.tally:
        for label, mean in sorted(tally().items(), key=lambda kv: -kv[1]):
            print(f"{label}: {mean:.2f}")


if __name__ == "__main__":
    main()
