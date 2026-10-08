"""Brain stage: Ears messages in, Voice chunks out (docs/CONTRACT.md v2, brain/SPEC.md).

feed() only queues jobs; one worker thread talks to llama-server, so Brain never has more than
one busy thread on the 2-CPU cap. Every reply carries a generation id (gen); cancelling a gen
stops its stream within one token and drops anything it would still send.
"""
from __future__ import annotations

import http.client
import queue
import re
import threading
from typing import Any, Callable, Optional

from brain.chunker import Chunker
from brain.llama_client import LlamaError, Timings
from brain.prompt import PromptBuilder, normalize
from brain.speakable import ThinkFilter, clean
from brain.tiers import TIERS, BrainTier
from common.clock import now
from common.log import EventLog

FALLBACK_TEXT = "Sorry, I lost my train of thought. Could you ask that again?"
LLM_ERRORS = (OSError, LlamaError, http.client.HTTPException)
_SENTENCE_END = re.compile(r"[.?!](?=\s|$)")


def count_sentence_ends(text: str) -> int:
    return len(_SENTENCE_END.findall(text.strip()))


def coalesce(jobs: list[tuple]) -> list[tuple]:
    """Drop a prefill when a later prefill or generate is already queued: only the newest text matters."""
    return [j for i, j in enumerate(jobs)
            if not (j[0] == "prefill" and any(k[0] in ("prefill", "generate") for k in jobs[i + 1:]))]


def _server_config(t: BrainTier) -> tuple:
    return t.model, t.ctx, t.threads, t.threads_batch


class BrainStage:
    def __init__(self, emit: Callable[[dict], None], log: EventLog, client: Any, *,
                 tier: int = 0, tiers: Optional[dict[int, BrainTier]] = None, router: Any = None,
                 early_prefill: bool = True, cache_prompt: bool = True, temperature: float = 0.4,
                 max_turns: int = 3, server_factory: Optional[Callable[[BrainTier], Any]] = None):
        self._emit, self._log, self._client = emit, log, client
        self._tiers = dict(TIERS if tiers is None else tiers)
        self._tier = self._tiers[tier]
        self._router = router
        self.early_prefill, self.cache_prompt, self.temperature = early_prefill, cache_prompt, temperature
        self._server_factory, self._server = server_factory, None
        self._prompt = PromptBuilder(self._tier.family, max_turns=max_turns)
        self._jobs: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._gen = 0
        self._live: dict[int, tuple[int, threading.Event]] = {}   # gen -> (turn, cancel event)
        self._last_prefill = ""
        self._worker = threading.Thread(target=self._run, name="brain-llm", daemon=True)

    # ---- lifecycle (stage interface) -------------------------------------------------------
    def start(self) -> None:
        if self._tier.model is not None:
            if self._server_factory is not None:
                self._server = self._server_factory(self._tier)
                self._server.start()
            if not self._client.health():
                raise RuntimeError("llama-server is not reachable; start it first (brain/SPEC.md)")
            self._warm_up()
        self._worker.start()
        self._log.event("ready", -1, tier=self._tier.name)

    def stop(self) -> None:
        self._cancel_live("stop")
        self._jobs.put(("stop",))
        if self._worker.is_alive():
            self._worker.join(timeout=5)
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._log.event("stopped", -1)

    def set_tier(self, n: int) -> None:
        if n not in self._tiers:
            raise ValueError(f"unknown Brain tier {n}")
        self._jobs.put(("tier", n))   # the worker applies it after any running reply: between turns only

    def base_prompt(self) -> str:
        return self._prompt.base()

    def feed(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "final":
            self._on_final(msg)
        elif kind == "partial":
            self._on_partial(msg)
        elif kind == "tentative_final":
            self._on_tentative(msg)
        elif kind == "cancel":
            self._on_cancel(msg)
        elif kind == "barge_in":
            self._cancel_live("barge_in")
        elif kind == "tier":
            self.set_tier(int(msg["tier"]))

    # ---- feed side: never calls the server -------------------------------------------------
    def _on_final(self, msg: dict) -> None:
        turn = int(msg["turn"])
        user = normalize(msg.get("norm") or msg.get("text", ""))
        self._last_prefill = ""
        self._cancel_live("new_turn")
        gen, ev = self._new_gen(turn)
        if not user:
            self._send_cached(turn, gen, "didnt_catch")
            return
        if self._router is not None:   # tier 0 of the Brain: common intents never reach the LLM
            r = self._router.route(user, threshold=self._tier.router_threshold)
            self._log.event("route", turn, gen=gen, kind=r.kind, intent=r.intent, score=round(r.score, 1))
            if r.kind == "cached":
                self._send_cached(turn, gen, r.clip)
                return
            if r.kind == "composed":
                self._log.event("cache_hit", turn, gen=gen, clip=r.intent, composed=True)
                self._send_chunk(turn, gen, 0, r.text, ev, last=True)
                self._finish(gen)
                return
        self._jobs.put(("generate", turn, gen, user))

    def _on_partial(self, msg: dict) -> None:
        if not self.early_prefill or self._tier.prefill == "off":
            return
        stable = normalize(msg.get("stable", ""))
        if len(stable.split()) < 2 or stable == self._last_prefill:
            return
        self._last_prefill = stable
        self._jobs.put(("prefill", int(msg["turn"]), "stable", stable))

    def _on_tentative(self, msg: dict) -> None:
        if not self.early_prefill or self._tier.prefill != "early":
            return
        text = normalize(msg.get("text", ""))
        if text:
            self._jobs.put(("prefill", int(msg["turn"]), "tentative", text))

    def _on_cancel(self, msg: dict) -> None:
        turn = int(msg.get("turn", -1))
        if "gen" in msg:
            self._cancel_live("voice_or_spine", gen=int(msg["gen"]))
        else:   # Ears: the user kept talking after a tentative_final
            self._last_prefill = ""
            self._log.event("spec_cancel", turn)

    # ---- generation bookkeeping ------------------------------------------------------------
    def _new_gen(self, turn: int) -> tuple[int, threading.Event]:
        with self._lock:
            self._gen += 1
            ev = threading.Event()
            self._live[self._gen] = (turn, ev)
            return self._gen, ev

    def _event(self, gen: int) -> Optional[threading.Event]:
        with self._lock:
            item = self._live.get(gen)
        return None if item is None else item[1]

    def _finish(self, gen: int) -> None:
        with self._lock:
            self._live.pop(gen, None)

    def _cancel_live(self, reason: str, *, gen: Optional[int] = None, keep_turn: Optional[int] = None) -> None:
        with self._lock:
            hits = [(g, t, ev) for g, (t, ev) in self._live.items()
                    if (gen is None or g == gen) and (keep_turn is None or t != keep_turn)]
        for g, t, ev in hits:
            if not ev.is_set():
                ev.set()
                self._log.event("cancel", t, gen=g, source=reason)

    # ---- worker side -----------------------------------------------------------------------
    def _run(self) -> None:
        while True:
            jobs = [self._jobs.get()]
            while True:
                try:
                    jobs.append(self._jobs.get_nowait())
                except queue.Empty:
                    break
            for job in coalesce(jobs):
                if job[0] == "stop":
                    return
                try:
                    self._do(job)
                except Exception as e:   # the worker must survive: the next turn still has to work
                    self._log.event("worker_error", -1, job=job[0], error=repr(e)[:200])
                    if job[0] == "generate":
                        self._finish(job[2])

    def _do(self, job: tuple) -> None:
        if job[0] == "generate":
            self._generate(*job[1:])
        elif job[0] == "prefill":
            self._prefill(*job[1:])
        elif job[0] == "tier":
            self._apply_tier(job[1])

    def _warm_up(self) -> None:
        t0 = now()
        for _ in self._client.stream(self._prompt.final("hello"), n_predict=4,
                                     temperature=self.temperature, cache_prompt=self.cache_prompt):
            pass
        t = self._client.prefill(self._prompt.base(), cache_prompt=self.cache_prompt)
        self._log.event("warm_up", -1, ms=round((now() - t0) * 1000, 1), base_tokens=t.prompt_n + t.cache_n)

    def _prefill(self, turn: int, kind: str, text: str) -> None:
        prompt = self._prompt.partial(text) if kind == "stable" else self._prompt.final(text)
        try:
            t = self._client.prefill(prompt, cache_prompt=self.cache_prompt)
        except LLM_ERRORS as e:
            self._log.event("prefill_error", turn, kind=kind, error=repr(e)[:200])
            return
        self._log.event("prefill", turn, kind=kind, prompt_n=t.prompt_n, cache_n=t.cache_n, prompt_ms=t.prompt_ms)

    def _generate(self, turn: int, gen: int, user: str) -> None:
        cancel = self._event(gen)
        if cancel is None or cancel.is_set():
            self._finish(gen)
            return
        if self._tier.model is None:   # T3 survival: no LLM loaded
            self._send_cached(turn, gen, "low_power")
            return
        prompt = self._prompt.final(user)
        self._log.event("prompt_ready", turn, gen=gen, chars=len(prompt))
        raw, seq, status, t = self._stream_reply(turn, gen, prompt, cancel)
        if status == "ok":
            self._prompt.add_turn(user, raw)   # exact generated text keeps the KV prefix valid
        self._finish(gen)
        t = t or Timings()
        self._log.event("gen_done", turn, gen=gen, status=status, chunks=seq, prompt_n=t.prompt_n,
                        cache_n=t.cache_n, predicted_n=t.predicted_n, decode_tps=round(t.decode_tps, 1))

    def _stream_reply(self, turn: int, gen: int, prompt: str, cancel: threading.Event, *,
                      seq0: int = 0, held: bool = False, first_only: bool = False,
                      first_done: bool = False) -> tuple[str, int, str, Optional[Timings]]:
        chunker, think = Chunker(first_done=first_done), ThinkFilter()
        raw: list[str] = []
        seq, sentences, timings, got_token, stopped = seq0, 0, None, False, False
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

    def _send_chunk(self, turn: int, gen: int, seq: int, text: str, cancel: threading.Event, *,
                    last: bool = False, held: bool = False) -> int:
        if cancel.is_set():
            return seq
        text = clean(text)
        if not text and not last:
            return seq
        if last and not text and seq == 0:
            text = FALLBACK_TEXT   # the model said nothing speakable: the user still hears something
        msg = {"type": "chunk", "turn": turn, "gen": gen, "seq": seq, "text": text if last else text + " "}
        if last:
            msg["last"] = True
        if held:
            msg["held"] = True
        if seq == 0:
            self._log.event("first_chunk", turn, gen=gen, words=len(text.split()), held=held)
        self._emit(msg)
        return seq + 1

    def _send_cached(self, turn: int, gen: int, clip: str) -> None:
        self._log.event("cache_hit", turn, gen=gen, clip=clip)
        self._emit({"type": "cached", "turn": turn, "gen": gen, "clip": clip, "last": True})
        self._finish(gen)

    def _apply_tier(self, n: int) -> None:
        old, new = self._tier, self._tiers[n]
        t0, load_ms = now(), 0.0
        restart = self._server_factory is not None and _server_config(old) != _server_config(new)
        if restart:
            if self._server is not None:
                self._server.stop()    # unload first: two models never share the 2 GB cap
                self._server = None
            if new.model is not None:
                self._server = self._server_factory(new)
                load_ms = self._server.start() * 1000
        if new.family != old.family:
            self._prompt = self._prompt.rebuild(new.family)
        self._tier = new
        if restart and new.model is not None:
            self._warm_up()
        self._log.event("tier_switch", -1, frm=old.name, to=new.name, load_ms=round(load_ms, 1),
                        switch_ms=round((now() - t0) * 1000, 1))
