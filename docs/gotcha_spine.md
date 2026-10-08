# Spine development gotchas: mistakes, fixes, and remaining limits

**Updated: 8 October 2026 (Asia/Calcutta).** Operational instructions live in
[handoff_spine.md](handoff_spine.md). This file records what went wrong during
this build and how it was addressed. It does not invent hardware failures:
Ubuntu, real models and physical speaker timing have not been tested here.

Evidence labels used below:

- **Observed failure:** a tool/test actually failed during this session.
- **Review-found defect/gap:** code inspection exposed a problem and we added
  protection/regression coverage; it was not a measured production incident.
- **Workflow mistake:** an approach slowed or confused delivery.
- **Remaining limit:** current behavior to account for; not claimed fixed.

## 1. Delivery was too fragmented and progress reporting obscured useful work

**Workflow mistake.** Early turns built small modules, ended, and repeatedly
reported 0/8 complete. Those eight phases included hardware acceptance, so the
count was honest but made completed portable code look like no progress. Sir
Jabin explicitly asked for larger leaps and to postpone Ubuntu until the end.

**Resolution:** build connected milestones against placeholders. Keep two
separate ledgers: five portable foundation deliverables and three recorded-input
additions are built; the original eight phases still have real-engine/hardware
gates. Add `spine/BUILD_STATUS.md`, an integrated runtime/demo, and review pages.
Do not retroactively rename mock execution into a completed real voice loop.

## 2. The first transport was only routing, without full turn/audio authorization

**Review-found gap.** The initial bus connected Ears/Brain/Voice mocks but did
not yet connect `CommitGate` or filter active turns/generations. The smoke path
had no speaker, but that transport would not be suitable for real audio alone.

**Resolution:** connect `TurnController`, queued prompt-preparation/validation,
generation filtering and `HoldBuffer`. Unregistered/stale/cancelled outputs and
unheld pre-commit chunks are dropped. Add role-scoped contexts and explicit
synthetic adapters. These checks must precede real speaker integration.

**Coverage:** `test_unheld_and_unregistered_output_never_reaches_voice`,
`test_prepare_before_final_is_held_then_committed`,
`test_commit_requires_exact_prompt_and_is_single_use`.

## 3. A cancelled generation could still send a late completion callback

**Review-found defect.** Matching only `(turn, gen)` was insufficient: cancel can
leave the same generation number in state while invalidating it. A late worker
success could then close a resumed turn or allow a tier change.

**Resolution:** completion must match current IDs, require a valid/nonclosed
generation, and require commit for a successful outcome. Old, cancelled and
uncommitted successful callbacks are logged/dropped. Barge-in closes the turn.

**Coverage:** `test_cancelled_generation_cannot_finish_resumed_turn`,
`test_completion_of_older_generation_is_ignored`.

## 4. Background failures and queue overflow needed an owner-thread wakeup

**Review-found gap.** Raising `queue.Full` or an engine error in an isolated
worker does not automatically stop the dispatcher. Without a separate failure
signal, the owner could keep waiting and eventually mislabel it as a timeout.

**Resolution:** add `bus.fail(stage, reason)`, a protected failure flag and a
wakeup event. The flag still works when the ordinary queue is full. Queue
overload marks the bus failed; adapters must catch worker errors and call fail.

**Coverage:** `test_worker_error_aborts_runner_without_waiting_for_timeout`,
`test_full_queue_still_propagates_worker_failure`, `test_overload_is_visible`.

## 5. Playback stopped did not necessarily mean the whole turn finished

**Review-found design trap.** An empty ring buffer can produce
`playback_state:false` during a gap between chunks. Treating it as permission to
reload models could switch tiers in the middle of an answer.

**Resolution:** require explicit `finish_turn`/generation-specific completion
after all work and actual audio have stopped. The bus defers the latest tier
request until that boundary. Stale finish callbacks do not affect an active turn.

**Coverage:** `test_tier_request_waits_for_explicit_safe_boundary`.

## 6. Stale resource samples could authorize a transition after the cap changed

**Review-found defect.** A transition that fit the cap when requested might not
fit when finally applied. Missing memory readings also must not become zero
current usage and appear safe.

**Resolution:** the installed transition guard re-reads the cgroup at the actual
safe boundary, checks target CPU/memory requirements and measured transition
peak plus guard, and denies unknown current/maximum memory or missing profiles.
Rejected transitions are logged and acknowledged to hysteresis state.

**Coverage:** `test_transition_guard_uses_current_cap_and_unknown_memory_is_denied`,
`test_safe_boundary_rechecks_a_cap_that_changed_after_tier_request`.

**Remaining limit:** low-level `request_tier` without a guard still relies on
the caller's feasibility check. Real profiles are not supplied by synthetic demos.

## 7. A counter reset between endpoints could hide inside a positive total

**Review-found accounting defect.** Comparing only the first/last CPU counters
can look positive even if a counter reset occurred midway and then rose above
the original value. Likewise, a cap could change and return to its original
value, concealing mixed PSI regimes at the endpoints.

**Resolution:** track invalid/reset samples and regime changes across the run
and per-turn windows. CPU totals become unavailable after invalid/reset intervals;
mixed-regime PSI aggregates are invalidated even if final and initial caps match.
Missing counters remain unavailable, not zero.

**Coverage:** `test_transient_counter_reset_cannot_hide_in_turn_or_run_totals`,
`test_cap_change_resets_pressure_window`,
`test_counter_reset_cannot_become_negative_cpu_use`.

## 8. Linux RAPL directory names broke the Windows test fixtures

**Observed failure.** Three monitoring tests failed with Windows
`NotADirectoryError` because fixtures used names such as `intel-rapl:0`; a colon
is not a valid normal Windows directory-name character.

**Resolution:** use portable underscore names in fixture directories. Discovery
uses the domain's `name` file (`package-0`, `core`), not a hardcoded path-name
format. Keep the actual Linux reader unchanged and validate package-only counting.

**Coverage:** package/core exclusion, wrap handling, counter-loss invalidation,
long sample gaps and missing energy in `test_spine_monitoring.py`.

## 9. First-token timelines could accidentally include abandoned generations

**Review-found reporting defect.** Choosing the earliest Brain event for a turn
could select a token from an abandoned branch rather than the audible generation.
This would make the latency waterfall tell the wrong story.

**Resolution:** select generation-matching Brain/PCM events and keep missing or
ambiguous identity visible. Require owners to log gen on generation-specific
events. Commit and PCM readiness are joined to the audible generation.

**Coverage:** `test_stale_generation_does_not_contaminate_brain_timeline`,
`test_labelled_eos_and_matching_generation_determine_critical_path`.

## 10. Runner completion alone was not enough to approve a headline

**Review-found gap.** A run can finish its cases yet encounter shutdown or
telemetry errors. A successful mock can also complete every callback with no
actual audio. Operational completion must not become a claimed voice result.

**Resolution:** report generation withholds headlines for synthetic runs,
missing sustained content audio, failed/incomplete turns, unexpected turns and
run-level abort/cleanup/telemetry errors. Failure timeout scores are separated
from observed latency; missing turns and unknown gap durations remain visible.

**Coverage:** `test_cleanup_failure_withholds_otherwise_complete_headline`,
`test_mock_marker_overrides_real_manifest_claim`,
`test_missing_turn_is_preserved_with_separate_timeout_score`,
`test_fillers_and_unverified_audio_do_not_enter_headline`.

**Remaining limit:** quality/content/sustained flags and labels are supplied by
adapters/scorers. Trace consistency does not independently verify them.

## 11. Readiness could be confused with a pre-existing local server

**Review-found process-ownership gap.** An HTTP 200 at the chosen port can come
from another process. Merely checking health after starting a child is not
sufficient to assume that the response belongs to that child under our cap.

**Resolution:** startup with a health URL rejects an already-ready endpoint,
checks the owned child remains alive, bounds readiness waits and stops the child
on failure. Health requests bypass proxies and reject redirects/remote URLs.

**Coverage:** `test_existing_health_endpoint_is_not_mistaken_for_owned_engine`,
`test_readiness_timeout_stops_owned_process`,
`test_remote_health_checks_are_rejected_before_network_access`.

**Remaining limit:** this is not full listener/model attestation. Use a dedicated
port, inspect ownership and verify the model/template. HTTP tests mock readiness;
an actual llama-server remains untested in this workspace.

## 12. Very short WAV replay could complete before EOS state was assigned

**Review-found race.** Starting the replay thread and only then assigning
`self.eos` could let a very short clip reach the completion callback first.
The final message would then carry missing/incorrect ground-truth time.

**Resolution:** choose capture-start on the caller, assign EOS before spawning
the worker, and pass that same capture-start into `WavReplayer.start`.
Timestamp sample positions against this absolute clock rather than callback time.

**Coverage:** `test_replay_preserves_samples_and_capture_clock_and_is_paced`,
the WAV-runtime integration smoke and `test_wav_runtime_records_fingerprint_and_never_claims_asr_or_audio`.

## 13. Header inspection alone could not detect changed audio content

**Review-found integrity gap.** A WAV can be changed after inspection while
keeping rate, channel count and frame count identical. Header equality would
not guarantee that the paired experiment delivered the same input.

**Resolution:** record container and PCM SHA-256 values; hash delivered PCM
while replaying and verify it before successful end_audio. Reject malformed,
truncated, unsupported-format and out-of-bounds-label input. Bound frame size.

**Coverage:** `test_changed_pcm_is_detected_before_endpoint_completion`,
`test_out_of_bounds_label_and_wrong_format_rejected`.

## 14. Paired score aggregation needed the same matching rules as measured gain

**Review-found comparison gap.** Numeric timeout scores can exist for both rows
even if inputs/conditions are unverified or mismatched. Aggregating those values
would imply comparable requests/configurations without evidence.

**Resolution:** retain the union of case IDs and all per-pair issues, but withhold
aggregate scored gains too when input identity, conditions or timeout policy
do not match. Synthetic evidence never supplies measured aggregate gains.

**Coverage:** `test_unverified_input_identity_withholds_aggregated_score`,
`test_different_inputs_or_caps_withhold_measured_gain`,
`test_failures_and_missing_cases_cannot_be_dropped`.

## 15. Batch execution could continue after a user interruption

**Review-found behavior defect.** `ExperimentRunner` correctly catches
KeyboardInterrupt to save evidence and stop stages, then returns an interrupted
summary. Without a batch-level check, the suite could launch the next run.

**Resolution:** after an interrupted run, stop scheduling and mark every later
declared run unstarted. Preserve schedule/progress/results and return exit 130.
Normal fatal run failures remain visible and may proceed to other planned runs.

**Coverage:** `test_interrupted_batch_does_not_start_later_runs`,
`test_interruption_retains_declared_turns_and_cleans_up`.

## 16. Several documentation patches assumed text that did not match the file

**Observed tool failures.** `apply_patch` rejected edits whose expected context
was absent, including attempts that treated part of a wrapped paragraph as a
complete line. Repeating broad patches cost time; some scripts had already
completed earlier independent edits before a later patch failed.

**Resolution:** reread current content, use smaller/stable context anchors,
separate dependent edits, and inspect the final diff. Do not assume a multi-call
editing script is an all-or-nothing transaction. The verification failures are
not evidence that the requested code ran or that the whole edit succeeded.

## 17. Integration limits that are not fixed defects

Carry these into Ubuntu work; do not count them as already resolved:

| Limit | Required action |
|---|---|
| No real engine/speaker adapters | Supply factories, local assets and role-specific dependencies; keep placeholders synthetic |
| Batch CLI uses `Telemetry(bus, log)` without hardware readers | Real batches must pass the Linux telemetry factory through Python `run_batch` |
| Current sudo wrapper runs payload as root | Verify desktop audio access or implement a supported user-owned scope/privilege-drop launch |
| Cgroup/RAPL parsing is fixture-tested only | Verify counters, permissions, limits and energy methodology on the actual Ubuntu VM |
| Package RAPL assumes less than a full wrap between reads | Validate sampling/range; multiple wraps/resets cannot be inferred from two values |
| Energy is package-wide and VM counters may be absent | Disclose scope/other work; report unavailable energy honestly |
| Fixed engine log paths reject repeated launches | Choose a fresh filename per launch; factories have no automatic run-output-dir callback |
| Stage `start/feed/stop/set_tier` can hang in Python | Keep feed nonblocking, bound operations, join workers; arbitrary Python threads are not forcibly killed |
| Single owned child only | Add descendant cleanup if an engine forks independent processes |
| Voice playback_state has no gen | Suppress stale same-turn callbacks inside Voice |
| Full wire validation and sequence-gap/final-chunk handling are partial | Validate payloads and completeness in adapters before real audio |
| No automatic semantic/WER/cutoff grader | Provide reviewed labels/scoring; pipeline completion alone is insufficient |
| Router/survival branch authorization needs integration | No generation-registration bypass exists; define canonical validation before wiring it |
| Whole-turn timeout also waits for playback/scoring | Choose/freeze realistic bounds; do not confuse them with first-audio latency targets |
| Generated artifacts can contain absolute Windows paths | Regenerate/normalize on Ubuntu; generated mock folders are not in Git |
| WAV hashes do not include separate EOS/scoring annotations | Freeze annotations in the dataset version; the comparer does not independently check label equality |
| Three repeats are not three independent recordings | Do not inflate independent-turn counts or cut-off confidence |

## 18. How to avoid repeating these mistakes

1. Read the implementation and [handoff](handoff_spine.md), not just the plan or
   research code. Match ownership, callback order and CLI limitations first.
2. Keep mock/fixture checks explicit. Use fresh output directories and engine
   logs; preserve failed runs rather than rewriting them into clean results.
3. Treat `(run_id, turn, gen)` as identity. Cancel is invalidation, not merely
   a message; completion must prove the same generation finished.
4. Test/review async boundaries: callbacks after cancel, after replacement,
   after timeout, during cap changes and while cleanup is failing.
5. Keep missing/ambiguous/reset telemetry unavailable. Check time provenance,
   actual audio, dataset identity and real conditions before publishing numbers.
6. Deliver integrated software milestones, then explicitly execute the deferred
   Ubuntu gates. Neither a test count nor a simulated tier switch passes the event gate.

Recorded implementation commits: `5fb26f5` (portable runtime/monitoring/review),
`b30665b` (WAV ingress and repeated paired experiments). The final implementation
test run before this documentation task passed 94 tests; this document does not
claim a newly measured hardware result.
