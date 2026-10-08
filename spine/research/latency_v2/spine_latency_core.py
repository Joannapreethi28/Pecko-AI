"""Latency research primitives, standard-library only; not a live controller.

Times are seconds on a common relative clock. Profiles must already describe a
feasible CPU/RAM schedule. Known future releases make chunk optimization an oracle
for that supplied trace; using predictions does not make it an online guarantee.
"""
from dataclasses import dataclass
import math
from typing import Iterable


def _nonnegative(*values):
    if any(not math.isfinite(x) or x < 0 for x in values):
        raise ValueError('Expected finite nonnegative values')


def playback_start(ready, durations, commit=0.0, output_delay=0.0):
    """Earliest no-gap start for known in-order chunk readiness and durations."""
    if not ready or len(ready) != len(durations):
        raise ValueError('Nonempty, equal-length traces required')
    _nonnegative(*ready, *durations, commit, output_delay)
    if any(d <= 0 for d in durations):
        raise ValueError('Audio durations must be positive')
    if any(a > b for a, b in zip(ready, ready[1:])):
        raise ValueError('Ready times must be in order')
    start = commit + output_delay
    played = 0.0
    for r, d in zip(ready, durations):
        start = max(start, r + output_delay - played)
        played += d
    return start


def playback_gaps(ready, durations, start, output_delay=0.0):
    """Includes startup waiting if start precedes the first available chunk."""
    playback_start(ready, durations, output_delay=output_delay)  # validate
    _nonnegative(start)
    t, gaps = start, []
    for r, d in zip(ready, durations):
        gap = max(0.0, r + output_delay - t)
        gaps.append(gap)
        t += gap + d
    return tuple(gaps)


def first_audio(commit, ready, output_delay=0.0):
    _nonnegative(commit, ready, output_delay)
    return max(commit, ready) + output_delay


def critical_path_gain(commit_before, ready_before, commit_after, ready_after):
    """Counts both hidden preparation and any induced commitment delay."""
    return first_audio(commit_before, ready_before) - first_audio(commit_after, ready_after)


def speculation_expected_gain(p_valid, success_gain, failure_penalty):
    if not 0 <= p_valid <= 1 or not math.isfinite(success_gain):
        raise ValueError('Invalid probability or gain')
    _nonnegative(failure_penalty)
    return p_valid * success_gain - (1 - p_valid) * failure_penalty


def endpoint_posterior(prior_at_visible_gap, conditional_pause_survival):
    """Mixture model: final gap survives; within-turn gap survives with S(t)."""
    p, s = prior_at_visible_gap, conditional_pause_survival
    if not (0 <= p <= 1 and 0 <= s <= 1):
        raise ValueError('Probabilities must be in [0,1]')
    denominator = p + (1 - p)*s
    if denominator == 0:
        raise ValueError('Conditioning event has zero probability')
    return p / denominator


def conformal_upper_margin(scores, alpha):
    """One-sided split-calibration quantile; infinity when n is insufficient.

    Coverage requires a frozen predictor/policy and exchangeable calibration/test
    scores. Use one maximum residual per turn, not correlated chunk residuals.
    """
    if not 0 < alpha < 1:
        raise ValueError('alpha must lie in (0,1)')
    if any(not math.isfinite(s) for s in scores):
        raise ValueError('Scores must be finite')
    n = len(scores)
    rank = math.ceil((n+1)*(1-alpha))
    if rank > n:
        return math.inf
    return max(0.0, sorted(scores)[rank-1])


def zero_failure_upper(n, delta=.05):
    """One-sided binomial bound for zero failures in n independent trials."""
    if n <= 0 or not 0 < delta < 1:
        raise ValueError('Require n>0 and delta in (0,1)')
    return -math.expm1(math.log(delta)/n)


@dataclass(frozen=True)
class ChunkEdge:
    begin: int
    end: int
    release: float
    synth: float
    audio: float
    energy: float = 0.0
    decode: float = 0.0

    def __post_init__(self):
        if self.begin < 0 or self.end <= self.begin:
            raise ValueError('Forward chunk boundaries required')
        _nonnegative(self.release, self.synth, self.audio, self.energy, self.decode)
        if self.audio <= 0:
            raise ValueError('Positive audio duration required')


@dataclass(frozen=True)
class ChunkState:
    boundary: int
    finish: float
    audio: float
    start_bound: float
    energy: float
    chunks: tuple[ChunkEdge, ...]


def _dominates(a, b):
    # Comparable states end at the same text boundary and use the same mode.
    return (a.finish <= b.finish and a.audio >= b.audio
            and a.start_bound <= b.start_bound and a.energy <= b.energy)


def optimize_chunks(edges: Iterable[ChunkEdge], end: int, *, commit=0.0,
                    output_delay=0.0, mode='fixed_release', energy_budget=math.inf,
                    frontier_limit=10000):
    """Pareto-label DAG optimization of predicted stall-free first audio.

    fixed_release: decode is already included in edge.release, from a fixed
        feasible LLM lane; one sequential TTS lane processes chunks.
    serial: shared CPU runs each edge.decode then edge.synth sequentially;
        edge.release is an external earliest-start constraint, usually zero.

    No beam approximation: limit overflow raises rather than claiming optimality.
    Speech/prosody eligibility must already be encoded in allowed edges.
    """
    _nonnegative(commit, output_delay)
    if mode not in ('fixed_release', 'serial') or end <= 0 or energy_budget < 0:
        raise ValueError('Invalid mode, endpoint or budget')
    if math.isnan(energy_budget) or frontier_limit <= 0:
        raise ValueError('Invalid budget or frontier limit')
    graph = {}
    for edge in edges:
        if edge.end > end or (mode == 'fixed_release' and edge.decode != 0):
            raise ValueError('Edge incompatible with endpoint or release mode')
        graph.setdefault(edge.begin, []).append(edge)
    frontiers = {0: [ChunkState(0, 0.0, 0.0, commit+output_delay, 0.0, ())]}
    for i in range(end):
        for state in frontiers.get(i, ()):
            for edge in graph.get(i, ()):
                finish = max(state.finish, edge.release) + edge.decode + edge.synth
                new = ChunkState(edge.end, finish, state.audio+edge.audio,
                                 max(state.start_bound, finish+output_delay-state.audio),
                                 state.energy+edge.energy, state.chunks+(edge,))
                if new.energy > energy_budget:
                    continue
                frontier = frontiers.setdefault(edge.end, [])
                if any(_dominates(old, new) for old in frontier):
                    continue
                frontier[:] = [old for old in frontier if not _dominates(new, old)]
                frontier.append(new)
                if len(frontier) > frontier_limit:
                    raise RuntimeError('Exact frontier limit exceeded; reduce candidate graph')
    return min(frontiers.get(end, ()),
               key=lambda x: (x.start_bound, x.energy, x.finish), default=None)


@dataclass(frozen=True)
class ProfiledAction:
    name: str
    latency_samples: tuple[float, ...]
    success_lower: float
    cutoff_upper: float
    gap_upper: float
    transition_peak_bytes: int
    energy_upper: float
    cpu_seconds_upper: float
    schedule_feasible: bool = True

    def __post_init__(self):
        if not self.latency_samples:
            raise ValueError('Latency samples required')
        _nonnegative(*self.latency_samples, self.transition_peak_bytes,
                     self.energy_upper, self.cpu_seconds_upper)
        if any(not 0 <= x <= 1 for x in (self.success_lower,self.cutoff_upper,self.gap_upper)):
            raise ValueError('Quality/risk bounds must be probabilities')


def _quantile(values, q):
    return sorted(values)[max(0, math.ceil(q*len(values))-1)]


def choose_latency_action(actions, *, quality_floor, cutoff_budget, gap_budget,
                          ram_bytes, energy_budget, cpu_seconds_budget):
    """Latency first (p90, p50), energy tie-break; no weighted quality product.

    Inputs must include transition cost and use comparable whole-turn profiles.
    This is empirical ranking, not a population quantile guarantee.
    """
    if any(not 0 <= v <= 1 for v in (quality_floor, cutoff_budget, gap_budget)):
        raise ValueError('Quality/risk thresholds must be probabilities')
    _nonnegative(ram_bytes, energy_budget, cpu_seconds_budget)
    feasible = [a for a in actions if a.schedule_feasible
                and a.success_lower >= quality_floor
                and a.cutoff_upper <= cutoff_budget and a.gap_upper <= gap_budget
                and a.transition_peak_bytes <= ram_bytes
                and a.energy_upper <= energy_budget
                and a.cpu_seconds_upper <= cpu_seconds_budget]
    return min(feasible, key=lambda a: (_quantile(a.latency_samples,.9),
               _quantile(a.latency_samples,.5),a.energy_upper), default=None)
