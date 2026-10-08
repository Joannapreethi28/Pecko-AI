import csv
import json
import sys

import pytest

from brain import bakeoff, score_sheet


def test_percentile_nearest_rank():
    xs = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert bakeoff.percentile(xs, 50) == 50
    assert bakeoff.percentile(xs, 90) == 90
    assert bakeoff.percentile(xs, 100) == 100
    assert bakeoff.percentile(list(reversed(xs)), 50) == 50     # order must not matter
    assert bakeoff.percentile([7], 90) == 7
    assert bakeoff.percentile([], 50) is None


def test_common_prefix_len():
    assert bakeoff.common_prefix_len([1, 2, 3, 4], [1, 2, 9]) == 2
    assert bakeoff.common_prefix_len([], [1]) == 0
    assert bakeoff.common_prefix_len([1, 2], [1, 2]) == 2


@pytest.mark.skipif(sys.platform != "win32", reason="windows-only expectation")
def test_cgroup_memory_peak_none_on_windows():
    assert bakeoff.cgroup_memory_peak() is None


def test_cgroup_memory_peak_reads_files(tmp_path):
    (tmp_path / "proc_cgroup").write_text("0::/user.slice/pecko.scope\n")
    d = tmp_path / "sys" / "user.slice" / "pecko.scope"
    d.mkdir(parents=True)
    (d / "memory.peak").write_text("123456789\n")
    got = bakeoff.cgroup_memory_peak(proc_cgroup=tmp_path / "proc_cgroup", sys_root=tmp_path / "sys")
    assert got == 123456789
    assert bakeoff.cgroup_memory_peak(proc_cgroup=tmp_path / "nope", sys_root=tmp_path) is None


def test_questions_file_has_20():
    qs = bakeoff.load_questions()
    assert len(qs) == 20
    assert len(set(qs)) == 20
    assert all(q == q.strip() and q for q in qs)


def test_summarize_and_row():
    q = [{"ttft_ms": 100 + 10 * i, "decode_tps": 20.0 + i, "cache_n": 50} for i in range(10)]
    rw = [{"ttft_ms": 80.0, "cache_n": 30, "lcp": 31}, {"ttft_ms": 90.0, "cache_n": 31, "lcp": 31}]
    s = bakeoff.summarize("m", q, rw, peak_rss_mb=512.0, cgroup_peak=None, platform_label="windows-dev, not judged")
    assert s["ttft_p50_ms"] == 140 and s["ttft_p90_ms"] == 180
    assert s["rewind_ttft_p50_ms"] == 80.0
    assert s["rewind_reprocesses"] is False          # cache_n >= lcp - 1 everywhere
    assert s["decode_tps_median"] == 24.5
    bad = bakeoff.summarize("m", q, [{"ttft_ms": 500, "cache_n": 5, "lcp": 31}], 1.0, None, "x")
    assert bad["rewind_reprocesses"] is True
    row = bakeoff.format_row(s)
    assert row.startswith("| m |") and "140" in row and "windows-dev, not judged" in row


def test_score_sheet_round_trip(tmp_path):
    for label in ("a", "b"):
        recs = [{"kind": "question", "question": f"q{i}", "reply": f"{label} reply {i}"} for i in range(3)]
        recs.append({"kind": "rewind", "ttft_ms": 1})
        (tmp_path / f"bakeoff_{label}.jsonl").write_text("\n".join(json.dumps(r) for r in recs))
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.csv"
    score_sheet.build([tmp_path / "bakeoff_a.jsonl", tmp_path / "bakeoff_b.jsonl"], sheet, key, seed=1)

    rows = list(csv.DictReader(open(sheet, encoding="utf-8")))
    assert len(rows) == 6
    assert set(rows[0]) == {"id", "question", "reply", "score"}      # no model name leaks into the sheet
    assert all("a reply" not in r["question"] for r in rows)

    keyrows = {r["id"]: r["label"] for r in csv.DictReader(open(key, encoding="utf-8"))}
    for r in rows:
        r["score"] = "5" if keyrows[r["id"]] == "a" else "3"
    with open(sheet, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    assert score_sheet.tally(sheet, key) == {"a": 5.0, "b": 3.0}


def test_score_sheet_ignores_unscored_and_rejects_bad(tmp_path):
    (tmp_path / "bakeoff_a.jsonl").write_text(json.dumps({"kind": "question", "question": "q", "reply": "r"}))
    sheet, key = tmp_path / "s.csv", tmp_path / "k.csv"
    score_sheet.build([tmp_path / "bakeoff_a.jsonl"], sheet, key, seed=0)
    assert score_sheet.tally(sheet, key) == {}                        # nothing scored yet
    rows = list(csv.DictReader(open(sheet, encoding="utf-8")))
    rows[0]["score"] = "9"
    with open(sheet, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(ValueError):
        score_sheet.tally(sheet, key)
