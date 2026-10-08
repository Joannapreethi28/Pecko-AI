# Spine handoff: implementation, integration, and Ubuntu acceptance

**Updated: 8 October 2026 (Asia/Calcutta). Audience: Ears, Brain, Voice, Mobile and the integrator.**

This is the primary operational handoff for Spine. It describes the code that
actually exists at commits `5fb26f5` and `b30665b`, not the features proposed in
research notes. All commands run from the Pecko repository root unless stated.

## Contents

- [Current status and boundaries](#1-read-this-first)
- [Runnable quickstart](#2-run-what-exists-today)
- [Code and ownership map](#3-code-map-and-ownership)
- [Factories, lifecycle and real-stage registration](#4-stage-factory-and-lifecycle-contract)
- [Turns, generations, commit and playback](#5-turn-generation-and-commit-rules)
- [WAV and dataset contract](#6-wav-input-and-dataset-contract)
- [Experiments, evidence and reports](#7-experiment-suite-evidence-and-report-contract)
- [Engine process ownership](#8-brain-engine-process-ownership)
- [Telemetry, energy and tiers](#9-telemetry-energy-and-tier-integration)
- [Ubuntu procedure](#10-ubuntuvm-procedure-at-the-end)
- [Real measurement checklist](#11-real-measurement-and-final-acceptance-checklist)
- [Remaining limits](#12-remaining-boundaries-to-carry-forward)

## 1. Read this first

- Portable development works on Windows now. Ubuntu VM validation is deferred
  until the end, per Sir Jabin. Label final VM results as VM results.
- Five portable foundation deliverables and three recorded-input additions are
  implemented. **Hardware-inclusive project acceptance remains 0/8.**
- The last implementation verification passed **94 tests**. Three scripted cases
  and a six-run WAV/placeholder batch completed. These are software checks, not
  latency, ASR quality, speech quality, energy, or Linux-enforcement measurements.
- There are **no real ASR, LLM, TTS, wake-word or speaker adapters shipped here**.
  Placeholders let everyone integrate independently; each role supplies its engine.
- Contract v2.1 hold-and-release was approved by all four roles, confirmed by
  Sir Jabin in this build chat. The wire shapes remain in [CONTRACT.md](CONTRACT.md).
- Shared architecture and priorities: [solution.md](solution.md). Each role's
  `SPEC.md` supplies model/engine choices. This handoff does not choose a bake-off winner.
- Advanced action selection, critical-path speculation admission and chunk
  optimization remain gated on the real L2 experiment. The shipped controller
  is the reactive ladder; research math is not production performance evidence.

**Start here:** run section 2, then implement the adapter contract in sections
4–7. Use section 10 for Ubuntu and section 11 for acceptance. Development mistakes
and remaining traps are recorded separately in [gotcha_spine.md](gotcha_spine.md).

## 2. Run what exists today

### Requirements and environment

Portable Spine uses Python **3.10+ and the standard library only**. It was checked
on Windows with Python 3.14.8. Each real engine's extra packages, binary, voice,
weights and licences are its owner's responsibility. Models belong in `models/`;
they are gitignored. Core modules are imported from the repository root.

Optional Windows venv:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Use the venv Python for subsequent commands if dependencies are installed there.
Activation is not required. Run each example with a **new output directory**:
experiments/suites reject existing directories and preserve prior evidence.

### A. Contract scenarios: partials, cancellation, correction, prompt mismatch

```sh
python -m spine.runtime --profile spine/examples/runtime.placeholder.json --plan spine/examples/plan.scripted.json --output data/results/handoff-contract-01
```

Expected: `completed_cases: 3`, `aborted: null`, `synthetic: true`.
Events show private `pcm_ready`, a matching-generation `commit`, then
`placeholder_release`. Cancelled/replaced generations do not release output.
No real `first_audio_out` is generated, so headline latency stays unavailable.

### B. Integrated degradation demonstration

```sh
python -m spine.demo --output data/results/handoff-control-01
```

Expected: three completed synthetic cases and **T0 → T1 → T0**, with switches
after turn completion. CPU/PSI values are deliberately simulated. Energy is
unavailable. This verifies wiring, hysteresis and safe boundaries, not real degradation.

### C. Real-time PCM input with a reference-text stand-in

```sh
python -m spine.wav_demo --output data/results/handoff-wav-01
```

This generates a **synthetic 0.2-second tone/silence file**, not human speech.
It streams 20 ms WAV frames and supplies reference text to placeholder Ears.
Expected: one completed case; no ASR or audible-answer claim.
The actual experiment lives in `handoff-wav-01/run/`.

### D. Two profiles, three repeats, six retained runs

```sh
python -m spine.batch --template data/results/handoff-wav-01/input-plan.json --baseline-profile data/results/handoff-wav-01/runtime.json --candidate-profile data/results/handoff-wav-01/runtime.json --output data/results/handoff-paired-01
```

Expected: `expected_runs: 6`, `runs_recorded: 6`, `aborted_runs: 0`, and
`measured_comparison_ready: false`. Both profiles above are the same placeholders.
**Calling a profile baseline does not implement B0.** Open `index.html` to review
all six runs and three comparison files.

### E. Logs, dashboard and checks

```sh
python -m spine.dashboard data/results/handoff-control-01/events.jsonl --watch
python -m unittest discover -s tests -v
python -m spine.linux --cpus 0,1 --dry-run
```

Run the live viewer in a second terminal; Ctrl+C stops it. Keep the viewer
outside the judged cgroup. Generated `dashboard.html` and suite `index.html`
are standalone files with no external assets. Temporary localhost preview
servers used in development are not required and are not part of the runtime.

## 3. Code map and ownership

| File/module | What to use it for |
|---|---|
| `common/clock.py` | `now()` gives host monotonic seconds; never subtract a process-local epoch |
| `common/log.py` | One shared `EventLog`, thread-safe JSONL writes and explicit capture timestamps |
| `spine/runtime.py` | `StageContext`, trusted factory registry, runtime profiles and `ReplayDriver` |
| `spine/bus.py` | Bounded event queue, routing, startup/cleanup, completion/error callbacks, deferred tier application |
| `spine/turns.py`, `spine/commit.py` | Turn/generation validity and exact full-prompt token comparison |
| `spine/hold.py` | Bounded, ordered private PCM with commit/cancel; no device I/O |
| `spine/placeholders.py`, `spine/wav_placeholder.py` | Explicit stand-ins; never use as real engine/quality evidence |
| `spine/audio.py` | Validated, paced WAV input and immutable `AudioFrame` |
| `spine/process.py` | Own one engine child, readiness timeout, exit notification and cleanup |
| `spine/experiment.py` | One run: declared cases, deadlines, durable evidence, cleanup and reports |
| `spine/suite.py`, `spine/batch.py` | Seeded repeated plans and execution of paired profiles |
| `spine/report.py`, `spine/compare.py` | Generation-aware timelines, failures and fair paired comparisons |
| `spine/resources.py`, `spine/energy.py` | Read-only cgroup counters, accounting and package-only RAPL |
| `spine/ladder.py`, `spine/telemetry.py` | Hysteresis, 200 ms sampling and calibrated transition guards |
| `spine/dashboard.py` | External terminal viewer and generated HTML review pages |
| `spine/linux.py`, `spine/preflight.py` | Ubuntu cap launcher and read-only acceptance checks |

Ears owns capture/VAD/KWS/ASR/endpointing; Brain owns model, tokenizer, prompt
serialization, cache/rewind, response chunks and router; Voice owns normalization,
synthesis, held/device buffers and speaker timing. Spine owns coordination,
limits, experiments and reporting. Mobile reuses interfaces but needs its own
platform/telemetry/engine integration; there is no complete phone implementation.

## 4. Stage factory and lifecycle contract

Register trusted Python factories under `ears:name`, `brain:name`, `voice:name`.
Each receives `(StageContext, config)` and returns an object with:

| Method | Required behavior |
|---|---|
| constructor | Store config/callbacks; do not start threads, load models or emit messages yet |
| `start()` | Load, warm, start workers, then return ready; bound external-engine startup |
| `feed(msg)` | Enqueue work and return promptly; no blocking inference on the dispatcher |
| `stop()` | Cancel and join workers, stop children, flush audio and release resources |
| `set_tier(n)` | Apply the role's tier only at Spine's safe boundary; free/reload coherently |
| Ears `replay(case, turn)` | For `ReplayDriver`: begin asynchronous input and return labelled monotonic EOS |

Spine starts **Voice → Brain → Ears**, then dispatches queued messages on one
owner thread. It stops **Ears → Brain → Voice**, including partially started
stages. One cleanup exception is logged while the other stages still get stopped.
A fresh run gets a fresh bus/stage instances; do not restart the same bus.

`StageContext` binds message/log source to the role:

| Callback | Who calls it | Meaning |
|---|---|---|
| `publish(msg)` | Any stage | Enqueue a supported contract message from this stage |
| `log(event, turn=None, t=..., **extra)` | Any stage | Log an event; use `t` to preserve actual capture/device time |
| `fail(reason)` | Any stage/worker | Wake Spine and abort on fatal error, including background errors |
| `prepared(turn, gen, tokens)` | Brain | Register a generation's complete serialized prompt tokens before its chunks |
| `validate(turn, gen, tokens)` | Brain | Validate the final prompt after receiving Ears final |
| `complete(turn, gen, success=..., reason=..., gap_s=...)` | Voice, coordinated with supervisor/scorer | Acknowledge fully stopped/drained work and a scored outcome |

The internal Python callbacks are not new JSON wire-message types. Worker
exceptions must call `fail`; exceptions in isolated threads otherwise do not
automatically reach the owner. Queue capacity defaults to **256 messages**;
overload raises `queue.Full` and marks a fatal bus failure. Do not swallow it
and continue. Payload sizes/context/buffer budgets also remain adapter responsibilities.

### Registering real stages

The shipped runtime/batch CLIs contain **only built-in placeholder factories**.
Putting an adapter file in a role folder does not automatically register it.
Write a trusted application entry point, for example `spine/team_run.py`, and
merge the owners' factories into a registry passed to `make_factory`/`run_batch`.

The following is an **integration skeleton**: the three `team_adapter` modules,
real profile and dataset paths are for the team to supply; they are not shipped.

```python
import json
from pathlib import Path
from ears.team_adapter import create_stage as create_ears
from brain.team_adapter import create_stage as create_brain
from voice.team_adapter import create_stage as create_voice
from spine.runtime import BUILTIN_FACTORIES, make_factory, ReplayDriver
from spine.experiment import ExperimentRunner

registry = dict(BUILTIN_FACTORIES)
registry.update({
    "ears:team": create_ears,
    "brain:team": create_brain,
    "voice:team": create_voice,
})
profile = json.loads(Path("data/runtime-team.json").read_text())
plan = json.loads(Path("data/heldout.json").read_text())
# Python APIs do not resolve case WAV paths relative to the plan for you.
for case in plan["cases"]:
    if "wav" in case:
        case["wav"] = str((Path("data") / case["wav"]).resolve())
runner = ExperimentRunner(
    plan, Path("data/results/team-run-01"),
    make_factory(profile, registry), ReplayDriver(),
    telemetry_factory=make_linux_telemetry,  # define as shown in section 9
)
runner.run()
```

The profile is data, not an import mechanism. Example stage entries:

```json
{
  "synthetic": true,
  "stages": {
    "ears": {"adapter": "team", "config": {}},
    "brain": {"adapter": "team", "config": {}},
    "voice": {"adapter": "team", "config": {}}
  }
}
```

Replace one role at a time. Keep `synthetic:true` while any stand-in, synthetic
input or reference-driven recognition remains. Set it false only for actual
engine/input runs; the flag alone does not prove quality or hardware correctness.
Stage-specific config fields are defined by the factory owner, not by Spine.

## 5. Turn, generation and commit rules

Read the authoritative message shapes in [CONTRACT.md](CONTRACT.md). All
timestamps are host `time.monotonic()` seconds. Turn IDs are unique/increasing
**within a run**; each fresh run can start at 0. Case IDs identify matching
recordings across runs. Generation IDs increase within a turn; chunks carry
nonnegative `gen` and ordered `seq` starting at 0.

Current routes:

| Source | Type | Destination |
|---|---|---|
| Ears | `partial`, `tentative_final`, `final` | Brain |
| Ears | `cancel`, `barge_in` | Brain and Voice |
| Ears | `intent_hint` | Voice for private preload |
| Brain | `chunk`, `cached` | Voice |
| Voice | `playback_state` | Ears; Spine inspects it |
| Voice | `cancel` | Spine invalidates and notifies Brain/Voice |
| Spine | internal-generated `commit`/`cancel` | Voice then Brain |

Spine filters old turns, unregistered/invalid generations, duplicate finals and
unheld Brain output before commit. It does not validate every message payload
field; adapters still validate text, chunk shape, cache identity and size limits.
Ears cancel invalidates speculative state but allows resumed speech in that turn.
Barge-in closes the interrupted turn; later speech needs a newer turn ID.
Corrections after final require cancel or a new turn, not a second silent final.

### Brain's required sequence

1. Serialize the **entire** model prompt: template, system message, history,
   user input and model control tokens. Use the real tokenizer's IDs.
2. Call `context.prepared(turn, gen, full_prompt_tokens)` before publishing
   any output from that generation. Callback and message ordering share one queue.
3. Before commit, all generated chunks must have `held:true`; Voice prepares privately.
4. On Ears final, reconstruct the full final prompt and call
   `context.validate(turn, gen, final_prompt_tokens)`.
5. Spine compares exact token sequences and requires final first. Equal sequences
   produce one commit; mismatch produces cancel. Normalized transcript equality
   or confidence alone is not sufficient.
6. On mismatch/cancellation, discard stale workers/KV state, rewind/recompute
   as supported by the chosen model, register a **newer** generation and validate again.

Post-final serial adapters must also register and validate their generation.
Cached output has no automatic registration/commit bypass: publish it only after
the generation is authorized, or privately preload via `intent_hint`. Finalize
canonical validation for router-only/no-LLM survival profiles before connecting them.
Spine cannot perform model KV rewind; Brain implements and tests it.

### Voice's held-buffer and device obligations

`HoldBuffer(max_bytes=1_048_576)` is optional reusable plumbing:

```python
blocks = hold.ready(turn, gen, seq, pcm_bytes)
blocks = hold.commit(turn, gen)
hold.cancel(turn, gen)
```

Returned blocks are authorized in sequence order. Commit can arrive before PCM
or after PCM; duplicate/old sequences and cancelled generations do not release.
The default limit is **1 MiB of pending PCM payload**, not total Python/engine
memory. Overflow raises `BufferError`; stop/cancel visibly. Missing sequence
timeouts, final-chunk completeness and output sample format are Voice responsibilities.

The helper does **not** open a speaker, manage a ring buffer, flush device audio,
or guarantee a barge-in deadline. Serialize authorized-block enqueue with cancel;
flush queued/device playback and suppress late synthesis callbacks. The wire
`playback_state` has no gen field, so Voice must suppress stale same-turn feedback.
Log true first sustained content audio at the audio path/DAC clock, not when
text arrives, commit happens, synthesis ends or bytes enter the device queue.

### Completion is stronger than playback_state:false

A temporary empty buffer can produce `playing:false` mid-answer. It is not a
safe model-reload boundary. Confirm input/replay workers, inference, TTS and
actual speaker playback are finished before `complete`/`bus.finish_turn(turn)`.
Completion carries gen; stale/cancelled/uncommitted successful callbacks are ignored.
`finish_turn` closes the turn without a scored outcome; the experiment runner
needs `complete_turn` to finish a case and record `turn_end`.

No automatic acceptable-answer grader exists. For evaluation, integrate scoring
with the supervisor; do not confuse operational completion with answer quality.
If human grading is offline, retain the original log and make a separately
reviewed/scored copy before publishing quality-inclusive results.

## 6. WAV input and dataset contract

`AudioFrame` contains `turn`, `pcm`, `sample_rate`, `offset_frames`, `t_capture`.
Input must be **mono 16 kHz signed 16-bit PCM, uncompressed WAV**. Default frame
size is 20 ms/320 samples. Delivery follows absolute replay time; the timestamp
marks the first sample, while callback delivery follows the frame's last sample.
Read one bounded frame at a time; `feed_audio` must enqueue promptly.

Use the same input queue for recorded WAV and microphone PCM. WAV `end_audio`
signals clip completion, not automatic endpoint approval. Keep enough recorded
tail/silence for the real endpointer. Default maximum replay lateness is 250 ms;
exceeding it fails visibly rather than dropping samples. Cancellation stops/join
the worker and suppresses successful completion.

`inspect_wav` validates format/EOS bounds and records file/PCM SHA-256 values.
Streaming checks the delivered PCM identity before successful completion.
Ground-truth EOS is **capture start + independently annotated eos_offset_s**;
never substitute the recognizer's predicted endpoint or process-local time.

Example `data/heldout.json` case:

```json
{
  "case_id": "speaker-a-turn-001",
  "wav": "clips/speaker-a-turn-001.wav",
  "eos_offset_s": 1.28,
  "timeout_s": 20,
  "reference_text": "What is the capital of France?",
  "acceptable_answer": "Paris"
}
```

Values above illustrate schema, not an existing recording or measured deadline.
CLI WAV paths resolve relative to the plan file; raw Python APIs require the
caller to normalize them. Reference/answer labels are for grading only: a real
ASR/Brain must not receive the answer as its input prediction. `wav-placeholder`
does intentionally use reference text and is therefore always synthetic.

## 7. Experiment, suite, evidence and report contract

Required plan fields: `run_id`, `platform`, `configuration`, boolean `synthetic`,
and a nonempty `cases` list. Each case has unique `case_id` and positive
`timeout_s`. Repeats use separate runs, not duplicated case IDs in one run.

For paired comparisons, also declare:

```json
{
  "conditions": {
    "llm_id": "replace-with-exact-model-hash-and-quantization",
    "cpu_limit": 2,
    "memory_limit": 2147483648,
    "input_set_id": "replace-with-frozen-dataset-id-or-hash",
    "warmup": true
  }
}
```

Conditions must describe the actual setup. Equal declarations are not proof of
actual cap enforcement or model identity. Baseline and Pecko use the **same LLM**.
Record full model/runtime/voice versions and configuration alongside the artifacts.
Freeze EOS annotations and scoring labels as part of the dataset version too.
The current paired comparer checks recording hashes and declared conditions;
it does not independently compare annotation offsets or prove that a runtime
really loaded the declared model. Identical WAV hashes alone do not prove
identical ground-truth labels. The shared batch template preserves the same
case data for both profiles, but independently prepared runs need this check.

The runner warms stages before measured cases and waits on events. Its deadline
is labelled EOS + `timeout_s` for **whole-turn completion**, not merely first
audio. Choose enough time for the full reply/drain/scoring, freeze the policy
before evaluation and keep it identical across paired profiles. First-audio
latency is a separate reported quantity, not the whole-turn timeout.

Normal scored failures can continue after confirmed stop. Timeout/fatal error
aborts that run and marks remaining cases unstarted. Every declared turn remains
in the manifest; unstarted turns use `t_eos:null`, `not_started:true`. Batch
execution retains run failures; interruption marks later runs unstarted.

| Artifact | Contents/use |
|---|---|
| `plan.json` | Declared inputs, timeouts, conditions; preserve before running |
| `events.jsonl` | One event object per line; flushed, capture-time capable |
| `manifest.json` | Every expected turn and its labelled EOS; checkpointed |
| `runner_summary.json` | Operational completion/failure/unstarted status |
| `report.json` | First audio, C/R, gaps, issues and separate timeout scoring |
| `resources.json` | Only with attached telemetry: per-turn and whole-run accounting |
| `dashboard.html` | Static run review; no external resources |
| Suite `plans/`, `batch-progress.json`, `batch-summary.json` | All declared runs, seeded schedule and outcomes |
| `comparison-repeat-N.json`, suite `index.html` | Strict per-repeat comparison and review links |

All generated `data/results/mock-*` artifacts are **synthetic and untracked**;
they are not guaranteed to exist in teammates' clones. Regenerate smoke runs.
Saved plans can contain absolute Windows WAV paths; normalize/rebuild them on Ubuntu.

### Log fields that make reporting work

One shared logger writes `stage`, `event`, `turn`, `t`, `extra`. Its lock protects
threads sharing that instance, not independent processes writing the same file.
Separate process logs or use one aggregator if stages are split later.

| Owner/event | Required reporting detail |
|---|---|
| Ears `t_eos`, `endpoint`, `asr_final` | Actual capture/confirmation timestamps; labelled EOS is independent in the manifest |
| Ears `input_clip` | `extra.sha256` for paired input identity; include format and label metadata |
| Brain `prompt_ready`, `first_token`, `first_chunk`, `cache_hit` | Include `extra.gen` on generation-specific events |
| Voice `chunk_recv`, `synth_start`, `synth_end` | Include gen/seq to distinguish stale work |
| Voice `pcm_ready` | `extra.gen`, `extra.seq:0` for the first clause of the audible generation |
| Voice `first_audio_out` | `extra.gen`, `content:true`, `sustained:true`; actual audio-path timestamp |
| Voice `underrun`, `barge_in_stop` | Log actual event/delay; accumulate complete-turn gap duration |
| Spine `commit` | Emitted by Spine; timestamp is C |
| Spine `turn_end` | Emitted by queued completion; success, failure reason, known complete-turn `gap_s` |
| Spine `pressure`, `tier_switch`, `tier_rejected` | Resource snapshots/deltas and actual transition outcome |

For cached clips, log first-clause PCM as seq 0 with the authorized gen too.
Unknown gaps stay null; do not claim zero gaps because logging is absent.
WER, explicit cut-off rates, answer scores and cache false-hit rates are not
automatically computed by the current reporter; the team must collect/grade them.

Headline = labelled speech end → first sustained audio of the **real answer**.
C is final-prompt commit; R is first-clause PCM ready; `max(C,R)` identifies the
last dependency. `device_and_dispatch_s` includes dispatch and device delay;
it is not a pure device-delay measurement. Percentiles use linear interpolation
at `(n-1)*q`. Synthetic, incomplete/failed, undeclared-turn, cleanup-error or
telemetry-error runs withhold headline percentiles. Failed/missing turns remain
visible and receive at least their declared timeout in a **separate scoring
distribution**, never a fabricated observed latency.

Compare matching case IDs, hashes, platforms, conditions and timeout policies.
Positive gain favors the candidate. Mean/median paired gains differ from
baseline-p90 minus candidate-p90. The comparer preserves every missing/failed
pair and withholds aggregate gains when prerequisites fail.

```sh
python -m spine.suite --template data/heldout.json --output data/results/heldout-plans-01 --repeats 3 --seed 42 --configurations B0 Pecko
python -m spine.report path/to/events.jsonl --manifest path/to/manifest.json --output path/to/new-report.json
python -m spine.compare path/to/baseline/report.json path/to/candidate/report.json --output path/to/new-comparison.json
```

**Important CLI distinction:** `spine.runtime` discovers cgroup/RAPL support;
`spine.experiment --telemetry` can also attach them, but its CLI driver is a text
mock. **The current `spine.batch` CLI attaches an empty telemetry collector, not
hardware readers.** For real batch CPU/RAM/energy, use `run_batch` with a supplied
Linux telemetry factory as below. None of these CLIs auto-import real adapters.

## 8. Brain engine process ownership

Use `EngineProcess(argv, log_path, on_failure, cwd=..., env=...)` for a CPU-only
local llama-server child. Pass arguments as a list; no shell is involved.
The owner-supplied server arguments must bind to literal loopback, not an external
interface, and the actual build/offload settings must be verified CPU-only.
Choose a fresh log filename for every launch/repeat, for example one using
`time.monotonic_ns()`. A fixed log path will fail on the second launch because
logs are opened exclusively. Factories are not automatically given a run output
directory; arrange unique log paths in the owner application/config.

```python
engine = EngineProcess(
    owner_supplied_argv,
    fresh_engine_log_path,
    lambda reason: context.fail(reason),
)
engine.start(health_url="http://127.0.0.1:8080/health", readiness_timeout_s=30)
# Owner then verifies model/template and performs its own warm-up.
```

Only literal HTTP loopback health URLs are allowed; proxies and redirects are
disabled. Startup rejects an already-ready endpoint. Still use a dedicated port
and verify ownership/model identity: HTTP 200 alone is not model/warm-up proof.
Unexpected exit, even code 0, calls the failure handler. Stop uses terminate,
then kill on a bounded wait, joins the watcher and closes the log.

This owns one child, not an arbitrary descendant tree. A stuck Python stage
method cannot be forcibly killed by the runner. Bound engine operations and
join workers. The child inherits the parent's Linux cgroup; **start it inside
the cap**, never reuse an independently launched server outside it. Offline
cache flags and thread defaults are set, but do not disable the network or
verify a CPU-only build. ONNX owners must configure intra/inter threads and
disable spinning explicitly as specified by the shared plan.

## 9. Telemetry, energy and tier integration

The 200 ms sampler is separate from event-driven first-audio dispatch. It reads
whole-cgroup CPU, memory, PSI and OOM counters. Missing values stay unavailable.
CPU delta yields CPU-seconds and mean cores. PSI uses a short counter delta,
not avg10; cap changes reset/invalidate history. Counter resets cannot become
negative CPU or quietly restore valid run/turn totals.

RAM is cgroup `memory.peak`, including mmapped pages and warm-up, for the cgroup
lifetime. CPU/energy sampling starts after stage warm-up and ends before shutdown;
record that window. Sampler and in-process harness costs are included in the
application/cgroup. The external terminal/dashboard viewer is outside it.

RAPL discovers **package domains only**, deduplicates aliases and avoids adding
core subdomains to package totals. Counter differences assume less than one
full wrap between reads. Missing/lost counters or excessive sample gaps invalidate
whole-run energy. The default gap guard is 2 s, not a mathematical guarantee that
all hardware wrap rates are safe. Validate the counter range and sampling rate.
Energy covers whole CPU packages, including other work, not the cgroup alone.
A VM may not expose RAPL at all; use an honest unavailable value or separately
disclosed physical-meter methodology. **CPU-seconds are never joules.**

The runner reports gross package energy per started turn when available.
Idle-adjusted energy is not measured automatically: measure an appropriate
idle-power baseline and call `energy_summary(..., idle_watts=measured_idle_watts)`.
Keep gross and net values separate; negative net energy remains visible as noise.

Define this in the real application, which will run **inside pecko.scope**:

```python
from spine.resources import own_cgroup, read_snapshot
from spine.energy import RaplMeter
from spine.telemetry import Telemetry

def make_linux_telemetry(bus, log):
    cgroup = own_cgroup()
    return Telemetry(
        bus, log,
        read_snapshot=lambda: read_snapshot(cgroup),
        energy=RaplMeter(),
        policy=None,  # attach PressurePolicy only after profiling
        interval_s=0.2,
    )
```

For paired execution, use:

```python
from spine.batch import run_batch
run_batch(
    template, baseline_profile, pecko_profile,
    Path("data/results/real-paired-01"),
    repeats=3, seed=42, registry=registry,
    telemetry_factory=make_linux_telemetry,
)
```

The reactive ladder defaults to 3 consecutive bad readings to downgrade and
10 consecutive healthy readings + 2 s dwell to recover. Unknown readings do
not count healthy; cap-regime changes clear history. Current `PressurePolicy`
uses CPU PSI and memory ratio. Backlog, playable buffer and tok/s risk integration
remain to be supplied with actual engines/profiles.

A policy file needs `calibrated`, `psi_fraction`, `memory_ratio`, `tiers` rows
(`tier`, `min_cpu`, `min_memory_bytes`), `memory_guard_bytes`, and
`transition_peak_bytes` keyed by strings like `0->1`. All numbers must come
from profiles before a real `calibrated:true` claim; demo numbers are fictional.
`calibrated:false` observes only. Every desired transition must have a profile.

`Telemetry.start()` installs a transition guard that re-reads current limits
at the actual safe boundary and checks target feasibility and transition peak
plus guard. Low-level `bus.request_tier` without an installed guard assumes the
caller has checked feasibility; it is not automatic resource safety.
The latest request waits until explicit completion. Stage switch order is
Brain → Voice → Ears; any failure propagates and stops the stack, not rollback.

## 10. Ubuntu/VM procedure at the end

Commands below are implementation-based handoff instructions, **not commands
already verified on this Windows host**. Declare guest OS/vCPU/RAM, host details,
runtime versions and whether hardware energy is exposed. VM timing and power
cannot be presented as native-laptop measurements.

### Prepare offline assets and verify the portable software first

```sh
python3 -m venv .venv
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m spine.runtime --profile spine/examples/runtime.placeholder.json --plan spine/examples/plan.scripted.json --output data/results/ubuntu-contract-01
```

Install only the role owners' required engine packages/binaries, prepare local
models/voices, and record hashes/licenses before disabling external networking.
Replace all placeholders via the trusted team application. Do not invent
llama-server flags or package versions: use the owner's verified CPU build.

### Choose actual logical CPUs and launch inside the declared scope

```sh
lscpu
.venv/bin/python -m spine.linux --cpus 0,1 --quota 200 --memory 2G --dry-run
sudo .venv/bin/python -m spine.linux --cpus 0,1 --quota 200 --memory 2G -- -m spine.runtime --profile spine/examples/runtime.placeholder.json --plan spine/examples/plan.scripted.json --output data/results/ubuntu-capped-contract-01
```

`0,1` are examples; choose IDs present on the guest. `CPUQuota=200%` is two
aggregate CPU equivalents; `AllowedCPUs` also limits affinity. `2G` here is
2 GiB/2,147,483,648 bytes; declare units correctly. Swap is capped at zero.
The helper's effective CPU calculation uses local quota and effective cpuset;
it does not prove absence of stricter ancestors or host VM contention.

For the real application, replace only the payload after `--`, for example
`-m spine.team_run` **after the team has written that entry point**. The same
scope must contain the orchestrator, Ears/Voice workers and owned llama-server.
Do not start/reuse a model server outside it.

**Privilege/audio check:** the current sudo launcher runs the payload as root;
it does not drop to the desktop audio user. Root may not access the user's
PulseAudio/PipeWire session or user-owned assets as expected. Validate real
mic/speaker access and choose a supported user-owned scope or privilege-drop
arrangement on Ubuntu before treating this as a ready judged launch.

### Inspect the live scope, not a guessed/global cgroup

While a longer real loop is running, in a second terminal:

```sh
systemctl status pecko.scope
unit_cgroup=$(systemctl show --property=ControlGroup --value pecko.scope)
if [ -z "$unit_cgroup" ]; then
  echo "pecko.scope is not running"
  exit 1
fi
cgroup_dir="/sys/fs/cgroup${unit_cgroup}"
cat "$cgroup_dir/cpu.max"
cat "$cgroup_dir/cpuset.cpus.effective"
cat "$cgroup_dir/memory.max"
cat "$cgroup_dir/memory.swap.max"
cat "$cgroup_dir/memory.peak"
cat "$cgroup_dir/memory.events"
```

The short mock scope can disappear before inspection. Do not accidentally read
the root cgroup and attribute it to Pecko. Preserve runtime snapshots before
scope teardown and verify OOM kills remain zero. For explicit preflight inside
a fresh capped scope:

```sh
sudo .venv/bin/python -m spine.linux --cpus 0,1 -- -m spine.preflight --model /absolute/path/model.gguf --model /absolute/path/asr.onnx --model /absolute/path/voice.onnx
```

Those model paths are examples to replace. `--expected-cpus` and `--memory-gib`
on preflight must match a nondefault cap. Preflight checks presence/nonempty
files, Python/Linux and cgroup fields. It does not verify licences, correct
models, engine compatibility or offline/audio correctness; `judged_loop_ready`
intentionally remains false. An uncapped/outside-Linux failure is expected.
If the team instead launches under a user systemd manager, inspect that manager
with `systemctl --user`; the system-manager commands above match the shipped sudo path.

### Offline and audio acceptance

1. From the local VM console, disable external networking/airplane-mode it as
   appropriate. `sudo nmcli networking off` is one NetworkManager option; it
   can disconnect network access, so use the local console for this step.
2. Confirm localhost still works with the owned llama-server health endpoint;
   both offline cache flags and the actual network-off check are required.
3. Verify CPU-only builds, warm engines, real wake/PTT handling and no fillers.
4. Check microphone → real answer → speaker through the actual audio path.
5. Cross-check sustained-answer timing and barge-in with an independent recording.
6. Keep dashboard/TUI outside the cap; disclose sampler/harness placement inside it.

### Degradation without an avoidable OOM

Announce the target cap between turns. Request the lower tier, finish the turn,
wait for reload and verify memory fits the **target** limit plus guard, then
lower the OS cap. Do not reduce RAM below current residency and expect a
reactive loop to beat an immediate OOM. After verification, an example T2 cap is:

```sh
sudo systemctl set-property --runtime pecko.scope AllowedCPUs=0 CPUQuota=100% MemoryMax=1250M
```

Replace CPU ID/cap with the agreed actual values. Capture switch latency, peak
memory, pressure history and OOM status. Reset regime history after the change.
The synthetic T0→T1→T0 demo is not this hardware acceptance test.

## 11. Real measurement and final acceptance checklist

1. Freeze a real B0: default silence handling → whole-utterance baseline ASR →
   the **same LLM** as Pecko without prompt-cache/streaming advantages → full
   reply TTS. The stage owners must implement those settings; labels do not.
   Add tuned B1/static B2/reactive B3 comparisons according to the shared plan.
2. Build the 30 calibration + 60 held-out recordings with independent EOS,
   reference transcripts and acceptable-answer labels. Keep labels out of inference.
3. Run the warm ordinary/hesitation/correction experiment at 1 and 2 CPUs.
   Inspect C, R, endpoint/final-ASR/prefill/first-token/first-chunk/PCM/audio traces.
4. Profile tier quality and whole-cgroup transition memory before real control.
5. Run paired held-out configurations three times in seeded/counterbalanced
   order with identical clips, LLM, caps, warm-up and timeout policy.
6. Report failures, cut-offs, gaps, answer quality, WER, p50/p90, CPU-s, RAM,
   available gross/net energy and model precision comparisons. Never drop failures.
7. Inspect `report.run_issues`, telemetry errors and live workers as well as
   runner completion counts. Cleanup failure can withhold the headline even when
   `completed_cases` is high and the suite's `aborted_runs` is zero.
8. Use real measured evidence to decide whether advanced speculation/chunk
   control pays. Keep the required ladder regardless; never ship audited incoming
   research code as-is. Phone work must not block the laptop/VM acceptance path.
9. Update results/README, preserve commits and reproducible artifacts, rehearse,
   record backup videos and complete submission per the team plan.

For cut-off statistics, three repeats of 60 recordings are not 180 independent
turns. The shared plan notes that zero observed cut-offs in 60 independent turns
still permits approximately 4.87% at 95% confidence; do not publish it as zero risk.

## 12. Remaining boundaries to carry forward

- Real stage factories, weights, mic/speaker integration, model rewind and caches
  remain role work. Placeholder success is not voice quality or low latency.
- Decode-batch/TTS deadline scheduling and a causal chunk planner are not yet
  implemented. Event routing alone does not guarantee playback continuity or
  safe shared-core concurrency; profile and bound the actual workers.
- The commit bus is stricter than plain routing: real/cached/serial output still
  needs generation registration and final authorization.
- Full wire payload schemas, sequence-gap handling, semantic scoring, WER,
  cut-off grading and cache false-hit analysis remain integration/evaluation work.
- Barge-in's physical stop deadline, engine model identity, root audio access,
  cgroup delegation, RAPL permissions and actual enforcement need Ubuntu checks.
- Child descendants and arbitrary stuck Python methods are not forcibly managed.
- CLI batch hardware telemetry needs the explicit Python factory shown above.
- Absolute WAV/model paths and fresh engine log paths need attention across hosts/repeats.
- Compare readiness reflects trace/declaration consistency, not independent proof
  that audio labels, quality flags, model identity and cap claims are correct.
- Freeze/check annotation and scoring metadata explicitly; the comparer does
  not independently validate EOS-offset equality across separately created runs.

Supporting references: [Spine README](../spine/README.md),
[delivery status](../spine/BUILD_STATUS.md),
[recorded-input guide](../spine/RECORDED_INPUT.md),
[solution](solution.md), [contract](CONTRACT.md), [gotchas](gotcha_spine.md).
