# Recorded-input and paired-evaluation milestone

Built and verified on Windows. This extends the five portable Spine deliverables;
real engine replacement and Ubuntu acceptance remain deferred.

## WAV smoke test

```sh
python -m spine.wav_demo --output data/results/mock-wav-01
```

This creates a synthetic 0.2-second tone/silence fixture, replays 20 ms PCM frames,
and runs placeholder Brain/Voice. It is not speech. Ears uses supplied reference
text, not recognition; Voice never opens a speaker. The run saves clip identity,
capture timestamps, labelled EOS and a dashboard under `mock-wav-01/run/`.

## Three repeats, six retained runs

```sh
python -m spine.batch --template data/results/mock-wav-01/input-plan.json --baseline-profile data/results/mock-wav-01/runtime.json --candidate-profile data/results/mock-wav-01/runtime.json --output data/results/mock-paired-01
```

Both profiles above are the same placeholders. This validates orchestration;
it does not implement B0 or prove a gain. Supply actual baseline/Pecko engines
later through the trusted factory registry accepted by `run_batch` in Python.
The CLI currently includes only built-in placeholder factories.

Open `mock-paired-01/index.html`: it links all six dashboards. Evidence includes
plans, seeded execution order, per-run logs/manifests, three comparisons, progress
checkpoints and `batch-summary.json`. Case order is shared within each repeat;
profile execution order rotates (as balanced as three repeats allow). Failures
remain visible. Interruption stops later runs and marks them unstarted.
Repeated recordings are not independent speakers/requests for cutoff confidence.

## Real Ears integration

`WavReplayer` accepts mono 16 kHz signed 16-bit PCM WAVs and reads bounded frames.
It waits against absolute capture time, avoiding accumulated sleep drift. Each
`AudioFrame` has PCM, turn, sample-rate, sample offset and the first-sample capture
timestamp. Delivery occurs after the final sample of the frame, as with a mic.

Use the same `feed_audio(frame)` queue for WAV and microphone input. The callback
must enqueue and return promptly; inference runs elsewhere. `end_audio(turn)`
signals clip completion but does not force immediate final in a real recognizer.
The Ears endpointer still owns final. Excessive lateness fails visibly rather
than dropping frames; cancellation suppresses the completion callback.

Annotate `eos_offset_s` independently on every recording and retain sufficient
tail/silence for the real endpointer. Ground-truth EOS is capture-start + offset;
do not replace it with the endpointer prediction. The inspected WAV container
and PCM have SHA-256 identities. Delivered PCM is checked before successful
end_audio; changed/truncated input fails. Reports carry clip hashes for pairing.

The `ears:wav-placeholder` profile accepts cases with `wav`, `reference_text`,
`eos_offset_s`, `case_id` and `timeout_s`. CLI WAV paths resolve relative to the
plan. Reference-driven Ears remains synthetic even for real spoken recordings.

## Planning and comparison independently

```sh
python -m spine.suite --template path/to/plan.json --output data/results/plans-01 --repeats 3 --seed 42 --configurations B0 Pecko
python -m spine.compare path/to/baseline/report.json path/to/candidate/report.json --output data/results/comparison-01.json
```

The input plan's `conditions` declares `llm_id`, `cpu_limit`, `memory_limit`,
`input_set_id` and `warmup`. Keep these identical for baseline/Pecko, including
the same LLM required by the solution. Matching declarations do not themselves
prove OS enforcement or engine identity; verify both on the final host.

Comparisons join unique case IDs and check hashes, platform, conditions and
timeout policy. Missing and failed turns stay in the comparison. Observed gains
and timeout-score differences are separate. Measured aggregates require complete
real-audio evidence and matching inputs/conditions; otherwise they are withheld.
No benefit is manufactured by discarding failures or unmatched cases.
