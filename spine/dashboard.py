"""Standalone HTML run dashboard and an external live terminal viewer."""

import argparse
from html import escape
import json
from pathlib import Path
import sys
import time
import unicodedata


def clean(value):
    return "".join(c for c in str(value) if not unicodedata.category(c).startswith("C"))


def display(value, suffix="", digits=3):
    return "Unavailable" if value is None else f"{value:.{digits}f}{suffix}"


class DashboardState:
    def __init__(self):
        self.state = "Waiting"
        self.turn = None
        self.transcript = ""
        self.tier = 0
        self.synthetic = False
        self.pressure = {}
        self.completed = self.failed = 0
        self.cache_hits = 0
        self.last_event = ""
        self.t_eos = {}      # real loop: turn -> end-of-speech time
        self.raw = {}        # real loop: turn -> {"C"/"R"/"first audio": t}
        self.path = ""

    def update(self, event):
        name, extra = event.get("event"), event.get("extra", {})
        self.last_event = clean(name)
        self.synthetic |= extra.get("synthetic") is True or name == "mock_run"
        if name == "case_start":
            self.turn, self.state = event["turn"], "Listening"
        elif name == "transcript":
            self.transcript = clean(extra.get("text", ""))
            self.state = "Thinking" if extra.get("final") else "Listening"
        elif name == "first_audio_out":
            self.state = "Speaking"
        elif name == "pressure":
            self.pressure = extra
        elif name == "tier_switch":
            self.tier = extra["tier"]
        elif name == "cache_hit":
            self.cache_hits += 1
        elif name == "turn_end":
            self.completed += int(extra.get("success") is True)
            self.failed += int(extra.get("success") is not True)
            self.state = "Idle"
        elif name == "run_abort":
            self.state = "Aborted"
        elif name == "run_end":
            self.state = "Aborted" if extra.get("aborted") else "Finished"
        # Real loop (spine.app) events
        elif name == "resources":
            self.pressure = {**self.pressure, "snapshot": extra, "delta": {"mean_cores": extra.get("mean_cores")}}
        elif name == "wake_detected":
            self.state = "Listening"
        elif name == "t_eos":
            self.turn, self.state = event.get("turn"), "Thinking"
            self.t_eos[event.get("turn")] = event["t"]
        elif name == "endpoint" and event.get("turn") not in self.t_eos and extra.get("delay_s") is not None:
            # some turns log no t_eos line; endpoint carries the delay since end of speech
            self.turn = event.get("turn")
            self.t_eos[self.turn] = event["t"] - extra["delay_s"]
        elif name == "asr_final":
            self.turn = event.get("turn")
            self.transcript = clean(extra.get("text", ""))
            self.state = "Thinking"
        elif name == "final_valid":
            self.path = clean(extra.get("path", ""))
        elif name in ("commit", "pcm_ready"):
            self._mark("C" if name == "commit" else "R", event)
        elif name == "turn_done":
            self.completed += 1
            self.state = "Idle"
        if name == "first_audio_out":
            self._mark("first audio", event)

    def _mark(self, key, event):
        self.raw.setdefault(event.get("turn"), {}).setdefault(key, event["t"])

    @property
    def marks(self):
        """Latest turn's C / R / first audio in ms after its end of speech."""
        t0, raw = self.t_eos.get(self.turn), self.raw.get(self.turn, {})
        if t0 is None:
            return {}
        return {k: (raw[k] - t0) * 1000 for k in ("C", "R", "first audio") if k in raw}

    def terminal(self):
        snap = self.pressure.get("snapshot") or {}
        delta = self.pressure.get("delta") or {}
        energy = self.pressure.get("energy") or {}
        memory = snap.get("memory_current")
        cap = snap.get("memory_max")
        return (f"PECKO  |  {'SYNTHETIC' if self.synthetic else 'LIVE LOG'}\n"
                f"{self.state}  |  turn {self.turn}  |  T{self.tier}\n"
                f"Transcript: {self.transcript}\n"
                f"CPU: {display(delta.get('mean_cores'), ' cores')}  "
                f"RAM: {display(None if memory is None else memory / 2**20, ' MiB')} / "
                f"{display(None if cap is None else cap / 2**20, ' MiB')}\n"
                f"Package energy: {display(energy.get('gross_j'), ' J')}\n"
                + (f"Last turn (ms after end of speech): " + "  ".join(f"{k} {v:.0f}" for k, v in self.marks.items())
                   + (f"  [{self.path}]" if self.path else "") + "\n" if self.marks else "")
                + f"Pipeline completions {self.completed}  |  failures {self.failed}  |  cache hits {self.cache_hits}\n")


def write_dashboard(output: Path, report: dict, events: list[dict], resources: dict | None = None):
    state = DashboardState()
    for event in events:
        state.update(event)
    rows = []
    for row in report["turns"]:
        commit, ready = row["commit_s"], row["pcm_ready_s"]
        high = max([v for v in (commit, ready, row["observed_first_audio_s"]) if v is not None] + [0.001])
        bars = ""
        for label, value, cls in (("Commit", commit, "commit"), ("PCM ready", ready, "ready")):
            width = min(100, max(0, (value or 0) / high * 100))
            bars += f'<div class="barrow"><span>{label}</span><div class="track"><div class="{cls}" style="width:{width:.2f}%"></div></div><b>{display(value, " s")}</b></div>'
        issues = ", ".join(row["issues"]) or "Complete trace"
        rows.append(f'<article><h3>{escape(clean(row["case_id"]))} <small>Turn {row["turn"]}</small></h3>{bars}'
                    f'<p>First content audio: {display(row["observed_first_audio_s"], " s")} · Gaps: {display(row["gap_s"], " s")}</p>'
                    f'<p class="muted">{escape(issues)}</p></article>')
    resources = resources or {}
    accounting = resources.get("accounting", {})
    energy = resources.get("energy", {})
    mode = "SYNTHETIC · NO HARDWARE RESULT" if report["synthetic"] else "RECORDED RUN · VERIFY EXPERIMENT CONDITIONS"
    headline = report["headline_latency_s"]
    html = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pecko · Run dashboard</title><style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif;background:#101820;color:#eef4f7}}body{{max-width:1080px;margin:0 auto;padding:40px 24px}}
h1{{font-size:42px;margin:8px 0}}h2{{font-size:22px}}h3{{font-size:17px}}small,.muted{{color:#a6bac5;font-weight:400}}small{{float:right}}
.badge{{color:#f5cc76;font-size:12px;letter-spacing:1.5px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:28px 0}}
.card,article{{background:#1a2833;border:1px solid #304451;border-radius:12px;padding:20px;margin-bottom:12px}}.card b{{display:block;font-size:26px;margin:8px 0}}
.barrow{{display:flex;align-items:center;gap:12px;margin:12px 0;font-size:13px}}.barrow span{{width:80px}}.barrow b{{width:110px;text-align:right}}.track{{height:12px;background:#304451;flex:1;border-radius:4px;overflow:hidden}}
.commit,.ready{{height:100%}}.commit{{background:#62c7c2}}.ready{{background:#94a7ff}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}footer{{color:#a6bac5;font-size:13px;margin-top:32px}}
</style><header><div class="badge">{mode}</div><h1>Pecko <span class="muted">/ Run review</span></h1>
<p>{escape(clean(report['run_id']))} · {escape(clean(report['platform']))} · {escape(clean(report['configuration']))}</p></header>
<section class="cards"><div class="card">Expected turns<b>{report['expected_turns']}</b>{report['failed_or_incomplete_turns']} failed/incomplete traces</div>
<div class="card">First-audio p50<b>{display(headline['p50'], ' s')}</b>p90 {display(headline['p90'], ' s')}</div>
<div class="card">CPU used<b>{display(accounting.get('cpu_s'), ' s')}</b>Includes Spine instrumentation</div>
<div class="card">Package energy<b>{display(energy.get('gross_j'), ' J')}</b>Whole packages, not cgroup-only</div></section>
<article><h2>Last state</h2><pre>{escape(state.terminal())}</pre></article>
<h2>Turn timing</h2><p class="muted">Times are relative to labelled speech end. Negative values indicate preparation before speech ended. Missing readings remain unavailable.</p>
{''.join(rows)}<footer>Commit and PCM-ready bars expose the later dependency. Failure timeout scores are separate from measured latency. Synthetic logs and incomplete runs cannot supply headline numbers. No external resources are loaded.</footer></html>'''
    output.write_text(html, encoding="utf-8")


class EventTail:
    def __init__(self, path):
        self.path, self.offset, self.pending = path, 0, b""

    def read(self):
        if not self.path.exists():
            return []
        if self.path.stat().st_size < self.offset:
            raise ValueError("Event log was truncated; restart the viewer")
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            chunk = stream.read()
            self.offset = stream.tell()
        lines = (self.pending + chunk).split(b"\n")
        self.pending = lines.pop()
        return [json.loads(line.decode("utf-8")) for line in lines if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    state, tail = DashboardState(), EventTail(args.events)
    try:
        while True:
            events = tail.read()
            for event in events:
                state.update(event)
            if events or not args.watch:
                if args.watch and sys.stdout.isatty():
                    print("\x1b[2J\x1b[H", end="")
                print(state.terminal(), flush=True)
            if not args.watch:
                break
            time.sleep(0.5)  # External viewer only, never the audio path.
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
