"""VoiceStage: contract v2 + v2.1 (hold-and-release). start() / feed(msg) / stop() / set_tier(n).

Brain chunk ─► turn/gen filter ─► seq reorder (300 ms gap timeout) ─► phrase chunker ─► normalize
          ─► synth (1 ONNX thread) ─► PCM ─┬─ gen released ──► ring buffer ─► audio callback ─► speaker
                                           └─ gen held ─────► private hold buffer ──(commit)──┘
Rules (docs/CONTRACT.md v2.1): nothing from a held gen is audible before `commit` for the same turn+gen.
A newer gen, `cancel` or `barge_in` drops held PCM (and stops playback if it was already released).

Control messages (commit, cancel, barge_in) are applied immediately inside feed(), not queued behind
synthesis, so a release or a stop never waits for a running synth call.
Events: chunk_recv, synth_start, synth_end, pcm_ready (= R, first clause PCM of a gen), commit_recv (= C),
release, first_audio_out, gap, underrun summary, barge_in_stop, cancel, seq_gap_skip, tier_switch, turn_done.
"""
import queue
import threading
import time

from .cache import AudioCache
import gc

import psutil

from .engine import OUT_SR, TIERS, finish_clip, make_engine
from .player import NullPlayer, Player
from .text import PhraseChunker, normalize
from .vlog import log, now

SEQ_GAP_TIMEOUT = 0.30   # missing seq: wait this long, then skip it (SPEC)
STALL_TIMEOUT = 2.0      # Brain died mid-reply (no `last`): finish what we have


class _Gen:
    """State of the reply generation currently owned by Voice."""

    def __init__(self, turn, gen, released):
        self.turn, self.gen = turn, gen
        self.released = released     # False while held (v2.1); True = audible path
        self.held = []               # private PCM waiting for commit
        self.ended = False           # `last` processed
        self.dead = False            # cancelled / superseded
        self.pending = {}            # seq -> msg (reorder buffer)
        self.next_seq = 0
        self.gap_since = None        # when we started waiting for a missing seq
        self.first_pcm = False


class VoiceStage:
    def __init__(self, on_event=None, tier: int = 0, device=None, threads: int = 1, audio: bool = True,
                 cache_layers=("L2", "L3", "L4", "C"), engine_factory=make_engine, barge_in: bool = True,
                 fallback_factory=lambda: make_engine("espeak-ng"), on_error=None):
        """audio=False uses NullPlayer (tests, benchmarks, WAV-in). cache_layers=() disables the cache (ablation).
        barge_in=False is the half-duplex switch: barge_in from Ears is ignored (use it if echo makes Pecko stop
        itself). fallback_factory builds the emergency engine used when one phrase fails to synthesize."""
        self.on_event = on_event or (lambda m: None)
        self.tier, self.pending_tier, self.threads, self.device = tier, None, threads, device
        self.audio, self.engine_factory, self.barge_in = audio, engine_factory, barge_in
        self.fallback_factory, self.fallback = fallback_factory, None
        self.on_error = on_error      # unexpected worker errors (Spine adapter passes ctx.fail)
        self.engine = None
        self.cache = AudioCache(cache_layers)
        self.inbox = queue.Queue()
        self.lock = threading.RLock()
        self.g = None                # current _Gen
        self.dead_turns = set()
        self.precommit = set()       # (turn, gen) commits that arrived before the gen's first chunk
        self.stats = {}
        self._running = False

    # ---- lifecycle ------------------------------------------------------------------
    def start(self) -> dict:
        t = now()
        cinfo = self._load_tier(self.tier)
        self.player = Player(self.device) if self.audio else NullPlayer()
        self.chunker = PhraseChunker(self.player.buffered_ms,
                                     is_opener=lambda p: self.cache.lookup(normalize(p))[1] == "L2")
        self.player.start()
        self._running = True
        threading.Thread(target=self._worker, name="voice-synth", daemon=True).start()
        threading.Thread(target=self._events, name="voice-events", daemon=True).start()
        info = {"pack": self.engine.pack, "tier": self.tier, "ready_s": round(now() - t, 2), "cache": cinfo,
                "out_latency_ms": round(self.player.out_latency * 1000, 1), "sr": OUT_SR}
        log("ready", **info)
        return info

    def stop(self):
        self._running = False
        self.inbox.put(None)
        self.player.events.put(None)
        self.player.close()

    def set_tier(self, n: int):
        self.feed({"type": "tier", "tier": n})

    # ---- input (any thread) ----------------------------------------------------------
    def feed(self, msg: dict):
        typ = msg.get("type")
        if typ == "commit":
            self._commit(msg.get("turn"), msg.get("gen"))
        elif typ == "cancel":
            self._cancel(msg.get("turn"), msg.get("gen"), reason="cancel")
        elif typ == "barge_in":
            if not self.barge_in:
                log("barge_in_ignored", msg.get("turn"), half_duplex=True)
                return
            self._cancel(msg.get("turn"), None, reason="barge_in", whole_turn=True)
        else:
            self.inbox.put(msg)

    def _commit(self, turn, gen):
        log("commit_recv", turn, gen=gen)
        with self.lock:
            g = self.g
            if g is None or (turn, gen) != (g.turn, g.gen):
                self.precommit.add((turn, gen))  # gen not started yet: release it on arrival
                return
            if g.released or g.dead:
                return
            g.released = True
            st = self.stats.get(turn)
            if st is not None:
                st["t_commit"] = now()
            for pcm in g.held:
                self.player.write(pcm)
            n_held = len(g.held)
            g.held = []
            if g.ended:
                self.player.end_turn()
        log("release", turn, gen=gen, held_phrases=n_held)

    def _cancel(self, turn, gen, reason, whole_turn=False):
        with self.lock:
            g = self.g
            if g is None or turn != g.turn or (gen is not None and gen != g.gen):
                if whole_turn and turn is not None:
                    self.dead_turns.add(turn)
                log(reason, turn, gen=gen, matched=False)
                return
            if whole_turn:
                self.dead_turns.add(turn)
            g.dead = True
            g.held = []
            was_audible = g.released
            if was_audible:
                self.player.stop_now()
            st = self.stats.get(turn)
            if st is not None:
                st["cancelled"] = reason
        log(reason, turn, gen=g.gen, stopped_playback=was_audible)
        if whole_turn and not was_audible:
            self._finish_turn_if_silent(turn)   # nothing was audible: close the turn now

    # ---- synth worker ----------------------------------------------------------------
    def _worker(self):
        while self._running:
            timeout = self._wait_budget()
            try:
                msg = self.inbox.get(timeout=timeout)
            except queue.Empty:
                self._on_timeout()
                continue
            if msg is None:
                return
            try:
                self._handle(msg)
            except Exception as e:  # never kill the stage silently: log, and tell the supervisor if asked
                log("error", self.g.turn if self.g else None, err=repr(e))
                if self.on_error is not None:
                    self.on_error(f"voice worker: {e!r}")

    def _wait_budget(self):
        g = self.g
        if g is None or g.dead or g.ended:
            return None                      # block until the next message
        if g.gap_since is not None:
            return max(0.0, SEQ_GAP_TIMEOUT - (now() - g.gap_since))
        return STALL_TIMEOUT

    def _on_timeout(self):
        g = self.g
        if g is None or g.dead or g.ended:
            return
        if g.gap_since is not None and g.pending:
            log("seq_gap_skip", g.turn, missing=g.next_seq)
            g.next_seq = min(g.pending)
            g.gap_since = None
            self._drain_pending(g)
        else:
            log("stall_finish", g.turn, gen=g.gen)
            self._end_gen(g)

    def _handle(self, msg):
        typ = msg.get("type")
        if typ == "tier":
            self.pending_tier = int(msg["tier"])
            g = self.g
            if (g is None or g.ended or g.dead) and not self.player.is_playing():
                self._apply_tier()              # between turns only; otherwise applied at the next turn
            return
        if typ not in ("chunk", "cached"):
            return
        turn, gen = msg.get("turn", 0), msg.get("gen", 0)
        g = self.g
        if turn in self.dead_turns:
            return
        if g is not None and (turn < g.turn or (turn == g.turn and gen < g.gen)):
            return                            # stale: older turn or generation
        if g is None or turn != g.turn or gen != g.gen:
            g = self._begin_gen(turn, gen, held=bool(msg.get("held")))
        if g.dead:
            return
        st = self.stats[turn]
        if st["t_first_chunk"] is None:
            st["t_first_chunk"] = now()
        if typ == "cached":
            clip = msg.get("clip")
            log("chunk_recv", turn, gen=gen, clip=clip)
            pcm = self.cache.intent(clip)
            if pcm is not None:
                log("cache_hit", turn, gen=gen, layer="L4", clip=clip)
                self._emit(pcm, g, "L4", 0.0)
            else:                             # cache off or unknown clip: speak its text (never go silent)
                text = msg.get("text") or self.cache.intent_text.get(clip) or self.cache.intent_text.get("didnt_catch", "")
                self._speak(text, g)
            self._end_gen(g)
            return
        log("chunk_recv", turn, gen=gen, seq=msg.get("seq"), held=bool(msg.get("held")))
        g.pending[msg.get("seq", g.next_seq)] = msg
        self._drain_pending(g)

    def _drain_pending(self, g):
        while g.next_seq in g.pending and not g.dead:
            m = g.pending.pop(g.next_seq)
            g.next_seq += 1
            if m.get("last") and m.get("seq", 0) == 0 and not self.chunker.buf.strip():
                pcm = self.cache.compose(m.get("text", ""))   # Brain's composed time/date/day answer
                if pcm is not None:
                    log("cache_hit", g.turn, gen=g.gen, layer="C", text=m.get("text", "").strip())
                    self._emit(pcm, g, "C", 0.0)
                    self._end_gen(g)
                    return
            phrases = self.chunker.feed(m.get("text", ""))
            if m.get("last"):
                phrases += self.chunker.flush()
            for p in phrases:
                if g.dead:
                    return
                self._speak(p, g)
            if m.get("last"):
                self._end_gen(g)
                return
        g.gap_since = (g.gap_since or now()) if g.pending else None

    def _begin_gen(self, turn, gen, held):
        with self.lock:
            old = self.g
            if old is not None and old.turn == turn and not old.dead:   # newer gen supersedes
                old.dead = True
                old.held = []
                if old.released:
                    self.player.new_turn(turn)   # drop its queued PCM without ending the turn
                log("superseded", turn, gen=old.gen, by=gen)
            released = (not held) or (turn, gen) in self.precommit
            self.precommit.discard((turn, gen))
            g = _Gen(turn, gen, released)
            if old is None or old.turn != turn:
                if self.pending_tier is not None:
                    self._apply_tier()
                self.player.new_turn(turn)
                self.stats[turn] = {"turn": turn, "tier": self.tier, "pack": self.engine.pack,
                                    "t_first_chunk": None, "t_commit": None, "t_pcm_ready": None,
                                    "t_first_audio": None, "first_synth_ms": None, "first_layer": None,
                                    "hits": {}, "phrases": 0,
                                    "synth_ms": [], "audio_s": 0.0, "gaps_ms": [], "barge_stop_ms": None,
                                    "cancelled": None, "gens": 0, "gen": gen, "held_used": False, "done": False,
                                    "first_dur_s": None}
            st = self.stats[turn]
            if st["gens"] and st["t_first_audio"] is None:
                # earlier gen of this turn was never heard: measure R and chunk->sound from this gen
                st["t_first_chunk"] = st["t_pcm_ready"] = st["first_synth_ms"] = st["first_layer"] = None
            if st["gens"]:
                st["cancelled"] = None    # an earlier gen was cancelled/superseded, but the turn goes on with this gen
            st["gens"] += 1
            st["gen"] = gen
            st["held_used"] = st["held_used"] or held
            if released and st["t_commit"] is None and held:
                st["t_commit"] = now()
            self.g = g
            self.chunker.reset()
            return g

    def _speak(self, phrase, g):
        text = normalize(phrase).strip()
        if not text:
            return
        pcm, layer = self.cache.lookup(text)
        if pcm is not None:
            log("cache_hit", g.turn, gen=g.gen, layer=layer, text=text)
            self._emit(pcm, g, layer, 0.0)
            return
        t0 = now()
        log("synth_start", g.turn, gen=g.gen, text=text)
        try:
            pcm = finish_clip(self.engine.synth(text), phrase)
        except Exception as e:  # risk P5: never go silent on one bad phrase -> emergency engine for this phrase
            log("synth_error", g.turn, err=repr(e)[:200], phrase=text, engine=self.engine.pack)
            try:
                if self.fallback is None:
                    self.fallback = self.fallback_factory()
                pcm = finish_clip(self.fallback.synth(text), phrase)
                log("synth_fallback", g.turn, engine=self.fallback.pack)
            except Exception as e2:
                log("error", g.turn, err=repr(e2)[:200], phrase=text, fallback_failed=True)
                return
        ms = (now() - t0) * 1000
        dur = len(pcm) / OUT_SR
        log("synth_end", g.turn, gen=g.gen, ms=round(ms, 1), audio_s=round(dur, 2), rtf=round(ms / 1000 / dur, 3))
        self.cache.remember(text, pcm)
        self._emit(pcm, g, None, ms)

    def _emit(self, pcm, g, layer, ms):
        """Route one phrase of PCM: hold buffer (gen not committed) or ring buffer (audible path)."""
        st = self.stats[g.turn]
        with self.lock:
            if g.dead:
                return
            if not g.first_pcm:
                g.first_pcm = True
                if st["t_pcm_ready"] is None:
                    st["t_pcm_ready"] = now()
                    st["first_synth_ms"] = round(ms, 1)
                    st["first_layer"] = layer or "synth"
                    st["first_dur_s"] = len(pcm) / OUT_SR
                # seq=0 = first clause of this gen: Spine's report pairs it with `commit` to get R (spine/report.py)
                log("pcm_ready", g.turn, gen=g.gen, seq=0, held=not g.released, layer=layer or "synth")
            st["phrases"] += 1
            if layer:
                st["hits"][layer] = st["hits"].get(layer, 0) + 1
            else:
                st["synth_ms"].append(round(ms, 1))
            st["audio_s"] += len(pcm) / OUT_SR
            if g.released:
                self.player.write(pcm)
            else:
                g.held.append(pcm)

    def _end_gen(self, g):
        with self.lock:
            if g.dead or g.ended:
                return
            g.ended = True
            if g.released:
                self.player.end_turn()
        if g.released and not self.player.is_playing() and self.stats[g.turn]["phrases"] == 0:
            self._done(g.turn)                   # nothing speakable in this reply

    def _load_tier(self, n: int) -> dict:
        """Load tier n's engine + cache; if it cannot load, fall down the ladder (n+1 ... 3). If nothing at or below
        n loads (e.g. espeak-ng missing for T3), reload the previous tier so Voice is never left without a voice."""
        prev = self.tier if self.engine is not None else None
        for k in list(range(n, max(TIERS) + 1)) + ([prev] if prev is not None and prev < n else []):
            if k != n and k == prev:
                log("tier_load_recovered", None, back_to=prev)
            spec = TIERS[k]
            try:
                if self.engine is None or self.engine.pack != spec["engine"]:
                    self.engine = None
                    gc.collect()                         # free the old voice BEFORE loading the new one
                    self.engine = self.engine_factory(spec["engine"], threads=self.threads)
                cinfo = self.cache.build(self.engine, normalize, pack=spec["cache"])
                self.tier = k
                log("cache_ready", **cinfo)
                return cinfo
            except Exception as e:
                log("tier_load_failed", None, tier=k, engine=spec["engine"], err=repr(e)[:200])
        raise RuntimeError("no voice tier could be loaded")

    def _apply_tier(self):
        """Between turns only (CONTRACT). Same engine (T1<->T2) = no reload; otherwise unload, then load."""
        n, self.pending_tier = self.pending_tier, None
        if n is None or n == self.tier or n not in TIERS:
            return
        proc = psutil.Process()
        t, rss0, frm = now(), proc.memory_info().rss / 1e6, self.tier
        reload_needed = self.engine is None or self.engine.pack != TIERS[n]["engine"]
        cinfo = self._load_tier(n)
        info = {"frm": frm, "to": self.tier, "engine": self.engine.pack, "cache": TIERS[self.tier]["cache"],
                "reloaded": reload_needed, "switch_ms": round((now() - t) * 1000),
                "rss_before_mb": round(rss0), "rss_after_mb": round(proc.memory_info().rss / 1e6),
                "cache_synthesized": cinfo["synthesized"], "cache_missing": cinfo["missing"]}
        log("tier_switch", None, **info)
        self.on_event({"type": "tier_switch", **info})

    # ---- player events (blocking consumer, no polling) -------------------------------------
    def _events(self):
        while True:
            ev = self.player.events.get()
            if ev is None:
                return
            kind, turn = ev[0], ev[1]
            st = self.stats.get(turn)
            if st is None:
                continue
            if kind == "first_audio":
                if st["t_first_audio"] is not None:
                    continue                      # a later gen of the same turn; keep the first
                st["t_first_audio"] = ev[2]
                # content: real answer audio (Voice never plays fillers); sustained: the first clip carries >= 100 ms
                # of speech, so this is not a click or a one-word blip (Spine's headline criterion, spine/report.py)
                log("first_audio_out", turn, t=ev[2], gen=st.get("gen"), content=True,
                    sustained=(st.get("first_dur_s") or 0) >= 0.1, layer=st.get("first_layer"))
                self.on_event({"type": "playback_state", "turn": turn, "playing": True, "t": round(ev[2], 6)})
            elif kind == "gap":
                st["gaps_ms"].append(round(ev[3] * 1000, 1))
                log("gap", turn, t=ev[2], ms=round(ev[3] * 1000, 1))
            elif kind == "stopped":
                st["barge_stop_ms"] = round((ev[3] - ev[2] + self.player.out_latency) * 1000, 1)
                log("barge_in_stop", turn, ms=st["barge_stop_ms"])
                self._done(turn)
            elif kind == "drained":
                self._done(turn)

    def _finish_turn_if_silent(self, turn):
        st = self.stats.get(turn)
        if st is not None and st["t_first_audio"] is None and not self.player.is_playing():
            self._done(turn)

    def _done(self, turn):
        st = self.stats.get(turn)
        if st is None or st["done"]:
            return
        st["done"] = True
        if st["gaps_ms"]:
            log("underrun", turn, count=len(st["gaps_ms"]), total_ms=round(sum(st["gaps_ms"]), 1))
        summary = {k: v for k, v in st.items() if k != "done"}
        summary["audio_s"] = round(summary["audio_s"], 2)
        log("turn_done", turn, **{k: v for k, v in summary.items() if k != "turn"})
        self.on_event({"type": "playback_state", "turn": turn, "playing": False, "t": round(now(), 6)})
        self.on_event({"type": "turn_summary", **summary})
