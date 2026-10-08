"""Measure the router on held-out phrasings: `python -m brain.eval_router [rows.jsonl]`.

Each row: {"text": ..., "expect": intent-name | null}. null = must go to the LLM.
  wrong       = routed to a different intent than expected
  false_hits  = expected null (LLM) but the router answered anyway
  hit_rate    = share of should-hit rows answered correctly (reported, not asserted)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from brain.prompt import normalize
from brain.router import Router

HELDOUT = Path(__file__).resolve().parent.parent / "tests" / "brain" / "data" / "router_heldout.jsonl"


def evaluate(router: Router, rows: list[dict]) -> dict:
    should_hit = correct = wrong = false_hits = should_miss = 0
    errors: list[dict] = []
    for row in rows:
        r = router.route(normalize(row["text"]))
        hit = r.kind != "llm"
        if row["expect"] is None:
            should_miss += 1
            if hit:
                false_hits += 1
                errors.append({"text": row["text"], "got": r.intent, "expect": None})
        else:
            should_hit += 1
            if hit and r.intent == row["expect"]:
                correct += 1
            elif hit:
                wrong += 1
                errors.append({"text": row["text"], "got": r.intent, "expect": row["expect"]})
    return {
        "n": len(rows),
        "should_hit": should_hit,
        "should_miss": should_miss,
        "correct": correct,
        "wrong": wrong,
        "false_hits": false_hits,
        "hit_rate": correct / should_hit if should_hit else 0.0,
        "false_hit_rate": false_hits / should_miss if should_miss else 0.0,
        "errors": errors,
    }


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else HELDOUT
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    res = evaluate(Router.load(), rows)
    print(f"router held-out: n={res['n']} (should-hit {res['should_hit']}, should-miss {res['should_miss']})")
    print(f"hit rate {res['hit_rate']:.1%} ({res['correct']}/{res['should_hit']}), wrong {res['wrong']}")
    print(f"false-hit rate {res['false_hit_rate']:.1%} ({res['false_hits']}/{res['should_miss']})")
    for e in res["errors"]:
        print("  ERROR", e)
    return 1 if res["wrong"] or res["false_hits"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
