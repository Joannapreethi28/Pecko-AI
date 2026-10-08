import json
import threading
import time

from common.clock import now
from common.log import EventLog


def test_now_is_monotonic_and_fine_grained():
    a, b = now(), now()
    assert b >= a
    info = time.get_clock_info("monotonic")
    assert info.resolution <= 0.001, f"clock too coarse for latency work: {info} (gotcha G8)"


def test_event_writes_one_json_line(tmp_path):
    p = tmp_path / "ev.jsonl"
    log = EventLog("brain", p)
    rec = log.event("first_token", 7, t=13.41, gen=2)
    log.close()
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"stage": "brain", "event": "first_token", "turn": 7,
                                    "t": 13.41, "extra": {"gen": 2}}
    assert rec["t"] == 13.41


def test_event_stamps_now_when_t_missing(tmp_path):
    log = EventLog("brain", tmp_path / "e.jsonl")
    before = now()
    rec = log.event("x", 1)
    after = now()
    log.close()
    assert before <= rec["t"] <= after


def test_threads_never_interleave_lines(tmp_path):
    p = tmp_path / "e.jsonl"
    log = EventLog("brain", p)

    def write(i):
        for k in range(200):
            log.event("e", i, k=k)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log.close()
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 800
    assert all(json.loads(line)["stage"] == "brain" for line in lines)


def test_creates_parent_dir(tmp_path):
    log = EventLog("brain", tmp_path / "a" / "b" / "e.jsonl")
    log.event("x", 0)
    log.close()
    assert (tmp_path / "a" / "b" / "e.jsonl").exists()


def test_keep_collects_records(tmp_path):
    log = EventLog("brain", tmp_path / "e.jsonl", keep=True)
    log.event("a", 1)
    log.event("b", 2)
    log.close()
    assert [r["event"] for r in log.records] == ["a", "b"]
