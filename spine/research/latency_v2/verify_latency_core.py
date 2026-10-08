"""Independent small-case enumeration and synthetic counterexamples."""
from dataclasses import replace
import json
import math
from pathlib import Path
import random
from spine_latency_core import (
    ChunkEdge, ProfiledAction, choose_latency_action, conformal_upper_margin,
    critical_path_gain, endpoint_posterior, first_audio, optimize_chunks,
    playback_gaps, playback_start, zero_failure_upper,
)


def enumerate_paths(edges, end, i=0):
    if i == end:
        yield ()
    for e in edges:
        if e.begin == i:
            for rest in enumerate_paths(edges, end, e.end):
                yield (e,)+rest


def replay(path, commit, delay):
    now = 0.0
    ready, durations = [], []
    for e in path:
        now = max(now,e.release)+e.decode+e.synth
        ready.append(now)
        durations.append(e.audio)
    start = playback_start(ready,durations,commit,delay)
    return (start,sum(e.energy for e in path),now),ready,durations


def main():
    rng = random.Random(81126)
    checks = {}
    for _ in range(2000):
        n = rng.randrange(1,8)
        ready = sorted(rng.uniform(0,4) for _ in range(n))
        durations = [rng.uniform(.05,1) for _ in range(n)]
        commit, delay = rng.uniform(0,2),rng.uniform(0,.1)
        start = playback_start(ready,durations,commit,delay)
        assert sum(playback_gaps(ready,durations,start,delay)) < 1e-10
        earlier = start-1e-5
        assert earlier < commit+delay or sum(playback_gaps(ready,durations,earlier,delay)) > 1e-7
    checks['minimal_stall_free_start'] = 2000

    paths_checked = 0
    for mode in ('fixed_release','serial'):
        for _ in range(300):
            n = rng.randrange(2,8)
            edges = []
            for i in range(n):
                for j in range(i+1,min(n,i+4)+1):
                    # Dyadic values avoid accidental float tie-breaking in exact ranking.
                    edges.append(ChunkEdge(i,j,j/32 if mode=='fixed_release' else 0,
                        rng.randrange(1,12)/128,rng.randrange(1,20)/128,
                        rng.randrange(1,10)/8,0 if mode=='fixed_release' else rng.randrange(1,8)/128))
            commit,delay,budget = 1/16,1/64,rng.uniform(.5,6)
            all_results = []
            for path in enumerate_paths(edges,n):
                result,_,_ = replay(path,commit,delay)
                paths_checked += 1
                if result[1] <= budget:
                    all_results.append(result)
            best = optimize_chunks(edges,n,commit=commit,output_delay=delay,
                                   mode=mode,energy_budget=budget)
            if not all_results:
                assert best is None
            else:
                assert best is not None
                actual = (best.start_bound,best.energy,best.finish)
                expected = min(all_results)
                # Floating-point roundoff can alter an exactly tied secondary objective.
                assert math.isclose(actual[0],expected[0],abs_tol=1e-12)
                assert math.isclose(actual[1],expected[1],abs_tol=1e-12)
                assert math.isclose(actual[2],expected[2],abs_tol=1e-12), (mode,actual,expected)
    checks['chunk_graphs_vs_exhaustive_paths'] = 600

    # Interval forecasts need one simultaneous score per turn, not chunkwise 95%.
    assert math.isinf(conformal_upper_margin([0]*10,.05))
    assert conformal_upper_margin(list(range(19)),.05) == 18
    assert conformal_upper_margin([-2]*19,.05) == 0
    checks['conformal_rank_edges'] = 3

    # Exhaustive leave-one-out ranks establish finite-sample rank coverage.
    for n in range(2,40):
        for alpha in (.1,.2,.3):
            all_scores = list(range(n+1))
            covered = sum(s <= conformal_upper_margin(all_scores[:i]+all_scores[i+1:],alpha)
                          for i,s in enumerate(all_scores))
            assert covered/(n+1) >= 1-alpha-1e-12
    checks['exchangeable_rank_enumeration'] = 114

    # Posterior monotonicity only for a fixed conditional prior and survival model.
    for p in (.1,.5,.9):
        posts = [endpoint_posterior(p,s/100) for s in range(100,-1,-1)]
        assert all(a <= b for a,b in zip(posts,posts[1:]))
    checks['conditional_endpoint_monotonicity'] = 3

    good = ProfiledAction('fast',(.5,.6,.7),.85,.01,.01,100,5,2)
    slow = replace(good,name='richer but slow',latency_samples=(.8,.9,1.0),success_lower=.95)
    low_quality = replace(good,name='invalid quality',latency_samples=(.1,.1,.1),success_lower=.6)
    wrong_ram = replace(good,name='transition too large',latency_samples=(.1,.1,.1),transition_peak_bytes=1000)
    opts = dict(quality_floor=.8,cutoff_budget=.02,gap_budget=.02,ram_bytes=200,
                energy_budget=6,cpu_seconds_budget=3)
    assert choose_latency_action([slow,good,low_quality,wrong_ram],**opts) == good
    assert choose_latency_action([low_quality,wrong_ram],**opts) is None
    checks['latency_first_and_constraints'] = 2

    # Same first-audio time despite extra work once the commit path dominates.
    assert math.isclose(critical_path_gain(.6,.9,.6,.5),.3)
    assert critical_path_gain(.6,.5,.6,.2) == 0
    assert math.isclose(critical_path_gain(.6,.9,1.0,.5),-.1)
    checks['critical_path_saturation_and_contention'] = 3

    for args in (([],[]),([1],[0]),([2,1],[1,1])):
        try:
            playback_start(*args)
            raise AssertionError('Invalid trace accepted')
        except ValueError:
            pass
    checks['invalid_trace_rejection'] = 3

    n=8
    edges=[ChunkEdge(i,j,.025*j,.12+.08*(j-i),.12*(j-i))
           for i in range(n) for j in range(i+1,n+1)]
    winner=optimize_chunks(edges,n)
    one_word=tuple(next(e for e in edges if e.begin==i and e.end==i+1) for i in range(n))
    whole=(next(e for e in edges if e.begin==0 and e.end==n),)
    tiny, tiny_ready, tiny_dur = replay(one_word,0,0)
    full,_,_ = replay(whole,0,0)
    win,_,_ = replay(winner.chunks,0,0)
    result={
        'scope':'Synthetic algorithm verification; no measured device or model speedups',
        'seed':81126,'checks':checks,'candidate_paths_enumerated':paths_checked,
        'synthetic_chunk_example':{
            'eight_word_response':True,
            'one_word_first_ready_s':tiny_ready[0],
            'one_word_stall_free_start_s':tiny[0],
            'one_word_gaps_if_played_immediately_s':sum(playback_gaps(tiny_ready,tiny_dur,tiny_ready[0])),
            'whole_response_start_s':full[0],
            'optimized_chunk_word_counts':[e.end-e.begin for e in winner.chunks],
            'optimized_stall_free_start_s':win[0],
        },
        'zero_failures_60_trials_95pct_upper':zero_failure_upper(60),
        'independent_zero_failure_trials_needed_for_2pct_at_95pct':math.ceil(math.log(.05)/math.log(.98)),
        'limitations':['Known-release chunk oracle is not causal future knowledge.',
                      'Calibrated deployment/prediction accuracy is untested.',
                      'No real latency, energy, quality or Linux enforcement measurement.'],
    }
    Path(__file__).with_name('latency_verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
