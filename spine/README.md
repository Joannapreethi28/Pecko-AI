# Spine portable runtime

**Portable delivery: 5/5 built and verified with mocks/fixtures.** Hardware-inclusive
project acceptance remains 0/8; Ubuntu VM and real-engine checks happen at the end.
See [delivery checklist and deferred gates](BUILD_STATUS.md).

Run the contract-faithful placeholders now:

```sh
python -m spine.runtime --profile spine/examples/runtime.placeholder.json --plan spine/examples/plan.scripted.json --output data/results/mock-contract-01
python -m spine.demo --output data/results/mock-control-01
```

The first command covers ordinary speech, cancellation/correction and a changed
final prompt. The second connects simulated pressure to guarded T0→T1→T0
switches. Both save dashboards and reproducible evidence. Pick fresh directories.

Implemented: shared monotonic clock and JSONL logger, bounded event-driven v2
transport, startup/cleanup, text-only mock, Ubuntu cap launcher, queued v2.1
prompt-token validation, turn/generation filtering and a bounded PCM hold helper.
This is not yet a working voice assistant.

Also implemented: offline per-turn reporting and read-only cgroup CPU/RAM/PSI
snapshots, with accounting helpers and synthetic fixtures. Linux measurement
hardware remains unverified. Package sampling is implemented and fixture-tested.

The reactive tier ladder and explicit between-turn tier application are built.
Risk classification thresholds and model-transition feasibility still need
calibration and integration with the real engine supervisor.

The experiment runner now executes declared cases and saves complete evidence,
including timeouts, fatal worker errors, interruptions and unstarted cases.
Engine process supervision also supplies bounded readiness and exit handling.

From the repository root (Python 3.10+, standard library only):

```sh
python -m spine.mock --text "Hello Pecko"
python -m unittest discover -s tests -v
python -m spine.linux --cpus 0,1 --dry-run
```

Expect readiness and routing JSONL events, including `mock_text_received`,
then `commit`, then `mock_release`.
Mock output is explicitly synthetic; there is no audio or latency benchmark.

## Experiment runner

Run a three-turn mock experiment with a NEW output directory:

```sh
python -m spine.experiment --plan spine/examples/plan.synthetic.json --output data/results/mock-run-01
```

An existing output directory is rejected so evidence cannot be overwritten.
The runner writes `plan.json`, `events.jsonl`, `manifest.json`,
`runner_summary.json` and `report.json`. The summary reports confirmed pipeline
completions. The mock has no speaker: its report correctly withholds headline
latency and marks sustained-content-audio evidence as missing. Completing the
mock pipeline does not establish a successful voice answer.

Each plan declares `run_id`, `platform`, `configuration`, `synthetic`, and a
`cases` list with unique `case_id` and positive `timeout_s`. Mock cases also need
`text`; optional `behavior` is `reply`, `timeout` or `error`. The mock CLI
requires `synthetic:true`. Real drivers use the `ExperimentRunner` Python API
with a bus factory and a `CaseDriver`; real adapters are not bundled yet.

`CaseDriver.begin(case, turn, bus, log)` must enqueue replay promptly, return
the independently labelled EOS on the host monotonic clock, and allow workers
to run asynchronously. The runner waits on the event queue until EOS + timeout.
Cases run in declared order; use separate plans for randomized repetitions.
Startup/driver methods must return; the runner cannot forcibly kill a hung
Python stage method. Use the bounded engine supervisor below for child startup.

After all work and playback stop and the acceptable-answer score is available,
call `bus.complete_turn(turn, gen, success=..., reason=..., gap_s=...)` from the
adapter/supervisor. This queued callback records `turn_end`, closes that turn,
and applies pending tiers. Stale/cancelled/uncommitted successful completions
are ignored. Normal scored answer failures can continue to the next case after
confirmed stop. Timeout or fatal error aborts the run and stops the stages;
all remaining cases stay visible as unstarted with no fabricated EOS timestamp.

Worker threads must catch their exceptions and call `bus.fail(stage, reason)`.
This wakes the event dispatcher even with a full queue, so a background failure
cannot quietly become a later timeout. Queue overload also marks a fatal bus
failure. Each stage's `stop` must cancel/join its workers and flush playback.

The manifest is checkpointed before execution and after each EOS is established.
Unstarted turns have `t_eos:null` and `not_started:true`; the reporter preserves
them as incomplete. Interruptions/failures retain declared cases and prior logs.
The runner records timing/status evidence and can attach continuous pressure and
package-energy sampling. Use --telemetry on spine.experiment, optional
--cgroup PATH, --rapl-root PATH, and --policy PROFILE.json. The placeholder
runtime attaches measurement adapters automatically when the host supports them.
Unavailable telemetry does not block portable development. Every run also writes
dashboard.html; attached monitoring writes resources.json with per-turn and
aggregate accounting. Energy per turn stays unavailable without package counters.

## Engine process integration

`spine.process.EngineProcess` starts an explicit executable argument list without
a shell. Point it at the Brain owner's CPU-only llama-server binary and local
model; use a dedicated localhost port and a fresh engine-log path. Connect its
failure callback to `lambda reason: bus.fail("brain", reason)`.

During Brain `start`, call `engine.start(health_url="http://127.0.0.1:8080/health",
readiness_timeout_s=30)`, then perform Brain's model-specific warm-up and prompt
checks. Startup rejects an already-ready health endpoint to avoid mistaking an
existing server outside the cap for the owned child. Use a dedicated port;
HTTP readiness alone does not identify model contents or prove warm-up.
Readiness timeout/early exit stops the child. Health checks contact only literal
loopback, bypass proxies and refuse redirects. Tests cover the startup control
flow, not an actual llama-server binary or live HTTP server.

Brain `stop` calls `engine.stop()`, which terminates then kills on a bounded
deadline, joins the exit watcher and closes the engine log. Unexpected exit is
reported to Spine even if the code is zero; deliberate stop does not report a
failure. Logs are written directly to a file, avoiding blocked output pipes.
This helper owns one child process; engines that spawn independent descendants
need additional process-tree cleanup. Launches are hidden on Windows.

On Linux the child inherits the parent's cgroup. The actual Spine application
must start inside pecko.scope before launching the engine. No model downloads
or CPU-only build verification are supplied by this helper; those remain engine
owner responsibilities. Offline flags and thread defaults are set in the child
environment, while the judged networking check is still separate.

## Measurement tooling

Try the synthetic report example:

```sh
python -m spine.report spine/examples/events.synthetic.jsonl --manifest spine/examples/experiment.synthetic.json
```

The example deliberately includes a missing turn. Expect two expected turns,
one incomplete turn, a null headline, and a separately named timeout-scored
distribution. None of its numbers are hardware measurements.

For a real experiment, make a manifest with `run_id`, `platform`,
`configuration`, `synthetic: false`, and every expected turn's `turn`, `case_id`,
`t_eos`, `timeout_s`. Choose timeout policy before running, and keep it identical
for paired baseline/Pecko comparisons. Every run uses fresh unique turn IDs;
`case_id` identifies the same recorded request across configurations/repeats.
For WAV input, `t_eos` is the capture/replay start on the monotonic clock plus
the independently annotated acoustic-end offset. Do not substitute the
endpointer's own prediction for the labelled acoustic end.

The harness reads the contract events and these optional `extra` fields:

- Voice `first_audio_out`: `gen`, `content: true`, `sustained: true`. These are
  adapter attestations requiring independent audio-path verification; fillers
  and unverified audio do not enter the headline.
- Voice `pcm_ready`: `gen`, `seq: 0`, for the first clause of the audible generation.
- Brain timeline events: `gen` when multiple generations exist; stale events are excluded.
- Spine `turn_end`: `success` (boolean), `reason` on failure, and complete-turn
  `gap_s` if known. Success should include the acceptable-answer judgement.

Spine emits commit events already. The experiment supervisor must emit turn_end
on completion, failure or timeout; missing turn_end remains an incomplete turn.
Missing/failed turns are retained in the report and score at least their declared
timeout in the explicitly labelled scoring distribution. Those scores are not
observed latency. Headline percentiles are withheld if the run is synthetic,
has incomplete/failed turns or includes undeclared turns. Unknown gaps remain
null; gaps are not inferred from missing events. This parser supports B0 traces
without commit events; C/R decomposition is unavailable where not instrumented.
`device_and_dispatch_s` includes device and dispatch delay, rather than claiming
a pure device-latency measurement. Percentiles use documented linear interpolation.

On Ubuntu, inside the same enforced scope as the engines:

```sh
python -m spine.resources
```

It reports CPU quota/cpuset, whole-cgroup RAM including mmapped pages, swap cap,
CPU PSI total and OOM kills. `usage_delta` converts paired snapshots to CPU-s,
mean cores and a short PSI fraction. Cap changes invalidate the PSI window;
missing/reset counters yield null, not zero. Windows reports unavailable.
Fixtures test the parsing/accounting but do not prove Linux enforcement.

`rapl_delta_j` handles one-wrap counter differences; sample often enough to avoid
multiple wraps and only combine disjoint package domains. RaplMeter discovers
package domains, deduplicates aliases and samples during the 200 ms telemetry
loop. Missing/lost counters and excessive sample gaps invalidate whole-run
energy. Actual hardware validation remains pending. Energy is whole-package,
not cgroup-specific.
`energy_summary` reports gross and idle-adjusted J/turn separately, retaining
negative net values to expose noise. Missing energy stays null. A VM may offer
no energy counters; CPU-s must never be renamed joules.

## Reactive ladder

`spine.ladder.TierLadder` consumes timestamped `PressureSample` objects. Supply
the cap-regime tuple from `Snapshot.regime`, a risk decision from calibrated
PSI/memory/backlog/buffer/tok-s thresholds, and the minimum tier that the cap
can support. This module does not invent those thresholds or assume model
quality from model size. Unknown risk is `None`; it never counts toward recovery.

Defaults follow the spec: downgrade after three consecutive bad readings;
upgrade after ten consecutive good readings and at least two seconds since
the last regime change or switch. A changed regime clears history. A stricter
minimum tier requests an immediate downgrade; recovery cannot cross that floor.
The returned tier is a request, not proof it has been applied. Use `acknowledge`
to synchronize the ladder with an applied/rejected transition.

After checking model availability and measured transition memory, the supervisor
calls `bus.request_tier(tier)`. The bus defers requests while a turn is active;
the latest request replaces earlier pending ones. Only after all audio and work
have stopped does the supervisor call `bus.finish_turn(turn)`. That callback
closes the turn to late events, then changes all three stages' tiers. A temporary
`playback_state:false` is insufficient to permit a switch. Stage reload failures
propagate so the supervisor can stop the entire stack rather than continue
with inconsistent tiers. Reload time and memory must be measured on Ubuntu.

Telemetry samples pressure at 200 ms while the first-audio path continues to
use event-driven dispatch. PressurePolicy initially classifies CPU PSI and
memory ratio; engine-specific backlog/buffer/tok-s thresholds remain future
integration work. It controls only with calibrated:true, explicit supported
tier requirements and measured transition peaks. The transition guard re-reads
the resource cap at the actual safe boundary. A calibrated:false profile only
observes. Advanced action/speculation/chunk control remains measurement-gated.

## Dashboard

Every completed experiment writes a standalone dashboard.html with transcript,
state, tier, turn timing and available resource accounting. It loads no external
assets. Synthetic runs have a prominent warning and withhold headline latency.
Run the external live terminal viewer alongside the application:

```sh
python -m spine.dashboard data/results/mock-control-01/events.jsonl --watch
```

The viewer follows complete JSONL lines, handles partial writes, and strips
terminal control characters from transcripts. Keep this viewer outside the
declared engine cgroup. Sampler cost is currently included inside the application
cgroup and disclosed in resources.json.

## Integration boundaries

Adapters implement `start`, `feed`, `stop`, `set_tier` and publish through
`bus.publish(stage_name, message)`. Feed must enqueue and return promptly;
inference/audio work belongs to stage workers. One owner calls `dispatch_one`.
The queue raises `queue.Full` on overload: the supervisor must stop the pipeline
on overload/dispatch failure, using cleanup in `finally`, never silently drop it.

The transport drops old turns, unregistered/cancelled generations and unheld
chunks before commit. Barge-in closes the interrupted turn; resumed speculative
speech uses cancel, followed by a newer generation within the same turn. New
turn IDs must increase. Generations must increase within each turn. Duplicate
final events are ignored; corrections after final require cancel or a new turn.

Brain calls `bus.prepared(turn, gen, full_prompt_tokens)` before publishing held
chunks. After receiving Ears final, Brain serializes its full final prompt and
calls `bus.validate_final(turn, gen, final_tokens)`. These are internal Python
adapter callbacks queued with the messages, not additions to the wire contract.
Include template, system prompt and conversation history in both token lists.
Spine sends commit only on exact equality after final, or cancel on mismatch.
Brain must rewind/recompute and register a newer generation after mismatch.
An engine's transcript normalization is not a substitute for token validation.

Voice can use `spine.hold.HoldBuffer`: pass finished PCM bytes to `ready`,
and controls to `commit`/`cancel`. Returned blocks are authorized in sequence
order. Commit before PCM-ready works too. The default pending PCM budget is
1 MiB; overflow raises `BufferError` and must stop/cancel the affected work.
This budget is for PCM payload only, not total interpreter/engine memory.
The helper discards older generations and cancelled worker completions.

Real playback integration remains essential: Voice must flush the device/ring
buffer on cancel/barge-in, serialize release/enqueue with cancellation, and
suppress stale worker playback callbacks. v2 playback_state has no generation
field, so Spine cannot disambiguate old feedback within the same turn. Voice
must enforce this locally. Sequence-gap timeouts and complete payload schemas
also remain to be supplied by adapters. Tests do not prove an audio-device stop
deadline. The mock uses synthetic bytes and does not open a speaker.

Sir Jabin confirmed all four roles approved v2.1 in the build chat on 8 Oct 2026.
The mock now exercises the approved hold/release path through the helper.

## Ubuntu launcher

Choose CPU IDs present in `lscpu`; 0,1 is only an example. From the repo root:

```sh
sudo .venv/bin/python -m spine.linux --cpus 0,1
```

Defaults to the short mock. Supply Python arguments after `--` for a future real
entry point. All workers, including llama-server, must be launched INSIDE this
scope. The launcher does not yet supervise llama-server. Verify audio-device
permissions for the launching user when integrating real audio.

While a real loop is running, inspect `systemctl status pecko.scope`, find its
ControlGroup and record `cpu.max`, `cpuset.cpus.effective`, `memory.max`,
`memory.swap.max`, `memory.peak`, and `memory.events` under `/sys/fs/cgroup`.
The short mock scope may disappear before inspection. Enforcement is untested
here; dry-run only checks command construction.

Offline environment flags do not disable networking. Disable external networking
separately, retaining localhost for llama-server. Engine owners must explicitly
disable ONNX spinning and configure its thread pools.

## Build phases and decisions

There are **8 phases, 0 complete**. Report this same count in chat updates;
portable subcomponents do not complete a phase with pending hardware gates.

| Phase | Milestone | Status |
|---|---|---|
| 1 | L0: foundations, local models, verified caps and offline check | In progress; portable foundation built, Ubuntu checks pending |
| 2 | L1: real capped voice loop | Mock wiring, hold/release and engine supervision built; real adapters pending |
| 3 | L2: B0 and C-versus-R experiment | Runner, report and accounting tooling built; real experiment pending |
| 4 | Phone feasibility spike | Pending L1; independent of laptop progress |
| 5 | PC2: core improvements, ladder, dashboard, A0–A4 | Ladder, monitoring and dashboard built; calibration and real engine improvements pending |
| 6 | L4: stable laptop, A5–A7, degradation, feature freeze | Pending |
| 7 | P1: phone integration or component-only evidence | Pending spike |
| 8 | L5: held-out evaluation, documentation, submission | Pending |

Advanced controllers require L2 measurements before implementation; no synthetic
result is a hardware claim. Phase 4 can run alongside laptop work after L1.

Current execution plan: portable development on Windows, Ubuntu VM measurements
later, per Sir Jabin. Label VM results explicitly; virtualization affects timing
and hardware energy counters may be unavailable. CPU-seconds are not joules.
The original submission plan still specifies native Ubuntu.

Next: replace role placeholders one at a time using registered stage factories,
then run deferred Ubuntu acceptance and real baseline measurements.
Turn/generation control, engine supervision, hold/release, reporting, monitoring,
energy accounting, reactive control and dashboard have portable checks;
actual cancellation timing, Linux limits and audio remain unmeasured.
No model selection or performance result is assumed.
