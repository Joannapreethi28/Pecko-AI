"""Spine runtime adapter for Voice (docs/handoff_spine.md §4 "Stage factory and lifecycle contract").

Register it in the team entry point:  {"voice:team": voice.team_adapter.create_stage}
Profile config (all optional):        {"tier": 0, "audio": true, "barge_in": true, "device": null, "threads": 1}

Mapping onto Spine's StageContext:
  playback_state          -> ctx.publish(msg)          (routed by Spine to Ears)
  Voice log events        -> ctx.log(event, turn, ...) (so spine/report.py sees first_audio_out / pcm_ready)
  turn finished or cut    -> ctx.complete(turn, gen, success=, reason=, gap_s=)
  unexpected worker error -> ctx.fail(reason)
"""
from . import vlog
from .stage import VoiceStage

# Voice's own bookkeeping events stay in logs/voice.jsonl only; everything else is mirrored into Spine's run log.
_LOCAL_ONLY = {"turn_done", "cache_ready"}


class VoiceTeamStage:
    def __init__(self, ctx, config=None):
        """Store callbacks only: no threads, models or messages before start() (Spine lifecycle rule)."""
        self.ctx, self.config = ctx, dict(config or {})
        self.voice = None

    # ---- lifecycle -------------------------------------------------------------------
    def start(self):
        vlog.add_sink(self._mirror)
        c = self.config
        self.voice = VoiceStage(on_event=self._on_event, tier=int(c.get("tier", 0)), device=c.get("device"),
                                threads=int(c.get("threads", 1)), audio=bool(c.get("audio", True)),
                                barge_in=bool(c.get("barge_in", True)), on_error=self.ctx.fail)
        self.voice.start()

    def feed(self, msg):
        self.voice.feed(msg)                 # non-blocking: control messages act at once, work is queued

    def stop(self):
        if self.voice is not None:
            self.voice.stop()
        vlog.remove_sink(self._mirror)

    def set_tier(self, n):
        self.voice.set_tier(int(n))          # Spine calls this at its safe boundary; Voice also waits for turn end

    # ---- outputs -----------------------------------------------------------------------
    def _mirror(self, rec):
        if rec["event"] not in _LOCAL_ONLY:
            self.ctx.log(rec["event"], rec["turn"], t=rec["t"], **rec["extra"])

    def _on_event(self, m):
        typ = m.get("type")
        if typ == "playback_state":
            self.ctx.publish({"type": "playback_state", "turn": m["turn"], "playing": bool(m["playing"]), "t": m["t"]})
        elif typ == "turn_summary":
            heard = m.get("t_first_audio") is not None
            reason = m.get("cancelled") or (None if heard else "no_audio")
            gap_s = round(sum(m.get("gaps_ms") or []) / 1000, 4)
            self.ctx.complete(m["turn"], int(m.get("gen") or 0), success=heard and not m.get("cancelled"),
                              reason=reason, gap_s=gap_s)


def create_stage(ctx, config=None):
    return VoiceTeamStage(ctx, config)
