"""
spine_core.py : reference implementations of the Spine algorithms for HNX26EPS08.
Pure Python + numpy/scipy. No model weights needed. Everything here is meant to be dropped into the
repo and fed with MEASURED numbers; the verify.py script exercises it on SYNTHETIC numbers only.
"""
from __future__ import annotations
import math, itertools
from dataclasses import dataclass, field
import numpy as np
from scipy import stats, optimize

# ---------------------------------------------------------------- 1. Bayesian endpointer
@dataclass
class PauseModel:
    """Within-turn pause durations, log-normal, left-truncated at t_min (VAD cannot see shorter pauses)."""
    mu: float
    sigma: float
    t_min: float = 0.15

    @classmethod
    def fit(cls, durations, t_min=0.15):
        d = np.asarray([x for x in durations if x >= t_min], float)
        y = np.log(d)
        a = math.log(t_min)

        def nll(p):
            mu, ls = p
            s = math.exp(ls)
            z = (y - mu) / s
            logpdf = -0.5 * z**2 - ls - 0.5 * math.log(2 * math.pi)
            logS_trunc = stats.norm.logsf((a - mu) / s)
            return -(logpdf.sum() - len(y) * logS_trunc)

        r = optimize.minimize(nll, [y.mean(), math.log(y.std() + 1e-3)], method="Nelder-Mead")
        return cls(r.x[0], math.exp(r.x[1]), t_min)

    def survival(self, t):
        """P(pause >= t | pause >= t_min)."""
        t = np.maximum(t, self.t_min)
        s = stats.norm.sf((np.log(t) - self.mu) / self.sigma)
        s0 = stats.norm.sf((math.log(self.t_min) - self.mu) / self.sigma)
        return np.minimum(s / s0, 1.0)

    def quantile_surv(self, s_target):
        """smallest t with survival(t) <= s_target."""
        s0 = stats.norm.sf((math.log(self.t_min) - self.mu) / self.sigma)
        q = stats.norm.isf(np.clip(s_target * s0, 1e-12, 1 - 1e-12))
        return np.maximum(np.exp(self.mu + self.sigma * q), self.t_min)


def endpoint_threshold(pm: PauseModel, p_end_text, eps):
    """
    Silence-time threshold at which posterior P(turn ended | text evidence, silence >= t) >= 1-eps.
      odds_post = odds(p_end_text) / S_pause(t)       (a silence that is the FINAL gap lasts forever => likelihood 1)
      => S_pause(t) <= odds(p_end_text) * eps/(1-eps)
    Monotone in silence time, so any sequential test using silence alone collapses to a hangover threshold;
    the gain can only come from the text/prosody evidence that shifts p_end_text.
    """
    p = np.clip(p_end_text, 1e-6, 1 - 1e-6)
    s_target = (p / (1 - p)) * eps / (1 - eps)
    return np.where(s_target >= 1.0, pm.t_min, pm.quantile_surv(np.minimum(s_target, 1.0)))


# ---------------------------------------------------------------- 2. Stall-free playback start
def stall_free_start(prod_times, play_durs):
    """
    prod_times[k] = time (from reply start) to produce chunk k *sequentially* (LLM decode + TTS synth, shared cap).
    play_durs[k]  = audio duration of chunk k.
    Returns (T0, ready_times): smallest playback start with no underrun at any chunk boundary.
      T0 = max_k ( r_k - sum_{j<k} D_j ),   r_k = cumulative production time.
    """
    r = np.cumsum(prod_times)
    D_before = np.concatenate([[0.0], np.cumsum(play_durs)[:-1]])
    return float(np.max(r - D_before)), r


def simulate_playback(prod_times, play_durs, T0):
    """Discrete check: returns total stall time if playback starts at T0."""
    r = np.cumsum(prod_times)
    t = T0
    stall = 0.0
    for k in range(len(prod_times)):
        if r[k] > t:
            stall += r[k] - t
            t = r[k]
        t += play_durs[k]
    return stall


def production_ratio(words_per_s, tps_tokens_per_s, tokens_per_word, tts_rtf):
    """rho = production time / audio time, sequential on a shared cap. Need rho <= ~0.8 for stall-free."""
    return words_per_s * tokens_per_word / tps_tokens_per_s + tts_rtf


# ---------------------------------------------------------------- 3. Planner
def amdahl(t1, f, c):
    return t1 * (f + (1 - f) / c)


@dataclass
class Tier:
    name: str
    stage: str            # asr | llm | tts
    quality: float        # measured on the fixed eval set, 0..1
    ram_gb: float
    # stage-specific timing params, all MEASURED at 1 thread
    t1: float = 0.0       # seconds for the unit of work at 1 thread (asr: per s audio, tts: per s audio, llm: per prompt token)
    f: float = 0.1        # serial fraction (Amdahl)
    tok_rate_1: float = 0.0   # llm decode tokens/s at 1 thread
    bw_cap: float = 1e9       # llm decode tokens/s ceiling from memory bandwidth


@dataclass
class Plan:
    asr: Tier
    llm: Tier
    tts: Tier
    c_llm: int
    c_tts: int
    spec: bool
    max_tokens: int
    pred_ttfa: float = 0.0
    pred_rho: float = 0.0
    quality: float = 0.0
    cpu_s: float = 0.0


def llm_decode_tps(t: Tier, c):
    return min(c * t.tok_rate_1, t.bw_cap)


def predict_plan(asr, llm, tts, c_llm, c_tts, spec, max_tokens, *, cap_c, hangover, asr_tail_audio=0.3,
                 resid_prompt_tokens=20, first_chunk_tokens=8, first_chunk_audio_s=1.2, out_buf=0.04,
                 words_per_s=2.6, tokens_per_word=1.4, noise_sigma=0.25, z90=1.2816, spec_waste=0.5):
    """Conservative serial model of TTFA (end of speech -> first audio). All inputs are measured numbers."""
    c_asr = cap_c                                   # ASR owns the cap while user speaks / just finished
    asr_tail = amdahl(asr.t1, asr.f, c_asr) * asr_tail_audio
    # incremental prefill hides most of the prompt; spec leaves only residual tokens
    resid = resid_prompt_tokens * (0.25 if spec else 1.0)
    prefill = amdahl(llm.t1, llm.f, c_llm) * resid
    decode1 = first_chunk_tokens / llm_decode_tps(llm, c_llm)
    synth1 = amdahl(tts.t1, tts.f, c_tts) * first_chunk_audio_s
    ttfa_mean = hangover + asr_tail + prefill + decode1 + synth1 + out_buf
    ttfa_p90 = ttfa_mean * math.exp(z90 * noise_sigma)
    # stall-free feasibility over the whole reply (sequential sharing)
    rho = production_ratio(words_per_s, llm_decode_tps(llm, c_llm), tokens_per_word, amdahl(tts.t1, tts.f, c_tts))
    cpu_s = (asr_tail * c_asr + prefill * c_llm + (max_tokens / llm_decode_tps(llm, c_llm)) * c_llm
             + synth1 * c_tts * (max_tokens / first_chunk_tokens))
    if spec:   # wasted speculative prefill: ~spec_waste extra full-prompt prefills per turn (measured in the endpoint sim: 0.3-0.7)
        cpu_s += spec_waste * amdahl(llm.t1, llm.f, c_llm) * resid_prompt_tokens * c_llm
    q = min(asr.quality, 1.0) * llm.quality * tts.quality
    return Plan(asr, llm, tts, c_llm, c_tts, spec, max_tokens, ttfa_p90, rho, q, cpu_s)


def choose_plan(asr_tiers, llm_tiers, tts_tiers, *, cap_c, ram_gb, slo_p90, hangover, rho_max=0.8,
                ram_margin=0.9, spec_options=(False, True), max_tokens_options=(60,)):
    """Exhaustive search (a few hundred plans). max quality s.t. SLO, RAM, stall-free; tie-break min CPU-seconds."""
    best, feasible = None, []
    for a, l, t in itertools.product(asr_tiers, llm_tiers, tts_tiers):
        if a.ram_gb + l.ram_gb + t.ram_gb > ram_gb * ram_margin:
            continue
        for c_l, c_t, sp, mt in itertools.product(range(1, cap_c + 1), range(1, cap_c + 1), spec_options, max_tokens_options):
            p = predict_plan(a, l, t, c_l, c_t, sp, mt, cap_c=cap_c, hangover=hangover)
            if p.pred_ttfa <= slo_p90 and p.pred_rho <= rho_max:
                feasible.append(p)
    if not feasible:
        return None, []
    feasible.sort(key=lambda p: (-round(p.quality, 4), p.cpu_s))
    return feasible[0], feasible


# ---------------------------------------------------------------- 4. Energy calibrator
def nnls_energy(cpu_seconds_by_stage: np.ndarray, energy_j: np.ndarray, idle_w: float, wall_s: np.ndarray):
    """
    Rows = runs, columns = stages (CPU-seconds from cgroup cpu.stat per stage).
    energy_j - idle_w*wall_s  ~=  X @ e   with e >= 0 (J per CPU-second per stage).
    """
    y = energy_j - idle_w * wall_s
    e, resid = optimize.nnls(cpu_seconds_by_stage, y)
    return e, resid


# ---------------------------------------------------------------- 5. Tier controller (between turns + fast loop)
@dataclass
class ControllerCfg:
    slo_p90: float = 1.0
    down_after_viol: int = 2          # violations in the last window to step down
    window: int = 3
    up_after_ok: int = 5              # consecutive turns with headroom to step up
    headroom: float = 0.10            # fractional slack on PREDICTED p90 needed to step up (0.25 was too strict: never recovered)
    probation_s: float = 90.0         # a down-switch within this time of an up-switch counts as a failed up-switch
    max_backoff: int = 6              # dwell multiplier cap (2**k)
    dwell_s: float = 30.0
    rtf_spec_off: float = 0.85        # fast loop: ASR real-time factor above which speculation is disabled


class TierController:
    """Levels are indices into a ladder ordered best quality (0) -> cheapest (n-1)."""
    def __init__(self, n_levels, cfg=ControllerCfg(), start=0):
        self.n, self.cfg, self.level = n_levels, cfg, start
        self.hist, self.ok_run, self.last_switch_t = [], 0, -1e9
        self.switches = []
        self.backoff = 0                  # exponent k: dwell = dwell_s * 2**k, grows on failed up-switches
        self.last_up_t = -1e9
        self.last_change_t = 0.0

    def replan_on_cap_change(self, feasible_level, t):
        """Cap change detected from cgroup files: jump straight to the best level the model says is feasible."""
        if feasible_level != self.level:
            self.switches.append((t, self.level, feasible_level, "cap"))
            self.level, self.ok_run, self.last_switch_t = feasible_level, 0, t

    def on_turn(self, ttfa, t, level_pred_next_ok):
        """ttfa measured this turn; level_pred_next_ok = model-predicted p90 TTFA at level-1 (one step richer)."""
        c = self.cfg
        self.hist.append(ttfa > c.slo_p90)
        self.hist = self.hist[-c.window:]
        severe = ttfa > 1.5 * c.slo_p90
        if (sum(self.hist) >= c.down_after_viol or severe) and self.level < self.n - 1:
            if t - self.last_up_t <= c.probation_s:          # we stepped up and it failed: be more patient next time
                self.backoff = min(self.backoff + 1, c.max_backoff)
            self.switches.append((t, self.level, self.level + 1, "down"))
            self.level += 1; self.ok_run = 0; self.hist = []; self.last_switch_t = t
            return
        has_room = (level_pred_next_ok is not None) and level_pred_next_ok <= c.slo_p90 * (1 - c.headroom)
        self.ok_run = self.ok_run + 1 if (ttfa <= c.slo_p90 and has_room) else 0
        if self.ok_run >= c.up_after_ok and self.level > 0 and (t - self.last_switch_t) >= c.dwell_s * (2 ** self.backoff):
            self.switches.append((t, self.level, self.level - 1, "up"))
            self.level -= 1; self.ok_run = 0; self.last_switch_t = t; self.last_up_t = t
        elif self.backoff and (t - self.last_switch_t) > 600:   # long stability forgives past failures
            self.backoff = 0

    @staticmethod
    def fast_loop(asr_rtf, throttle_frac, mem_frac, c=ControllerCfg()):
        """Within-turn, degrade-only actions. Returns the set of actions to take now."""
        acts = set()
        if asr_rtf > c.rtf_spec_off or throttle_frac > 0.05:
            acts.add("spec_off")
        if mem_frac > 0.92:
            acts.add("drop_standby_tier")
        if throttle_frac > 0.20:
            acts.add("shorten_reply")
        return acts
