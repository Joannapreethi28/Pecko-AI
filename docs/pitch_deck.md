> **v2 note:** product renamed **Pecko**. Update the thesis slide to the critical-path picture (`first audio = max(C,R)+d`, solution.md §1) and add one **"Pecko on a phone"** slide (solution.md §4): same contract on Ubuntu → Android, real throttling drives the ladder. Fill only measured numbers.

# PITCH DECK PLAN: "Pecko", a voice assistant that thinks while you talk, on 2 CPU cores
HackNEX 2026 · HNX26EPS08 · Team Plumbers · content plan v1 (8 Oct 2026)
Companion to `solution.md`. This file is the story, the slides, what to say, the demo script and the Q&A bank. Slides get built from this later.

> **Number rule.** Every `[MEASURE]` is filled from our own runs before it goes on a slide. If a number is not measured, the slide says "target" or the number comes off. A judge who catches one fake number stops believing the rest.

---

## 0. Three decks from one story

| Deck | When | Mode | Length |
|---|---|---|---|
| **PC1 deck** | Progress Check 1, 5:30 PM today | Live, presenter-driven | 5 slides, ~3–4 min (confirm the slot length with organisers) |
| **Submitted deck** | With the repo, 6:30–8:00 AM | **Read alone** by judges choosing the top 15 | 10–12 slides, denser, every number visible on the slide |
| **Finale deck** | 8:15 AM, top 15 | Live, presenter-driven, ≤ 3 points per slide | ~11 slides + live demo, 20 min total |

PC2 (12:00 AM) reuses the PC1 deck plus one "progress" slide (§3).

Do **not** submit the finale deck as the written deck: sparse live slides look empty when read alone. Do **not** read the dense deck aloud in the finale.

---

## 1. The spine of the story

**Insight (say it in every version):**
> *"On a 2-core budget, the models aren't slow. The waiting is. A normal voice assistant waits for silence, then transcribes, then reads the whole prompt, then writes the whole reply, then speaks. Each stage sits idle while the previous one finishes. Pecko does all of it at once, and starts thinking before you've finished talking."*

**The arc in seven sentences:**
1. **Hook:** Pecko is an offline voice assistant that answers in under a second on 2 CPU cores and 2 GB of RAM. *(true for the median only: p50 0.84 s, p90 1.28 s on 24 synthetic turns in a VM; say "typically under a second")*
2. **Problem:** Offline voice assistants on cheap hardware take several seconds to reply, which feels broken; a standard stack with the same LLM takes 2.06 s p50 / 2.50 s p90 after you stop talking (VirtualBox VM, 2 CPU / 2 GB cgroup, swap 0, 24 synthetic Piper-voice questions, no speaker = 0 ms device latency).
3. **Insight:** That time is spent waiting between stages, not computing inside them.
4. **Solution:** Pecko overlaps the stages: smart endpointing, streaming speech recognition, a language model that pre-reads your words while you speak, and speech that starts at the first clause.
5. **Proof:** Under an enforced 2-core / 2 GB limit: first audio p50 835 ms vs 2059 ms (p90 1280 vs 2496 ms; paired gap p50 1199 ms, p90 1472 ms, min 837 ms; faster in 24/24 pairs), at 1.63× less CPU time per turn (1.20 vs 1.96 CPU-s) and about the same peak RAM (846 vs 917 MiB; identical runs vary ±90 MiB, so not a win). Energy per turn: not yet measured (needs native Ubuntu RAPL). (VirtualBox VM, 2 CPU / 2 GB cgroup, swap 0, 24 synthetic Piper-voice questions, no speaker = 0 ms device latency) Source: `data/results/run-syn24-pecko-ram/compare_vs_baseline-syn24-b0.txt`.
6. **Why it's new:** Speculative voice agents exist on GPUs; Pecko prices every early guess against the CPU and energy it steals on a tiny shared budget, and keeps working as the budget shrinks.
7. **Impact + ask:** The same design runs voice assistants on ₹5,000-class hardware with no internet (rural clinics, kiosks, classrooms, assistive devices), and we'd like your vote to take it to a Raspberry Pi and Indian languages next.

**Name the product, not the pipeline.** Say "Pecko" every time, never "our ASR-LLM-TTS stack."

---

## 2. PC1 deck (5:30 PM, ~3–4 min): idea + approach

Goal: judges remember the insight and believe we can build it. Show something running.

| # | On the slide | Say (speaker notes) |
|---|---|---|
| 1 | **Pecko** · *A voice assistant that thinks while you talk* · 2 CPU cores · 2 GB · offline | "We picked PS08. Our goal: an offline voice assistant that replies in under a second inside a 2-core, 2 GB box, and proves every millisecond." |
| 2 | Waterfall sketch: default stack = 5 blocks in a row, **≈ 3–8 s** (label "estimate, measuring today") | "Here's a standard offline assistant. Every block waits for the one before it. Most of these seconds are waiting, not computing." |
| 3 | **"The models aren't slow. The waiting is."** + overlapped diagram (stages stacked in parallel) | "So we overlap the stages. Pecko detects that you've finished in about 150 ms, not 800. It transcribes while you talk. The language model pre-reads your words before you stop. Speech starts at the first comma." |
| 4 | Three proofs we'll bring: **latency waterfall · CPU/RAM/energy per turn · degradation curve** | "We'll measure against a fair baseline using the same model under the same limit, add one technique at a time, and squeeze the box live to show Pecko degrading gracefully instead of crashing." |
| 5 | **Live now:** terminal with `systemd-run` limit + one stage running (e.g. Moonshine transcribing) · 4 roles: Ears · Brain · Voice · Spine | "This is the limit, enforced by the kernel right now. Four of us own one stage each, with a frozen interface between them, so we build in parallel and integrate tonight." |

Q to expect at PC1: "Which models?", "How will you measure energy?", "What's your baseline?" Answers are in §8.

---

## 3. PC2 add-on slide (12:00 AM)

| On the slide | Say |
|---|---|
| **Built:** ✅ loop offline under cap · ✅ baseline measured (2.06 s p50) · ✅ streaming + smart endpoint · ✅ cache · ⏳ early prefill · ⏳ degradation controller | "Here's where we are. First real numbers: baseline 2.06 s p50, Pecko 0.88 s p50 (24 synthetic turns, VM, same cap). Tonight we add early prefill and the controller, then we only measure." |

Show the dashboard live if it exists. Bring the waterfall with whatever rows are measured.

---

## 4. Finale (20 min): time plan

| Block | Time | Who |
|---|---|---|
| Story slides 1–6 | 5 min | Sir Jabin (lead) |
| **Live demo** (§6) | 7 min | Spine drives the laptop, Sir Jabin narrates, a judge speaks |
| Proof slides 7–10 | 4 min | Ears + Voice each own their slide |
| Impact + ask | 1 min | Sir Jabin |
| Q&A | ~3 min (more if allowed) | Whoever owns the stage being asked about |

Confirm with organisers whether Q&A is inside the 20 minutes. If it is outside, give the demo 2 more minutes.

---

## 5. Finale deck, slide by slide (live mode: ≤ 3 points, one idea per slide)

Rubric key: **P** = problem rubric (Lat 25 · Foot 25 · New 20 · Quant 15 · Degr 15) · **E** = event rubric (Innov · Tech · Feas · UX · Pitch).

### Slide 1 · Title
- **On slide:** *Pecko* · "A voice assistant that thinks while you talk" · small line: 2 CPU · 2 GB · no GPU · no internet
- **Say:** "Hi, we're Plumbers. This is Pecko, a voice assistant that runs entirely on this laptop, squeezed into 2 cores and 2 gigabytes, with the Wi-Fi off. Ask it anything and it answers in under a second." *(only if measured)*
- **Transition:** "To see why that's hard, look at what usually happens."
- **Covers:** E-Pitch

### Slide 2 · Problem
- **On slide:** one big number: **2.06 seconds** (p50; p90 2.50 s) · caption "a standard offline assistant, same LLM, same 2 CPU / 2 GB limit" · footnote: (VirtualBox VM, 2 CPU / 2 GB cgroup, swap 0, 24 synthetic Piper-voice questions, no speaker = 0 ms device latency)
- **Say:** "We built the standard way first: a popular VAD, Whisper, a small language model, Piper speech. Same laptop, same 2-core limit. You wait about 2 seconds for every reply (2.06 s median, 2.50 s p90). In a conversation, anything over about a second feels broken."
- **Land:** 2.06 s p50 / 2.50 s p90, measured by us (VM, synthetic questions, no speaker).
- **Transition:** "We expected the models to be the problem. They weren't."
- **Covers:** P-Lat, E-Feas

### Slide 3 · Insight
- **On slide:** **"The models aren't slow. The waiting is."** + the 5-block serial waterfall with idle gaps shaded
- **Say:** "Here's where those seconds go. 800 ms waiting to be sure you've stopped. Then Whisper starts from zero. Then the model re-reads the whole prompt. Then it writes the full reply before anything is spoken. Every stage sits idle while the last one finishes."
- **Land:** the 800 ms silence timer alone is ~39% of the baseline's 2059 ms median (B0 endpoint ~803 ms on every turn). The full split of the remaining waiting is `[MEASURE %]` (not yet measured).
- **Transition:** "So we stopped making models faster and started removing the waiting."
- **Covers:** P-New, E-Innov

### Slide 4 · Solution
- **On slide:** the overlapped timeline (stages stacked, starting during speech) · 3 labels: *ends your turn sooner · thinks while you talk · speaks at the first comma*
- **Say:** "Pecko overlaps everything. Speech recognition streams while you talk. A turn detector listens to *how* you speak, so it knows you've finished in about 150 milliseconds without cutting you off mid-thought. The language model pre-reads your words into its memory before you stop. Speech begins at the first clause, not the full reply. And common questions skip the model entirely with pre-made audio."
- **Transition:** "Here's how that fits in 2 cores."
- **Covers:** P-Lat, E-Innov

### Slide 5 · How it works
- **On slide:** the architecture diagram from `solution.md §3` (Ears → Brain → Voice inside one cgroup box, Spine around it), rendered with diagram-forge. Small footer with the stack: Moonshine · Smart Turn · llama.cpp `[model]` · Piper · sherpa-onnx
- **Say:** "Four stages, one kernel-enforced box. Ears listens, Brain thinks, Voice speaks, Spine schedules the two cores by phase: while you talk, one core listens and the other pre-reads; when Pecko speaks, one core writes and one core talks. No thread ever spins waiting."
- **Land:** "every model is quantized and every thread pool is capped at one."
- **Covers:** P-Quant, E-Tech

### Slide 6 · What's new (before the demo, so judges watch for it)
- **On slide:** **"Work on whichever is later."** · `first audio = max(C, R) + d` · measured wins: fusion endpointer (C) + system-prompt KV cache (R)
- **Say:** "First audio is the later of two things: knowing you've finished, and having the first clause ready. We measured which one is late and attacked it: a fusion endpointer that commits in about 300 ms instead of 800, and a cached system prompt so the answer starts fast. We also built speculation, starting the answer before you finish, but on 2 cores early work steals CPU. On our test set it didn't pay: no measurable latency gain, 0.1 to 0.3 extra CPU-seconds a turn. Once the prompt is cached, the commit is rarely the late term. So speculation is something we gate off when it doesn't pay, and we're telling you it didn't here."
- **Honesty note:** do not claim speculation as a measured win. Leave-one-out source: `data/results/ablation-e2e-summary.md`.
- **Transition:** "Let's try it."
- **Covers:** P-New, E-Innov, E-Tech

### → LIVE DEMO (§6)

### Slide 7 · Proof: the waterfall
- **On slide:** cumulative waterfall chart A0 → A7 (from `solution.md §6`), baseline bar on the left, Pecko bar on the right, each step labelled with its saving
- **Say:** "Every bar is one technique added on its own, same test set, same limit. The biggest single win is the fusion endpointer: replace it with a fixed 800 ms timer and the median goes from 882 to 1400 ms. The system-prompt KV cache is next: 1374 ms without it, and 1.97 instead of 1.33 CPU-seconds a turn. Speculation: no measurable change. Together: 2059 to 835 ms median, p90 2496 to 1280 ms." *(Leave-one-out, not a cumulative A0→A7 build-up: each bar turns ONE technique off from full Pecko; one run of 24 synthetic turns each, noise ~±50 ms p50 / ±150 ms p90; ~190 ms of the gap to B0 (all four off: 1810 ms) is unattributed (streaming ASR, first-clause TTS). Source: `data/results/ablation-e2e-summary.md`.)*
- **Land:** p50 and p90, with the test set size: today 24 synthetic paired turns, 1 run each (60 held-out human turns × 3 not yet measured).
- **Covers:** P-Lat, P-New, E-Tech

### Slide 8 · Proof: footprint
- **On slide:** 3 numbers, baseline → Pecko: **CPU-seconds/turn 1.96 → 1.20** · **peak RAM 917 vs 846 MiB (about the same; ±90 MiB run to run)** · **joules/turn: not yet measured** (VirtualBox VM, 2 CPU / 2 GB cgroup, swap 0, 24 synthetic Piper-voice questions, no speaker = 0 ms device latency)
- **Say:** "Faster usually means burning more. Not here: per turn, Pecko uses 1.20 CPU-seconds vs 1.96, 1.63 times less, and RAM is about the same as the baseline: 846 vs 917 MiB, but identical runs of Pecko vary by 90 MiB, so we don't call that a win. Our first build used 1140 MiB; profiling found an unused ASR model and torch loaded for nothing, and removing them brought it to about 850. Energy per turn needs the CPU's RAPL counters, which our VM doesn't expose; `[J]` vs `[J0]` only once measured on native Ubuntu."
- **Land:** 1.63× less CPU time per turn, RAM about the same. (Energy ratio only if measured.)
- **Covers:** P-Foot, E-Feas

### Slide 9 · Proof: squeeze the box
- **On slide:** p50 at 2 CPU vs 1 CPU (2 GB): B0 2059 → 2643 ms (+584) · Pecko T2 835 → 996 ms (+161) · failures 0 vs 0 · CPU-s/turn at 1 CPU 2.05 vs 0.95
- **Say:** "Real devices get starved. Halve the CPU and the baseline slows by almost 600 ms at the median; Pecko, started on its lighter 1-CPU tier, slows by 160 and still wins all 24 turns, at half the CPU time. Neither failed a turn." Do NOT say Pecko switches tiers by itself: the tier is chosen at launch; there is no automatic switching yet.
- **Land:** failures at 1 CPU: B0 0 vs Pecko 0; B0 +584 ms p50, Pecko T2 +161 ms. *(T2 still uses Qwen3-0.6B with ctx 512 / n_predict 25, shorter answers, quality not scored. One fixed-T0 turn lost by 52 ms. The 1.25 GiB cap never bound. Source: `data/results/degradation-summary.md`.)*
- **Covers:** P-Degr, P-Quant, E-Feas

### Slide 10 · Honest numbers (one slide earns a lot of trust)
- **On slide:** 3 small lines: *Same model in baseline and Pecko* · *Fillers off in every number* · *Held-out questions we never tuned on*
- **Say:** "Three things we did to keep ourselves honest. Our baseline uses the same language model, so the gain is the system, not a smaller model. We don't count 'umm' sounds as an answer. And we tested on questions we never tuned on, including people outside our team." Negative results we have: Piper int8 was 2.4-3.2× *slower* than fp32 (Windows dev laptop, voice/RESULTS.md), so we ship fp32; and our first integrated build used *more* RAM than the baseline (1140 vs 917 MiB) until we profiled it (now ~850, about the same as the baseline, not less). Speculation (early prefill) gave no measurable gain on our test set. Quantization fact: LLM Q4_K_M beat Q8_0 on first chunk p50, 177 vs 261 ms (brain/RESULTS.md, VM, same cap).
- **Covers:** E-Pitch, P-Quant (if the int8 finding exists)

### Slide 11 · Impact + ask
- **On slide:** **"Voice AI for the next billion devices, without the cloud."** · 3 icons: clinic kiosk · classroom · assistive device · next: Raspberry Pi · Hindi/Tamil
- **Say:** "Most of the world's devices are cheap, offline, or private by necessity. Pecko's design (finish early, think early, waste nothing) is what makes voice work there. Next we take it to a Raspberry Pi and Indian languages; we already have Hindi `[status]`. We'd like your vote to keep going."
- **End on this slide.** Take questions here. No "Thank you" slide.
- **Covers:** E-Feas (scalability), bonus items

---

## 6. Live demo script (7 min, rehearse it 3+ times)

**Setup before the judges arrive:** charger in, performance mode, wired speaker or headset, network off, Pecko warmed up (one dummy turn), dashboard on the second half of the screen, terminal with the cgroup status visible, backup video open in a hidden tab.

**Status as of 04:10, 9 Oct:** live mic is **untested**. Fallback (decide before going on stage): play the WAVs, `scripts/run_pecko.sh --wav data/clips/synthetic/q1.wav ... --ears-tier 2`. With a live speaker, expect about **+250 ms** over the headline (`data/results/demo-smoke-audio`: R 831 ms → first audio 1081 ms), so don't promise 835 ms on stage.

| Step | What happens | What we say |
|---|---|---|
| 1 | `systemctl --user status 'pecko-*.scope'`, then `cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/app.slice/pecko-*.scope/{cpu.max,memory.max,memory.peak}` (if the path differs, find it first with `systemd-cgls`). Toggle Wi-Fi off on screen. | "The kernel is enforcing 2 cores and 2 gigs: cpu.max 200000 100000, memory.max 2 GiB. The network is off. No GPU." |
| 2 | Teammate: "Hey Pecko, what can you do?" (cache hit) | "That one came from a pre-made answer, no language model." Do **not** say "instant": on short phrases the endpointer waits ~1.2 s (the one measured cached turn, "thank you", was 1209 ms, all endpoint wait). |
| 3 | Teammate: a real open question with a pause in the middle ("What's a good name for... a coffee shop near a college?") | "Notice it didn't cut in during the pause. That's the turn detector." Point at the waterfall on the dashboard. |
| 4 | **Hand the mic to a judge:** "Ask it anything." (only if the live mic was tested OK; otherwise play a WAV) | Read the latency off the dashboard after the reply. |
| 5 | Barge-in: **SKIP.** Untested end to end. | (say nothing) |
| 6 | **Squeeze:** `systemctl --user set-property --runtime 'pecko-*.scope' CPUQuota=100%`, then ask again | "We just halved its CPU, live. Slower, but still answering." Do **not** say "it dropped a tier": there is no automatic tier switching. |
| 7 | `cat .../pecko-*.scope/memory.events` → `oom_kill 0`. Energy line **only if** RAPL was measured on this machine; otherwise skip it. | "No crash, no out-of-memory kill." |

**Fallbacks (decide before going on stage):**
- Live mic fails → play the WAVs (command above) and narrate.
- Wake word misfires → push-to-talk key, say nothing about it.
- Something crashes → restart takes `[MEASURE]` s (not yet measured); if it's longer than 20 s, play the backup video of the same script and keep narrating.
- Judge asks something weird → that's fine; an honest "I'm offline and can't check that" is a good answer and shows the router.

---

## 7. Rubric coverage check (every criterion must have a visible slide)

| Criterion | Weight | Slides | Demo step |
|---|---|---|---|
| Offline / no GPU (pass/fail) | gate | 1, 5 | 1 |
| Latency vs baseline | 25% | 2, 3, 4, 7 | 2–4 |
| Footprint (CPU, RAM, energy) | 25% | 8 | 7 |
| What's new + ablation | 20% | 3, 6, 7 | 3 |
| Quantization + offload | 15% | 5, 9, 10 | – |
| Graceful degradation | 15% | 9 | 6 |
| Bonus: cached TTS · multilingual · small device | extra | 4, 11 | 2 |
| Innovation & Creativity | event | 3, 6 | – |
| Technical Complexity | event | 5, 6, 7 | – |
| Feasibility & Scalability | event | 8, 9, 11 | 6 |
| Design & UX | event | dashboard on screen during the demo | all |
| Presentation & Pitch | event | the whole arc + Q&A | – |

**Gap watch:** quantization is the thinnest. Make sure slide 5 or 10 shows one real quantization comparison (LLM Q4 vs Q8, or TTS int8 vs fp32, with speed and quality).

---

## 8. Q&A bank (owner answers; practise out loud)

| Likely question | Short answer | Owner |
|---|---|---|
| "Isn't your baseline a straw man?" | "Same language model, same limit, and we also show a tuned baseline (B1) and a 'typical' one with a bigger model. Our gain over the tuned one is `[x]`." *(B1 and the bigger-model baseline are not yet measured; until then say only: same model, same limit, B0 described in baseline/run.py.)* | Spine |
| "Fillers fake latency, did you use them?" | "No. Every number is first audio of the actual answer. Fillers are off." | Voice |
| "What happens if the user keeps talking after you started thinking?" | "Ears sends a cancel. The early work is thrown away and nothing was spoken. On our 12-turn Brain test set, 10-19% of early prefill work was wasted (brain/RESULTS.md); the cost in ms/J is `[ms/J]` (not yet measured)." | Brain |
| "Why not a bigger model for better answers?" | "An 8B model needs about 5 GB at 4-bit, more than double the whole budget, and writes a few words per second on 2 cores. We chose the best model that passes our latency, rewind and RAM checks." | Brain |
| "Why that model?" | Bake-off table: TTFT, rewind works, RAM, answer score. "Hybrid models were faster but the runtime can't rewind their memory, which breaks early thinking." | Brain |
| "How do you measure energy?" | "Intel RAPL package counters before and after a scripted session, idle power subtracted, charger in, same power mode. It's CPU package energy, not the whole laptop, and we say so." | Spine |
| "How do you know the limit is really enforced?" | Show `cpu.max`, `memory.max`, `memory.peak`, `systemd-cgtop`, `oom_kill 0`. | Spine |
| "How do you know when someone has finished speaking?" | "A tiny 8 MB model listens to intonation, plus silence length and whether the sentence ends on 'and' or 'the'. It adapts to each speaker's pause length." | Ears |
| "Does it work with Indian accents?" | "We tested on all four of our voices plus `[n]` outsiders: WER `[x]`. We added hot-words for local names." | Ears |
| "Is your cache cheating?" | "Only fixed intents (greetings, time, 'who are you'). On 18 held-out questions that should go to the LLM, the router answered from cache 0 times (0/18, voice/RESULTS.md)." | Voice |
| "What's actually new? Pipecat/LiveKit do streaming." | "Streaming is the baseline we tuned, not our claim. Our claim is deciding when early work pays under a hard CPU cap, and staying alive as the cap shrinks. Speculative voice research runs on GPUs." | Sir Jabin |
| "Did you write this or use a framework?" | "Open-source models and runtimes, our own orchestration, scheduler, endpointer, router, cache and controller, all in the repo history from today." | Spine |
| "Will it run on a phone or Pi?" | "Every part has ARM builds. `[status: tested / next step]`." | Spine |
| "Multilingual?" | "Hindi `[status]`: the wake phrase picks the language. Tamil is harder offline; we say so." | Ears |
| "What breaks first if you squeeze further?" | "Below about `[x]` it drops the language model and answers only from cache, and it tells the user it's in low-power mode." | Spine |

Rule for Q&A: if we don't know, say "we haven't measured that" and say how we would. Never guess a number.

---

## 9. Numbers to collect for the deck (owners fill, Spine verifies)

| Number | Slide | Owner |
|---|---|---|
| B0 p50 / p90 latency, same cap | 2, 7 | Spine |
| Share of B0 time that is waiting | 3 | Spine |
| Each waterfall step's saving (A1–A7) | 7 | each owner |
| Pecko p50 / p90, 60 held-out turns × 3 | 7 | Spine |
| CPU-s/turn, peak RAM, J/turn (gross + idle-adjusted), baseline vs Pecko | 8 | Spine |
| Idle CPU while waiting for the wake word | 8 | Ears |
| Degradation curve points + failures per cap | 9 | Spine |
| Cache hit latency and false-hit rate | demo, Q&A | Voice + Brain |
| Endpoint delay and false cut-offs | Q&A | Ears |
| Speculation cancel rate and wasted ms/J | Q&A | Brain |
| One quantization comparison (speed + quality) | 5 or 10 | Brain / Voice |
| WER on team + outsider voices | Q&A | Ears |

---

## 10. Submitted (read-alone) deck: differences

Same 11 beats, but:
- Every slide states its point as a full headline ("Pecko answers in 0.88 s vs 2.06 s (p50) on the same 2-core limit").
- Slides 7–9 carry the full tables, not just charts.
- Add a **"How to run it"** slide (one command, README link) and a **"Built in 24 h"** slide (repo link, commit graph screenshot, what is ours vs open-source).
- Add the demo video link on slide 1 and slide 7.

---

## 11. Rehearsal plan

1. After M4: one full timed run of the finale (slides + demo), even with placeholder numbers.
2. After numbers are in: second run, with a teammate playing a hostile judge from §8.
3. Before submission: final run with the backup video tested on the presenting laptop.
4. Everyone can explain the whole architecture in one minute (rules: "the team must understand what they built").
