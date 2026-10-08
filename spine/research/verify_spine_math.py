"""Synthetic algebra checks only. No inference or hardware benchmarking."""
import json
import math
from pathlib import Path
import random


def utility(p, g, d, es, ef, lam):
    return p * g - (1 - p) * d - lam * (p * es + (1 - p) * ef)


def wilson_lower(successes, n, z=1.96):
    if n == 0:
        return 0.0
    phat = successes / n
    return (phat + z*z/(2*n) - z*math.sqrt(
        phat*(1-phat)/n + z*z/(4*n*n))) / (1 + z*z/n)


def timing(releases, synthesis, durations, audio_delay):
    finishes, starts, gaps = [], [], []
    for k, (release, synth, duration) in enumerate(zip(releases, synthesis, durations)):
        finish = max(release, finishes[-1] if finishes else 0.0) + synth
        ready = finish + audio_delay
        prior_end = starts[-1] + durations[k-1] if starts else ready
        finishes.append(finish)
        starts.append(max(ready, prior_end))
        gaps.append(max(0.0, ready-prior_end))
    return finishes, starts, gaps


def tick_timing(releases, synthesis, durations, audio_delay):
    """Independent discrete event tick simulator; inputs are integer ticks."""
    remaining = 0
    worker_index = 0
    ready_times = []
    starts = []
    playing_until = 0
    playback_index = 0
    for t in range(10000):
        if remaining:
            remaining -= 1
            if remaining == 0:
                ready_times.append(t + audio_delay)
                worker_index += 1
        if remaining == 0 and worker_index < len(releases) and t >= releases[worker_index]:
            remaining = synthesis[worker_index]
        if (playback_index < len(ready_times) and t >= ready_times[playback_index]
                and t >= playing_until):
            starts.append(t)
            playing_until = t + durations[playback_index]
            playback_index += 1
        if playback_index == len(releases):
            return starts
    raise AssertionError('Simulator did not terminate')


def main():
    rng = random.Random(20261008)
    counts = {}
    max_error = 0.0
    for _ in range(100000):
        p = rng.random()
        g, d = rng.uniform(-1, 2), rng.uniform(0, 2)
        es, ef = rng.uniform(-2, 3), rng.uniform(-2, 3)
        lam, delta = rng.uniform(0, 2), rng.uniform(0, .1)
        a = g+d-lam*(es-ef)
        expanded = p*a-d-lam*ef
        direct = utility(p, g, d, es, ef, lam)
        max_error = max(max_error, abs(expanded-direct))
        assert math.isclose(expanded, direct, abs_tol=1e-12)
        if abs(a) > 1e-10:
            threshold = (d+lam*ef+delta)/a
            gate = p > threshold if a > 0 else p < threshold
            assert gate == (direct > delta)
    counts['speculation_identity_and_signed_threshold'] = 100000

    # Explicit outcome enumeration independently checks expected utility.
    successes = 80
    costs = [-.35+.1*.2]*successes + [.12+.1*1.]*(100-successes)
    assert math.isclose(-sum(costs)/100, utility(.8,.35,.12,.2,1.,.1), abs_tol=1e-12)
    counts['outcome_enumeration'] = 1

    # Fluid queue: recurrence versus explicit integer service/arrival accounting.
    for _ in range(10000):
        q, arrival, service = rng.randrange(500), rng.randrange(40), rng.randrange(50)
        expected = len(list(range(q+arrival))[service:])
        assert max(0, q+arrival-service) == expected
    counts['queue_conservation'] = 10000

    # Constant-rate queue growth over a continuous utterance.
    q = 0.0
    for _ in range(200):
        q = max(0, q+.1-.8*.1)
    assert math.isclose(q, 4.0, abs_tol=1e-10)
    counts['unstable_queue_example'] = 1

    for _ in range(5000):
        n = rng.randrange(1, 8)
        releases = sorted(rng.randrange(0, 80) for _ in range(n))
        synthesis = [rng.randrange(1, 15) for _ in range(n)]
        durations = [rng.randrange(1, 20) for _ in range(n)]
        delay = rng.randrange(0, 5)
        _, predicted, gaps = timing(releases, synthesis, durations, delay)
        observed = tick_timing(releases, synthesis, durations, delay)
        assert predicted == observed
        assert all(g >= 0 for g in gaps)
    counts['playback_recurrence_vs_tick_simulation'] = 5000

    # Turn cutoff formula versus exhaustive independent binary pause outcomes.
    for n in range(1, 8):
        eps = .1
        f = (1-eps)**(1/n)
        cutoff = 0.0
        for mask in range(1, 1 << n):
            failed = mask.bit_count()
            cutoff += (1-f)**failed * f**(n-failed)
        assert math.isclose(cutoff, eps, abs_tol=1e-12)
    counts['pause_risk_exact_enumeration'] = 7

    for n in range(1, 101):
        values = [wilson_lower(s,n) for s in range(n+1)]
        assert all(-1e-12 <= x <= 1 for x in values)
        assert all(a <= b for a,b in zip(values,values[1:]))
    counts['wilson_bounds_and_monotonicity'] = 5150

    # Steady-state dominance can be reversed by transition costs.
    # Lower latency/energy is better; both actions have equal quality.
    resident = {'latency': .5, 'energy': 1.5, 'switch': 0.0}
    other = {'latency': .3, 'energy': 1.0, 'switch': 1.0}
    score = lambda a: a['latency']+.1*a['energy']+a['switch']
    assert other['latency'] < resident['latency'] and other['energy'] < resident['energy']
    assert score(resident) < score(other)
    counts['transition_counterexample'] = 1

    report = {
        'scope': 'Synthetic mathematical consistency checks; no measured model/controller gains',
        'seed': 20261008,
        'checks': counts,
        'total_checks': sum(counts.values()),
        'maximum_speculation_identity_error': max_error,
        'toy_speculation_threshold': (.12+.1*1.+.02)/(.35+.12-.1*(.2-1.)),
        'toy_speculation_utility_seconds': utility(.8,.35,.12,.2,1.,.1),
        'high_pressure_threshold': (.30+.1*1.+.02)/(.02+.30-.1*(.2-1.)),
        'limitations': [
            'No hardware, ASR, LLM, TTS or energy measurement.',
            'Fluid queue and constant audio delay are simplified models.',
            'Pause-risk enumeration assumes independent pauses.',
            'Wilson bounds do not ensure validity under distribution shift.',
            'No verification of real runtime prompt/KV reuse or Linux enforcement.'
        ]
    }
    output = Path(__file__).with_name('math_verification.json')
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
