# Brain Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Compact by request (16.5 h left, save tokens):** every task gives exact files, interfaces, the tests to write (names + what they assert) and full code for the non-obvious parts. Obvious glue is described in one line. TDD still applies: write the listed tests first, see them fail, then implement.

**Goal:** a Brain stage that turns Ears `partial`/`tentative_final`/`final` into short speakable `chunk`s for Voice as fast as possible, with a cached system prompt, early prefill, a router for common intents, tiers, and measured numbers.

**Architecture:** `llama-server` (llama.cpp b11501, CPU) runs as its own process, one slot. `BrainStage` (Python) builds byte-stable ChatML prompts itself and calls `/completion` (stdlib `http.client`, SSE streaming). `feed()` only queues jobs; one worker thread talks to the server, so Brain never has more than one busy thread. Pure logic (chunker, speakable filter, prompt builder, router) is separate, unit-tested, and runs on Windows dev and Ubuntu alike.

**Tech Stack:** Python 3.13 (Windows dev) / 3.10+ (Ubuntu VM), llama.cpp b11501, Qwen3-0.6B GGUF (unsloth), pytest, rapidfuzz, pyyaml, psutil.

**Spec:** `brain/SPEC.md` (+ `docs/CONTRACT.md`, `docs/solution.md` §1, §3, §5, §7). Mistakes log: `brain/gotcha.md`.

## Global Constraints
- Contract v2 message shapes exactly as `docs/CONTRACT.md`; times = `common.clock.now()` (`time.monotonic()` seconds).
- Log line: `{"stage":"brain","event":...,"turn":N,"t":...,"extra":{...}}`; required events `prompt_ready`, `first_token`, `first_chunk`, `cache_hit`. Non-turn events use `turn: -1`.
- System prompt ≤ 150 tokens, **byte-identical every turn**, warmed in `start()`. Thinking **off** (empty `<think>\n\n</think>\n\n` block pre-filled).
- Server flags: `-c 2048 -np 1 -t 1 -tb 2 -ctk q8_0 -ctv q8_0 --host 127.0.0.1` (+ `-fa on` only if the probe in Task 4 shows quantized V cache needs it).
- Nothing audible before `final` (chunks only after `final`, or `held:true` in Task 11).
- No network at runtime; models in `models/` (gitignored); llama.cpp binaries in `models/llama.cpp/b11501-*/`.
- Windows numbers are labelled `windows-dev, not judged`. Judged numbers come from the **Ubuntu VM under the cgroup** only.
- Work on `main` (team decision 8 Oct). Brain edits only `brain/`, `tests/brain/`; shared files touched: `common/clock.py`, `common/log.py`, `pyproject.toml` (pytest config only). Commit small; `git pull --rebase` before `git push`; never force-push.
- Python packages: `brain/requirements.txt`. Windows venv must be Python 3.13 (gotcha G8).

## Review Focus
1. **Ears casing vs `stable`**: `final.text` is cased ("What is the capital of France?") but `stable` is lowercase. Brain must build the user turn only from normalized text (`normalize(stable)`, `normalize(tentative_final.text)`, `normalize(final.norm or final.text)`) so the early-prefill prompt is a byte prefix of the final prompt. Test in Task 3 + Task 7.
2. **Unspeakable output**: model emits `<think>`, markdown, emoji, URLs, `&`. Nothing of that reaches Voice, even when a tag is split across pieces. Tests in Task 2 + Task 5.
3. **Numbers/times**: `3.5`, `1,000`, `3:45`, `x.y` never split into separate chunks. Tests in Task 2.
4. **Cancel races**: `barge_in`, Voice `cancel{gen}`, or a new `final` while a reply streams → the old gen stops within one token and emits nothing more; the next turn still works. Test in Task 5.
5. **Server down / HTTP error mid-reply / empty reply** → user still hears one fallback sentence (`last:true`), `llm_error` logged, worker keeps running. Test in Task 5.

## Environment (done 8 Oct on Windows; repeat on the Ubuntu VM)
Windows (done): `py -3.13 -m venv .venv`, `pip install -r brain/requirements.txt`, llama.cpp `llama-b11501-bin-win-cpu-x64.zip` → `models/llama.cpp/b11501-win/`, `hf download unsloth/Qwen3-0.6B-GGUF Qwen3-0.6B-Q4_K_M.gguf Qwen3-0.6B-Q8_0.gguf --local-dir models`.

Ubuntu VM (do once, inside the VM, from a `git clone` — **not** a shared folder):
```bash
sudo apt-get install -y python3-venv python3-pip git curl unzip gh
grep -o -m1 avx2 /proc/cpuinfo || echo "NO AVX2: fix VM CPU settings before benchmarking"   # gotcha G9
python3 -m venv .venv && . .venv/bin/activate && pip install -r brain/requirements.txt
mkdir -p models/llama.cpp && cd models/llama.cpp
gh release download b11501 -R ggml-org/llama.cpp -p "llama-b11501-bin-ubuntu-x64.tar.gz"
mkdir b11501-ubuntu && tar xzf llama-b11501-bin-ubuntu-x64.tar.gz -C b11501-ubuntu && cd ../..
hf download unsloth/Qwen3-0.6B-GGUF Qwen3-0.6B-Q4_K_M.gguf Qwen3-0.6B-Q8_0.gguf --local-dir models
sha256sum models/*.gguf   # paste into brain/RESULTS.md header
```

## Waves (what runs in parallel)
- **Wave A (me, ~15 min):** Task 1.
- **Wave B (parallel, 4 workers, no shared files):** Task 2 · Task 3 · Task 4 · Task 8.
- **Wave C:** Task 5 → then parallel Task 6 · Task 7 · Task 10.
- **Wave D (Ubuntu VM, under the cgroup):** Task 9 (bake-off) → Task 12 (ablation). Task 11 only after the team agrees contract v2.1.

---

### Task 1: Shared clock + event log (+ pytest config)
**Files:** Create `common/__init__.py` (empty), `common/clock.py`, `common/log.py`, `pyproject.toml`, `tests/common/test_clock_log.py`.
**Produces:** `now() -> float`; `EventLog(stage: str, path: Path | None = None, keep: bool = False)` with `.event(event: str, turn: int, t: float | None = None, **extra) -> dict`, `.records: list[dict]` (filled only when `keep=True`), `.close()`.

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```
`common/clock.py`:
```python
"""Shared clock: every stage stamps events with this, so times compare across stages and processes."""
import time


def now() -> float:
    """time.monotonic() seconds; one origin for every process on this machine."""
    return time.monotonic()
```
`common/log.py`:
```python
"""Event log: one JSON object per line, {"stage","event","turn","t","extra"} (docs/CONTRACT.md)."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from common.clock import now


class EventLog:
    def __init__(self, stage: str, path: Optional[Path] = None, keep: bool = False):
        self.stage = stage
        self.records: list[dict] = []
        self._keep = keep
        self._lock = threading.Lock()
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._fp = open(path, "a", encoding="utf-8", buffering=1)
        else:
            self._fp = sys.stdout
        self._owns = path is not None

    def event(self, event: str, turn: int, t: Optional[float] = None, **extra: Any) -> dict:
        rec = {"stage": self.stage, "event": event, "turn": turn,
               "t": now() if t is None else t, "extra": extra}
        line = json.dumps(rec, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            self._fp.write(line + "\n")
            if self._keep:
                self.records.append(rec)
        return rec

    def close(self) -> None:
        if self._owns:
            self._fp.close()
```
**Tests (write first):** `test_now_is_monotonic_and_fine_grained` (asserts `time.get_clock_info("monotonic").resolution <= 0.001`; fails on Windows Python ≤3.12 by design) · `test_event_writes_one_json_line` (exact dict incl. `extra`) · `test_event_stamps_now_when_t_missing` · `test_threads_never_interleave_lines` (4 threads × 200 events → 800 parseable lines) · `test_creates_parent_dir` · `test_keep_collects_records`.
- [ ] Write tests → `pytest tests/common -q` fails (ImportError) → implement → passes.
- [ ] Commit `common: shared clock + JSONL event log` and push. Tell Spine in `brain/handoff_brain.md` (they may extend, not change, the line format).

### Task 2: Speakable filter + chunker (pure)
**Files:** Create `brain/__init__.py` (empty), `brain/speakable.py`, `brain/chunker.py`, `tests/brain/test_speakable.py`, `tests/brain/test_chunker.py`.
**Produces:** `clean(text: str) -> str`; `ThinkFilter().feed(piece) -> str`, `.flush() -> str`; `Chunker(first_min_words=2, first_max_pieces=6, later_comma_words=4, first_done=False)` with `.push(piece) -> list[str]`, `.flush() -> str | None`, `.chunks_out: int`.

`brain/speakable.py`:
```python
"""Make LLM text safe to speak: no markdown, emoji, URLs or hidden thinking."""
import re

_URL = re.compile(r"https?://\S+|www\.\S+")
_BULLET = re.compile(r"(?m)^\s*(?:[-•*]|\d+[.)])\s+")
_MD = re.compile(r"[*_`#>|~]+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.?!;:])")
_SPACES = re.compile(r"\s+")


def clean(text: str) -> str:
    text = _URL.sub(" ", text)
    text = _BULLET.sub(" ", text)
    text = _MD.sub("", text)
    text = _EMOJI.sub("", text)
    text = text.replace("&", " and ")
    text = _SPACES.sub(" ", text).strip()
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


def _partial_tag_len(s: str, tag: str) -> int:
    for k in range(min(len(tag) - 1, len(s)), 0, -1):
        if s.endswith(tag[:k]):
            return k
    return 0


class ThinkFilter:
    """Drops everything between <think> and </think>, even when a tag is split across pieces."""
    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buf, self._inside = "", False

    def feed(self, piece: str) -> str:
        self._buf += piece
        out = []
        while True:
            if self._inside:
                j = self._buf.find(self.CLOSE)
                if j < 0:
                    self._buf = self._buf[-(len(self.CLOSE) - 1):]
                    return "".join(out)
                self._buf, self._inside = self._buf[j + len(self.CLOSE):], False
            else:
                i = self._buf.find(self.OPEN)
                if i < 0:
                    keep = _partial_tag_len(self._buf, self.OPEN)
                    out.append(self._buf[:len(self._buf) - keep])
                    self._buf = self._buf[len(self._buf) - keep:]
                    return "".join(out)
                out.append(self._buf[:i])
                self._buf, self._inside = self._buf[i + len(self.OPEN):], True

    def flush(self) -> str:
        rest = "" if self._inside else self._buf
        self._buf = ""
        return rest
```
`brain/chunker.py`:
```python
"""Cut a streamed reply into speakable chunks for Voice (brain/SPEC.md 'Chunking to Voice')."""
from __future__ import annotations

from typing import Optional

CUTS = ",.?!;:"
SENTENCE_END = ".?!;"
MAX_WORDS = 25


def _last_space_cut(buf: str) -> int:
    i = buf.rfind(" ")
    return len(buf) if i <= 0 else i + 1


class Chunker:
    """First chunk: first , . ? ! ; : after >= 2 words, or after 6 pieces at a word boundary.
    Later chunks: at . ? ! ; or at , : once the chunk has >= 4 words; never more than 25 words.
    Punctuation glued to the next character (3.5, 1,000, 3:45, x.y) is never a cut; a '.' or ','
    right after a digit at the end of the buffer waits one piece (it may become 3.5)."""

    def __init__(self, first_min_words: int = 2, first_max_pieces: int = 6,
                 later_comma_words: int = 4, first_done: bool = False):
        self.first_min_words = first_min_words
        self.first_max_pieces = first_max_pieces
        self.later_comma_words = later_comma_words
        self.chunks_out = 1 if first_done else 0
        self._buf = ""
        self._pieces = 0

    def push(self, piece: str) -> list[str]:
        if not piece:
            return []
        self._buf += piece
        self._pieces += 1
        out = []
        while (cut := self._find_cut()) is not None:
            out.append(self._buf[:cut])
            self._buf = self._buf[cut:]
            self.chunks_out += 1
        return out

    def flush(self) -> Optional[str]:
        rest, self._buf = self._buf, ""
        if rest.strip():
            self.chunks_out += 1
            return rest
        return None

    def _find_cut(self) -> Optional[int]:
        buf, first = self._buf, self.chunks_out == 0
        for i, ch in enumerate(buf):
            if ch not in CUTS:
                continue
            at_end = i == len(buf) - 1
            if not at_end and not buf[i + 1].isspace():
                continue
            if at_end and ch in ".," and i > 0 and buf[i - 1].isdigit():
                return None
            words = len(buf[:i + 1].split())
            if first:
                if words >= self.first_min_words:
                    return i + 1
            elif ch in SENTENCE_END or words >= self.later_comma_words:
                return i + 1
        n_words = len(buf.split())
        if first and self._pieces >= self.first_max_pieces and n_words >= self.first_min_words:
            cut = _last_space_cut(buf)
            return cut if len(buf[:cut].split()) >= self.first_min_words else None
        if not first and n_words > MAX_WORDS:
            return _last_space_cut(buf)
        return None
```
**Tests:** speakable — parametrized `clean`: `"**Paris** is the `capital`."→"Paris is the capital."`, `"- first item"→"first item"`, `"1. Step one"→"Step one"`, `"See https://example.com for more"→"See for more"`, `"Great job 🎉!"→"Great job!"`, `"Salt & pepper"→"Salt and pepper"`, `"  lots   of\nspace "→"lots of space"`, `"# Heading"→"Heading"`; `ThinkFilter` drops `["<thi","nk>secret"," plan</th","ink>Hi"," there"]` → `"Hi there"`; plain text passes through.
Chunker (helper `feed(ch, pieces)` concatenates push results): `["Paris"," is"," the"," capital",","]→["Paris is the capital,"]` · `["Yes",","]→[]` then `[" it"," is","."]→["Yes, it is."]` · six pieces `["The"," sun"," is"," a"," star"," that"," shi"]→["The sun is a star "]` · with `first_max_pieces=20`: `["It"," is"," 3","."]→[]`, then `["5"," degrees","."]→["It is 3.5 degrees."]`; `["About"," 1",",","000"," people","."]→["About 1,000 people."]`; `["At"," 3",":","45"," pm","."]→["At 3:45 pm."]` · `["It"," was"," 2024","."," Then"]→["It was 2024."]` · later chunk: after `["Paris"," is"," big",","]`, `[" and"," old",","]→[]` then `[" and"," very"," pretty","."]→[" and old, and very pretty."]` · after `["Yes"," sure",","]`, `[" it"," opens"," at"," nine",","]→[" it opens at nine,"]` · runaway: after `["Okay"," then","."]`, 27 pieces `" w{i}"` → exactly one chunk of 25 words · `flush()` returns `"Hello there"` once, then `None`.
- [ ] Tests → fail → implement → `pytest tests/brain -q` passes → commit `brain: chunker + speakable filter`.

### Task 3: Prompt builder (byte-stable ChatML)
**Files:** Create `brain/prompt.py`, `tests/brain/test_prompt.py`.
**Produces:** `SYSTEM_PROMPT: str`; `normalize(text) -> str`; `PromptBuilder(family="qwen3", system=SYSTEM_PROMPT, max_turns=3)` with `.base()`, `.partial(user)`, `.final(user)`, `.add_turn(user, reply)`, `.rebuild(family) -> PromptBuilder`, `.clear()`.
```python
"""Byte-stable prompts. The KV cache is reused only for an identical byte prefix, so: the system
prompt never changes, history is append-only, and a past reply is rendered exactly as generated
(including the empty think block) so the next turn's prompt extends the previous one."""
from __future__ import annotations

import re
from dataclasses import dataclass

SYSTEM_PROMPT = (
    "You are Pecko, an offline voice assistant running on this device. "
    "Answer in one or two short spoken sentences. Give the answer first, then at most one short reason. "
    "No lists, no markdown, no symbols, no emoji. Spell out numbers in words. "
    "If you don't know, say so in one sentence. "
    "You are offline and cannot browse, check live data or open apps."
)
# keep letters/digits/apostrophes; Devanagari and Tamil blocks kept whole (their vowel signs are not \w)
_PUNCT = re.compile(r"[^\w\s'ऀ-ॿ஀-௿]")


def normalize(text: str) -> str:
    return " ".join(_PUNCT.sub(" ", text.lower()).split())


@dataclass(frozen=True)
class Template:
    system: str
    user_open: str
    user_close: str
    assistant_open: str
    assistant_close: str


TEMPLATES = {
    # Qwen3 non-thinking: pre-fill an empty think block so no silent "thinking" seconds
    "qwen3": Template("<|im_start|>system\n{sys}<|im_end|>\n", "<|im_start|>user\n", "<|im_end|>\n",
                      "<|im_start|>assistant\n<think>\n\n</think>\n\n", "<|im_end|>\n"),
    # LFM2: BOS <|startoftext|> is added by llama-server's tokenizer, not written here
    "lfm2": Template("<|im_start|>system\n{sys}<|im_end|>\n", "<|im_start|>user\n", "<|im_end|>\n",
                     "<|im_start|>assistant\n", "<|im_end|>\n"),
}


class PromptBuilder:
    def __init__(self, family: str = "qwen3", system: str = SYSTEM_PROMPT, max_turns: int = 3):
        self.family, self.max_turns, self._system_text = family, max_turns, system
        self.t = TEMPLATES[family]
        self._system = self.t.system.format(sys=system)
        self._turns: list[tuple[str, str]] = []

    def base(self) -> str:
        parts = [self._system]
        for user, reply in self._turns:
            parts += [self.t.user_open, user, self.t.user_close, self.t.assistant_open, reply, self.t.assistant_close]
        return "".join(parts)

    def partial(self, user: str) -> str:
        """Early-prefill prompt: the user turn is still open, so this is a byte prefix of final()."""
        return self.base() + self.t.user_open + user

    def final(self, user: str) -> str:
        return self.partial(user) + self.t.user_close + self.t.assistant_open

    def add_turn(self, user: str, reply: str) -> None:
        self._turns.append((user, reply))
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[len(self._turns) - self.max_turns:]

    def rebuild(self, family: str) -> "PromptBuilder":
        nb = PromptBuilder(family, self._system_text, self.max_turns)
        nb._turns = list(self._turns)
        return nb

    def clear(self) -> None:
        self._turns.clear()
```
**Tests:** `normalize("What is the Capital of France?")=="what is the capital of france"`; keeps `"what's"`; Hindi `"नमस्ते, पेको!"` keeps both words intact · `final("what is the capital of france").startswith(partial("what is the capital"))` · `base()` byte-identical across calls · qwen3 `final()` ends with `"<think>\n\n</think>\n\n"` · cache invariant: `p1=b.final(u); b.add_turn(u, r); assert b.base().startswith(p1 + r)` · history keeps last 3; `max_turns=0` keeps none · `len(SYSTEM_PROMPT.split()) <= 90` (token check is live in Task 4) · `rebuild("lfm2")` keeps turns, changes template.
- [ ] Tests → fail → implement → pass → commit `brain: byte-stable prompt builder`.

### Task 4: llama-server client, process manager, probes
**Files:** Create `brain/llama_client.py`, `brain/llama_server.py`, `brain/probe_server.py`, `tests/brain/test_llama_client.py` (fake SSE server), `tests/brain/test_llama_live.py` (skipped unless `PECKO_LLAMA_PORT` set).
**Produces:** `Timings(prompt_n, cache_n, prompt_ms, predicted_n, predicted_ms)` + `.decode_tps`, `Timings.from_json(d)`; `Piece(text, timings=None)`; `iter_sse(lines)`; `LlamaError`; `LlamaClient(host="127.0.0.1", port=8080, timeout=120.0, prefill_n_predict=DEFAULT_PREFILL_N_PREDICT)` with `.health() -> bool`, `.tokenize(text) -> list[int]`, `.prefill(prompt, *, cache_prompt=True) -> Timings`, `.stream(prompt, *, n_predict, temperature=0.4, cancel=None, cache_prompt=True) -> Iterator[Piece]` (last piece carries timings; cancel = close the connection, which makes llama-server stop). `find_llama_server(root=Path("models/llama.cpp")) -> Path`; `LlamaServer(model, *, ctx=2048, threads=1, threads_batch=2, port=8080, exe=None, extra=DEFAULT_EXTRA, log_path=None)` with `.args()`, `.start(timeout=120) -> float seconds`, `.stop()`, `.pid`, `.port`.

Key code (`brain/llama_client.py`, stdlib only so it also runs in Termux):
```python
DEFAULT_PREFILL_N_PREDICT = 0   # set to 1 if probe_server.py reports n_predict_0_ok == false

def iter_sse(lines) -> Iterator[dict]:
    for raw in lines:
        line = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw).strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        yield json.loads(payload)

    # inside LlamaClient
    def stream(self, prompt, *, n_predict, temperature=0.4, cancel=None, cache_prompt=True):
        body = {"prompt": prompt, "n_predict": n_predict, "stream": True, "cache_prompt": cache_prompt,
                "temperature": temperature, "stop": ["<|im_end|>"], "id_slot": 0}
        conn, resp = self._request("POST", "/completion", body)
        try:
            for ev in iter_sse(resp):
                if cancel is not None and cancel.is_set():
                    return
                text = ev.get("content", "")
                if ev.get("stop"):
                    if text:
                        yield Piece(text)
                    yield Piece("", Timings.from_json(ev.get("timings")))
                    return
                if text:
                    yield Piece(text)
        finally:
            conn.close()   # closing mid-stream is the cancel: llama-server stops on client disconnect
```
`_request` opens a fresh `http.client.HTTPConnection` per call (localhost, < 1 ms), raises `LlamaError` on non-200. `LlamaServer.start()` Popens `args()` with stdout/stderr to `data/results/llama-server-<model>.log`, polls `health()` every 0.1 s, raises with the log path if the process exits; `stop()` terminate → wait 10 s → kill.
**Fake-server unit tests** (`ThreadingHTTPServer` on port 0; POST streams `n_pieces` SSE events `" w{i}"` with `delay`, then a stop event with timings `{prompt_n:3, cache_n:10, predicted_n:n, predicted_ms:50}`; non-stream POST returns JSON timings; GET `/health` 200; records `last_body` and `disconnected`): `test_iter_sse_parses_data_lines_and_stops_at_done` · `test_timings_defaults_and_tps` · `test_stream_yields_pieces_then_timings` (also asserts `stream` and `cache_prompt` true in body) · `test_cancel_stops_stream_and_disconnects` (cancel after 2 pieces → exactly 2 pieces, server sees disconnect within 2 s) · `test_prefill_returns_timings` · `test_http_error_raises_llama_error` · `test_server_args_match_spec` (`LlamaServer(...).args()` contains `-np 1 -t 1 -tb 2 -ctk q8_0 -ctv q8_0 --host 127.0.0.1`) · `test_find_llama_server` (tmp tree with `x/llama-server.exe` and a `.dll` → finds the exe).
**Live tests** (`PECKO_LLAMA_PORT=8080`): system prompt base ≤ 150 tokens via `/tokenize` · second request `cache_n >= base_tokens - 1` · thinking off (`"<think>" not in reply`, reply non-empty).
**`probe_server.py --port 8080 --label <model>`** writes `data/results/probe_<label>.json` with: `n_predict_0_ok` (prefill with `n_predict:0` returns `predicted_n==0` and timings), `cache_reuse_tokens`, `disconnect_stops_generation` (stream 300 tokens, close after 3, time a tiny prefill: < 500 ms ⇒ stopped), `rewind_cache_n` vs `rewind_lcp_tokens` (prefill `final("what is the weather in chennai today")`, then stream `final("what is the capital of france")`; LCP of the two `/tokenize` lists), `think_leak`.
- [ ] Start server: `models/llama.cpp/b11501-win/llama-server.exe -m models/Qwen3-0.6B-Q4_K_M.gguf -c 2048 -np 1 -t 1 -tb 2 -ctk q8_0 -ctv q8_0 --host 127.0.0.1 --port 8080`. If it refuses the quantized V cache, add `-fa on`, set `DEFAULT_EXTRA = ("-fa", "on")`, log it in `gotcha.md`.
- [ ] Unit tests → fail → implement → pass. Live tests + probe → pass; apply probe results to `DEFAULT_PREFILL_N_PREDICT`. Commit `brain: llama-server client, manager, probes`.

### Task 5: BrainStage core (final → chunks, cancel, fallback, tiers table)
**Files:** Create `brain/tiers.py`, `brain/stage.py`, `tests/brain/fakes.py`, `tests/brain/test_stage.py`.
**Consumes:** Tasks 1–4. **Produces:** `BrainTier(name, model, family, ctx, n_predict, threads, threads_batch, prefill, max_sentences=2, router_threshold=90.0)`; `TIERS: dict[int, BrainTier]`; `BrainStage(emit, log, client, *, tier=0, tiers=None, router=None, early_prefill=True, cache_prompt=True, temperature=0.4, max_turns=3, server_factory=None)` with `start()`, `feed(msg)`, `stop()`, `set_tier(n)`, `base_prompt() -> str`; module funcs `coalesce(jobs)`, `count_sentence_ends(text)`; constants `FALLBACK_TEXT`, `LLM_ERRORS`.

`brain/tiers.py` (Qwen3-0.6B everywhere until the bake-off decides T0/T1):
```python
TIERS = {
    0: BrainTier("T0", "Qwen3-0.6B-Q4_K_M.gguf", "qwen3", 2048, 60, 1, 2, "early"),
    1: BrainTier("T1", "Qwen3-0.6B-Q4_K_M.gguf", "qwen3", 1024, 40, 1, 2, "stable"),
    2: BrainTier("T2", "Qwen3-0.6B-Q4_K_M.gguf", "qwen3", 512, 25, 1, 1, "off", router_threshold=85.0),
    3: BrainTier("T3", None, "qwen3", 0, 0, 0, 0, "off", router_threshold=85.0),   # no LLM
}
```
Stage design (implement exactly; this is where the bugs hide):
- Live generations: `self._live: dict[gen, (turn, threading.Event)]` under `self._lock`. `_new_gen(turn) -> (gen, event)` (gen is a global counter), `_finish(gen)`, `_cancel_live(reason, turn=-1, *, gen=None, keep_turn=None)` sets matching events and logs `cancel{gen, source}`.
- `feed()` never calls the server. `final` → `normalize(norm or text)`; cancel all live gens (`new_turn`); new gen; empty text → `cached` clip `didnt_catch`; else queue `("generate", turn, gen, user)`. `barge_in` → cancel live gens. `cancel` with `gen` → cancel that gen; without `gen` (Ears: user kept talking) → reset `_last_prefill`, log `spec_cancel`. `tier` → `set_tier`. `partial`/`tentative_final` → nothing yet (Task 7).
- Worker loop: block on the queue, drain everything waiting, run `coalesce(jobs)` (drop a `prefill` if any later `prefill`/`generate` is queued; keep `generate`/`tier`/`stop` in order), dispatch; wrap each job so an exception logs `worker_error` and the loop continues.
- `_generate`: if its event is already set → finish, return. If `tier.model is None` → `cached` `low_power`. Else log `prompt_ready`, `_stream_reply(...)`, on `ok` → `add_turn(user, raw)` (raw = exact generated text, keeps the KV prefix valid), log `gen_done{status, chunks, prompt_n, cache_n, predicted_n, decode_tps}`.
- `_stream_reply(turn, gen, prompt, cancel, *, seq0=0, held=False, first_only=False, first_done=False) -> (raw, seq, status, timings)`:
```python
        chunker, think = Chunker(first_done=first_done), ThinkFilter()
        raw, seq, sentences, timings, got_token, stopped = [], seq0, 0, None, False, False
        it = self._client.stream(prompt, n_predict=self._tier.n_predict, temperature=self.temperature,
                                 cancel=cancel, cache_prompt=self.cache_prompt)
        try:
            for piece in it:
                if piece.timings is not None:
                    timings = piece.timings
                    break
                if not got_token:
                    got_token = True
                    self._log.event("first_token", turn, gen=gen, held=held)
                raw.append(piece.text)
                for chunk in chunker.push(think.feed(piece.text)):
                    seq = self._send_chunk(turn, gen, seq, chunk, cancel, held=held)
                    sentences += count_sentence_ends(chunk)
                if (first_only and chunker.chunks_out > 0) or sentences >= self._tier.max_sentences:
                    stopped = True
                    break
        except LLM_ERRORS as e:
            self._log.event("llm_error", turn, gen=gen, error=repr(e)[:200])
            if not cancel.is_set():
                seq = self._send_chunk(turn, gen, seq, FALLBACK_TEXT, cancel, last=True)
            return "".join(raw), seq, "error", None
        finally:
            it.close()
        if cancel.is_set():
            self._log.event("gen_cancelled", turn, gen=gen, chunks=seq)
            return "".join(raw), seq, "cancelled", timings
        if first_only:
            return "".join(raw), seq, "held", timings
        if not stopped:
            for chunk in chunker.push(think.flush()):
                seq = self._send_chunk(turn, gen, seq, chunk, cancel)
        rest = None if stopped else chunker.flush()
        seq = self._send_chunk(turn, gen, seq, rest or "", cancel, last=True)
        return "".join(raw), seq, "ok", timings
```
- `_send_chunk(turn, gen, seq, text, cancel, *, last=False, held=False) -> int`: return unchanged if cancelled; `text = clean(text)`; skip empty non-last; empty last with `seq == 0` becomes `FALLBACK_TEXT` (user always hears something); message `{"type":"chunk","turn","gen","seq","text": text if last else text + " "}` + `last`/`held` flags; log `first_chunk{words, held}` when `seq == 0`; emit; return `seq + 1`.
- `start()`: if `server_factory` and a model → start the server; if tier has a model → `health()` must be true, then warm-up: stream `final("hello")` with `n_predict=4`, then `prefill(base())`, log `warm_up{ms, base_tokens}`. Start the worker; log `ready`. `stop()`: cancel live, queue `stop`, join (5 s), stop owned server.
- `set_tier(n)` queues `("tier", n)` (applies after any running reply). `_apply_tier` here: switch params, `rebuild` the prompt if the family changed, log `tier_switch{frm, to, switch_ms}` (server restart comes in Task 10).

`tests/brain/fakes.py`: `FakeClient(replies=None, fail=False, delay=0.0)` records `calls` (`("prefill", prompt)` / `("stream", prompt)`); `stream` picks pieces by matching a key against the text after the last `"<|im_start|>user\n"`, default pieces `["Paris"," is"," the"," capital",","," and"," its"," largest"," city","."]`, honours `cancel` and `n_predict`, raises `ConnectionResetError` when `fail`, ends with `Piece("", Timings(prompt_n=8, cache_n=60, predicted_n=len(pieces), predicted_ms=100))`. Helper `wait_until(pred, timeout=2)`.
**Tests:** `test_final_streams_chunks_with_contract_fields` (texts `"Paris is the capital, "`, `"and its largest city. "`, then a `last` chunk; seq 0..2; same gen) · `test_required_events_logged_in_order` (`prompt_ready` < `first_token` < `first_chunk` < `gen_done`) · `test_prompt_uses_norm_not_cased_text` · `test_second_turn_prompt_extends_first` (second stream prompt starts with first prompt + raw reply) · `test_barge_in_stops_within_one_piece` (50 pieces, delay 0.02, barge_in after first chunk → no `last` chunk for that gen, ≤ 1 extra chunk, `gen_cancelled` logged) · `test_new_final_cancels_running_reply` · `test_voice_cancel_by_gen` · `test_llm_failure_sends_fallback` (`fail=True` → one chunk `FALLBACK_TEXT`, `last`, `llm_error`) · `test_empty_final_sends_didnt_catch_without_llm` · `test_sentence_limit_two` (3-sentence reply → only 2 spoken) · `test_unspeakable_never_reaches_voice` (pieces `["**Sure**", ",", " see", " https://x.y", " 🎉", "."]` → no `*`, `http`, emoji in any text) · `test_tier3_answers_low_power_without_server` · `test_set_tier_waits_for_running_reply` (`gen_done` logged before `tier_switch`) · `test_coalesce_keeps_only_last_useful_prefill` (pure).
- [ ] Tests → fail → implement → pass. Run 20× (`pytest tests/brain/test_stage.py -q --count` not available: loop `for i in $(seq 20); do pytest -q tests/brain/test_stage.py || break; done`) to catch thread flakiness. Commit `brain: BrainStage core`.

### Task 6: Typed-text mock (`brain/mock_cli.py`)
**Files:** Create `brain/mock_cli.py`. **Consumes:** BrainStage, LlamaClient, EventLog(keep=True).
Behaviour: `python -m brain.mock_cli [--port 8080] [--tier 0]`; each typed line becomes a `final` (turn += 1); every emitted message prints as `+{ms since final} {msg}`; after the `last` chunk prints `first_token X ms | first_chunk Y ms | prompt tokens computed N, reused from cache M | decode Z tok/s` from that turn's records; events also go to `data/results/brain_mock_events.jsonl`.
- [ ] Verify by hand with the live server: ask 3 questions. **Pass when** turn 2+ shows `reused from cache` ≥ the system prompt tokens and `computed` ≈ only the new words. Paste one run into `brain/handoff_brain.md`. Commit `brain: typed-text mock`.

### Task 7: Early prefill (`stable`, `tentative_final`) + speech simulator
**Files:** Modify `brain/stage.py` (`_on_partial`, `_on_tentative`, worker `prefill` job); Create `brain/sim.py`; Modify `brain/mock_cli.py` (add `--speak`); Test `tests/brain/test_early_prefill.py`.
- `_on_partial`: skip if `not early_prefill` or tier `prefill == "off"`; `stable = normalize(msg["stable"])`; skip if < 2 words or unchanged from `_last_prefill`; else queue `("prefill", turn, "stable", stable)`.
- `_on_tentative`: only when tier `prefill == "early"`; queue `("prefill", turn, "tentative", normalize(text))`.
- Worker builds the prompt (never the feed thread): `"stable"` → `partial(text)`, `"tentative"` → `final(text)`; logs `prefill{kind, prompt_n, cache_n, prompt_ms}`; errors log `prefill_error` and are otherwise ignored.
- `brain/sim.py`: `speak(stage, turn, text, wps=2.5, pause_ms=300) -> float` feeds one `partial` per word (`stable` = all but the newest word), a `tentative_final` at speech end, sleeps `pause_ms`, feeds `final` (with `norm`), returns the time `final` was fed.
**Tests:** prefill prompt for `stable` equals `partial(stable)` and is a prefix of the later final prompt · unchanged / 1-word `stable` → no prefill · `tentative_final` then identical `final` → stream prompt == prefilled prompt · T1 (`"stable"`) prefills partials but not tentatives; T2 (`"off"`) prefills nothing · `early_prefill=False` → none · Ears `cancel` resets so the next `stable` prefills again.
- [ ] Tests → fail → implement → pass. `python -m brain.mock_cli --speak` shows `cache_n` covering the spoken words on the final request. Commit `brain: early prefill on stable + tentative_final`.

### Task 8: Router + intents (agree the clip list with Voice)
**Files:** Create `brain/router.py`, `brain/intents.yaml`, `brain/eval_router.py`, `tests/brain/data/router_heldout.jsonl`, `tests/brain/test_router.py`; Modify `brain/stage.py` (`_on_final` routes before queueing), `brain/mock_cli.py` (`--router`).
**Produces:** `Route(kind: "cached"|"composed"|"llm", intent=None, clip=None, text=None, score=0.0)`; `Router.load(path=INTENTS_PATH, clock=datetime.now)`, `.route(norm, threshold=90.0) -> Route`; `time_words(dt)`, `date_words(dt)`, `day_words(dt)`; `evaluate(router, rows) -> dict`.
Rules, in order: empty → `cached didnt_catch` · exact template match → cached · strip leading `hey|hi|hello|ok|okay|so|um|uh|please|pecko` → composed time/date/day (anchored regexes) → exact match on the stripped text → fuzzy only on `fuzzy: true` intents with **entity agreement** (every query word is in that intent's template words or in `{please, pecko, hey, hi, hello, um, uh, so, okay, ok, oh, well, just, the, a, there, again, now, yeah, very, much}`), score = token-set ratio (rapidfuzz; difflib fallback for Termux), hit if ≥ threshold · else `llm`. Composed text has no abbreviations: `"It's three forty-five in the afternoon."` (morning < 12 ≤ afternoon < 17 ≤ evening < 21 ≤ night), `"Today is Thursday, October eighth."`, `"It's Thursday."`.
`intents.yaml` (each `clip` is pre-synthesized by Voice from `say`; templates already normalized), seed set: `greeting, thanks, bye, how_are_you, who_are_you, your_name, what_can_you_do, who_made_you, are_you_online, are_you_ai, are_you_listening, help, weather, news, music, alarm, call, shopping, joke, compliment, sorry, ok_ack, never_mind, how_old, where_running, languages, what_is_pecko, repeat_unsupported, didnt_catch, low_power` (30). `didnt_catch` = "Sorry, I didn't catch that. Could you say it again?"; `low_power` = "I'm in low-power mode right now, so I can only do simple things like the time and date."
**Tests:** every clip unique, every template `normalize(t) == t`, every `say` non-empty · exact hits (`"hello pecko"→greeting`, `"thank you"→thanks`) · fuzzy with filler (`"hello there pecko"→greeting`) · entity rejection (`"hello can you book a cab"→llm`, `"thanks but what is the capital of france"→llm`) · leading greeting stripped for composed (`"hi what time is it"` → composed time) · `time_words(datetime(2026,10,8,15,45))=="It's three forty-five in the afternoon."`, `(0,5)`→`"It's twelve oh five at night."`, `(9,0)`→`"It's nine o'clock in the morning."` · `date_words(datetime(2026,10,8))=="Today is Thursday, October eighth."` · held-out file (≥ 30 rows, `{"text","expect": intent|null}`, phrasings never used as templates, half should-not-hit) → `evaluate` reports **0 wrong and 0 false hits** (hit rate is reported, not asserted) · stage: cached route emits `cached` + logs `route` and `cache_hit`, never calls the LLM, does not touch history.
- [ ] Tests → fail → implement → pass. `python -m brain.eval_router` prints hit rate / false-hit rate → paste into `brain/RESULTS.md`. Push `intents.yaml` and tell Voice in the handoff. Commit `brain: router + intents`.

### Task 9: Bake-off (Ubuntu VM, under the cgroup)
**Files:** Create `brain/bakeoff.py`, `brain/bakeoff_questions.txt` (20 spoken-style questions: capital of France, leap-year days, Romeo and Juliet author, boiling point of water, black hole, cup of tea, largest planet, why the sky is blue, photosynthesis, a sleep tip, tallest mountain, language of Tamil Nadu, weather in Coimbatore today, prime minister of India, distance to the moon, what a CPU does, coffee shop name near a college, twelve times eight, thank you in Hindi, a fact about elephants), `brain/score_sheet.py`, `tests/brain/test_bakeoff.py`; Modify `brain/RESULTS.md`.
`python -m brain.bakeoff --model models/<file>.gguf --family qwen3|lfm2 --label <label> [--port 8080]`: starts `LlamaServer`, samples server RSS every 50 ms (psutil) and reads cgroup `memory.peak` (`/proc/self/cgroup` → `/sys/fs/cgroup/<path>/memory.peak`, `None` if absent), warms `prefill(base())`, asks the 20 questions with no history (TTFT = request → first piece; `cache_n`, decode tok/s), runs the rewind probe 5× (as in Task 4), writes `data/results/bakeoff_<label>.jsonl` + `_summary.json`, prints the `RESULTS.md` row (TTFT p50/p90 nearest-rank, rewind TTFT p50, `rewind reprocesses?` = any `cache_n < lcp - 1`, decode tok/s median, peak RAM, platform). `score_sheet.py` builds a shuffled blind CSV (`data/results/blind_scores.csv` + key) for a teammate to score 1–5, and `--tally` prints the mean per model.
Run inside Spine's cap: `sudo systemd-run --scope -p AllowedCPUs=0,1 -p CPUQuota=200% -p MemoryMax=2G -p MemorySwapMax=0 --unit=pecko-bakeoff .venv/bin/python -m brain.bakeoff ...` for: Qwen3-0.6B Q4_K_M, Qwen3-1.7B Q4_K_M, LFM2.5-1.2B-Instruct Q4_0, LFM2.5-350M Q4_0 (download with `hf download` first; LFM2: if replies are garbage, the BOS is missing; prepend `<|startoftext|>` in the `lfm2` template and note it in `gotcha.md`).
**Tests (pure):** nearest-rank percentile; `common_prefix_len`; `cgroup_memory_peak()` returns `None` on Windows; score sheet round-trip (build → fill → tally) on tmp files.
- [ ] Apply the SPEC decision rule (T0 = best quality with p50 TTFT ≤ 300 ms, rewind not reprocessing, total stack peak ≤ 1.6 GB; default Qwen3-0.6B). Update `brain/tiers.py` and `docs/CONTRACT.md` tier row only if the team agrees. Commit `brain: bake-off + results`.

### Task 10: Tier switching with server restart
**Files:** Modify `brain/stage.py` (`_apply_tier`, `start`, `stop`); Test `tests/brain/test_tiers.py`.
`_apply_tier(n)`: if `server_factory` and `(model, ctx, threads, threads_batch)` changed → **stop the old server first** (two models never share the 2 GB cap), start a new one when the new tier has a model (T3 has none), then warm up; `rebuild` the prompt on family change; log `tier_switch{frm, to, load_ms, switch_ms}`.
**Tests (FakeServer + factory recording start/stop):** T0→T2 (ctx changes) restarts once, stop before start · T0→T1 with same server config does not restart · T0→T3 stops the server; the next final answers `low_power` · T3→T0 starts it again and the next final streams · switch requested mid-reply applies after `gen_done`.
- [ ] Tests → pass. Live (Ubuntu VM): switch T0→T2→T3→T0, record `switch_ms` and Spine's `memory.peak` per switch in `RESULTS.md`. Commit `brain: tier switching`.

### Task 11: Hold-and-release (only after all four agree contract v2.1)
**Files:** Modify `brain/stage.py`, `brain/chunker.py` (already has `first_done`); Test `tests/brain/test_hold_release.py`.
With `hold_release=True` and tier `prefill == "early"`: `tentative_final` → new gen, record `_held_turn`, queue `("held", turn, gen, text)`; worker streams `final(text)` with `first_only=True` (first chunk sent with `held:true`, then the stream is closed) and stores `{turn, gen, text, raw, seq, cancel, status}`. `final` for the held turn → cancel other turns' gens only (`keep_turn=turn`), queue `("resolve", turn, user, fallback_gen)`. Worker `resolve`: if text matches → log `held_valid{match:true}` (Spine sends `commit`), continue with `final(text) + raw` from `seq` using `first_done=True` (same gen, not held), `add_turn(user, raw + rest)`; else log `held_valid{match:false}`, emit `{"type":"cancel","turn","gen":held_gen}`, generate normally with the fallback gen. Ears `cancel` → drop the held state, emit the same cancel to Voice.
**Tests:** matching final → first chunk `held:true`, later chunks same gen without `held`, seq continuous, second request prompt == `final(text) + held raw` · mismatching final → `cancel` for the held gen, new gen answers · Ears `cancel` before final → cancel emitted, nothing else.
- [ ] Commit `brain: hold-and-release (contract v2.1)`.

### Task 12: Brain ablation (Ubuntu VM, under the cgroup)
**Files:** Create `brain/ablate.py`, `brain/ablation_turns.jsonl` (12 spoken turns, different from the bake-off questions, incl. 3 hesitations, 2 corrections, 2 router intents); Test `tests/brain/test_ablate.py`; Modify `brain/RESULTS.md`.
Configs (same model, `temperature=0`, same turns, 3 reps): `no_cache` (cache_prompt off, no prefill) · `sys_cache` · `early_stable` (tier prefill `stable`) · `early_tentative` (`early`) · `router` (+ router). Each turn played through `sim.speak`; before each turn `base_n = len(client.tokenize(stage.base_prompt()))` (outside the timed window). Per turn: `first_token` and `first_chunk` (or `cache_hit`) minus final time; wasted prefill % = `(Σ prefill.prompt_n − max(0, gen_done.cache_n − base_n)) / Σ prefill.prompt_n`. Prints the RESULTS rows (p50/p90 nearest-rank, n, platform). Q4 vs Q8: rerun `sys_cache` + `early_tentative` with `Qwen3-0.6B-Q8_0.gguf` and the 20-question quality sheet.
**Tests:** `measure()` on synthetic records gives the expected p50/p90 and wasted %; router-only turns have no `first_token` and do not crash.
- [ ] Run, paste rows, commit `brain: ablation results`.

---
## Self-review (done)
Spec coverage: system-prompt cache (T3–T6), thinking off (T3, T4 live), chunk rule (T2), speakable (T2, T5), cancel ≤ 1 token (T4, T5), bake-off + rule (T9), early prefill + tentative (T7), router + false-hit on held-out (T8), tiers (T5, T10), hold-and-release (T11), ablation rows incl. Q4 vs Q8 (T12), phone Q4_0 profile (tiers table; Mobile owns `mobile/`). Review Focus items each have a test in their owning task. Names cross-checked: `_stream_reply`, `_send_chunk`, `Chunker(first_done)`, `PromptBuilder.partial/final/base/rebuild`, `LlamaClient.stream/prefill/tokenize`, `BrainTier.prefill/router_threshold`.
