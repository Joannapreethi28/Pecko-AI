# Spine software delivery and deferred hardware acceptance

Build here on Windows using explicit placeholders. Ubuntu VM validation happens
at the end, as requested by Sir Jabin. No Linux counters or voice performance
are fabricated to complete software milestones.

## Portable delivery: 5 of 5 implemented and verified

| Deliverable | Acceptance evidence | Status |
|---|---|---|
| 1. Foundations and contract coordination | Shared clock/log, bounded event bus, lifecycle, cancellation and exact-token commit checks | Built, tested |
| 2. Supervised, swappable runtime | Stage contexts/registry, placeholder profile, ordinary/hesitation/correction scenarios, owned engine-process startup/cleanup | Built, tested; synthetic runtime |
| 3. Experiment evidence tooling | Declared cases, deadlines, failures/unstarted cases, manifests, traces and generation-aware reports | Built, tested |
| 4. Monitoring and reactive control | 200 ms sampler, cgroup accounting, package RAPL parser, calibrated profile hook and guarded between-turn transitions | Built; fixtures and synthetic degradation demo |
| 5. Review and Ubuntu handoff | Generated HTML dashboard, external live terminal viewer, preflight and integration documentation | Built; browser checked |

This counts software deliverables only. Advanced action selection, speculation
admission and chunk optimization remain gated on real C-versus-R measurements.
The required end-to-end baseline still needs actual engine adapters.

## Recorded-input integration milestone: 3 of 3 built

| Addition | Acceptance evidence | Status |
|---|---|---|
| Real-time WAV ingress | Bounded PCM frames, capture timestamps, EOS labels, cancellation, integrity checks and reference-text placeholder | Built; fixture run and tests |
| Paired comparison | Input/model/cap/timeout matching; failed/missing cases retained; synthetic gains withheld | Built; matching/mismatch tests |
| Repeated execution | Shared seeded case order, rotating profile order, six retained runs, three comparisons and suite review page | Built; end-to-end batch run |

See [recorded input instructions](RECORDED_INPUT.md). Actual engines and recorded
human speech remain deferred; the smoke input is tone/reference text only.

## Original project phases: hardware-inclusive acceptance remains 0 of 8

| Project phase | Built Spine software | Deferred acceptance |
|---|---|---|
| 1. L0 foundations | Clock/log, launcher, preflight | Ubuntu cap/offline check; local weights |
| 2. L1 real loop | Swappable placeholder runtime, hold/release, engine supervision | Ears/Brain/Voice replacement, actual audible capped loop |
| 3. L2 baseline + decisive experiment | WAV ingress, repeated paired runner, comparisons, reports, accounting | Real B0, paired traces at 1 and 2 CPUs |
| 4. Phone feasibility spike | Shared runtime contract remains portable | Termux feasibility check after L1 |
| 5. PC2 core improvements | Reactive ladder, monitoring, dashboard and private release plumbing | Profile calibration, engine streaming/cache improvements, A0–A4 measurements |
| 6. L4 stability | Failure paths and synthetic degradation wired | Integrated real-loop stability, A5–A7, feature freeze |
| 7. P1 phone | No phone-specific implementation claim | Phone integration or honest component-only evidence |
| 8. L5 evaluation/submission | Reproducible evidence files and review tool | Held-out repeats, ablations, real numbers, videos and submission |

## Immediate runnable paths

```sh
python -m spine.runtime --profile spine/examples/runtime.placeholder.json --plan spine/examples/plan.scripted.json --output data/results/mock-contract-01
python -m spine.demo --output data/results/mock-control-01
python -m spine.dashboard data/results/mock-control-01/events.jsonl --watch
python -m unittest discover -s tests
```

Use fresh output directories. Runtime and demo runs generate `dashboard.html`,
`resources.json`, `report.json`, manifest, plan, event log and completion summary.
The synthetic control demo changes T0→T1→T0 after turn completion; its CPU/PSI
inputs are deliberately simulated. The placeholder runtime has no microphone,
ASR, tokenizer, LLM, TTS or speaker.

## Replacing placeholders without waiting for Ubuntu

Register a trusted Python factory under `ears:name`, `brain:name`, or `voice:name`
and call `runtime.make_factory(profile, registry)` from application code. Each
factory accepts `(StageContext, config)` and returns a stage with
`start/feed/stop/set_tier`. The registry is code; logs/plans never import or
execute factories. Switch one role's profile entry at a time, retaining
`synthetic:true` while any placeholders remain. Set it false only after all
placeholders and synthetic inputs have been removed and actual engines are wired.

`StageContext` provides role-bound publishing, logging and failure callbacks.
Brain uses `prepared` and `validate` with full serialized model token IDs.
Voice uses `complete` only after work/playback stops and answer scoring is known.
Ears' replay method accepts a declared case and turn, starts asynchronous WAV
replay, and returns capture-start + independently labelled EOS offset. The
placeholder replay demonstrates the expected callback shape using scripted
events instead of audio. Real mic listening need not use ReplayDriver.

Linux-only measurement adapters are optional during development. Missing cgroup
or RAPL support stays unavailable; it does not stop placeholder development.

## Ubuntu acceptance at the end

Create the venv and copy local models/binaries using the role owners' instructions.
Choose actual logical CPU IDs, then launch the real runtime under the wrapper.
For the current placeholder smoke run:

```sh
sudo .venv/bin/python -m spine.linux --cpus 0,1 -- -m spine.runtime --profile spine/examples/runtime.placeholder.json --plan spine/examples/plan.scripted.json --output data/results/ubuntu-placeholder-01
```

Inside the same scope, inspect `python -m spine.preflight --model /absolute/model.gguf`
plus the other declared engine files using additional --model arguments. The
preflight fails honestly outside Linux or without supplied model files; it never
claims audible/offline readiness. Declare that the final host is a VM, confirm
network-off and CPU-only engines, and independently cross-check speaker timing.
If RAPL is unavailable, report CPU-s and RAM with energy unavailable.
