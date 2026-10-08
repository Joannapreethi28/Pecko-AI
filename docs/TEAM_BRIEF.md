> **NOTE (8 Oct, merge):** goal, gate, scoring and working agreement below are still valid. The message **contract in §5 is v1 and is superseded by `docs/CONTRACT.md` (v2).** Where a role file disagrees with `docs/solution.md`, solution.md wins.

# HNX26EPS08: On-Device Conversational Stack. TEAM BRIEF (everyone reads this first)

## 1. The goal
Build a **voice-in → voice-out assistant that runs fully offline on CPU only**, inside a **small, declared resource limit** (e.g. 2 CPU cores, 2 GB RAM), and **beats a standard "default" stack** on speed and footprint.

```
You speak → [EARS] → text → [BRAIN] → text chunks → [VOICE] → sound
                   ↑ [SPINE: wiring, limits, measuring, baseline] ↑
```

## 2. Pass/fail gate (fail this and nothing else counts)
- No cloud calls. No GPU. CPU only. Fully offline.
- Working loop under a limit we **declare and show enforced live**.
- Wake-word / VAD handling present.
- Beats the baseline on **end-to-end latency** (end of speech → first audio of reply) **at lower resource use**.
- We report measured **CPU, RAM, energy** + a short write-up.

## 3. How we're scored
| Criterion | Weight |
|---|---|
| End-to-end latency vs baseline | 25% |
| Resource footprint vs baseline (CPU, RAM, energy) | 25% |
| "What's new" vs baseline, proven by an ablation | 20% |
| Quantization + offload strategy | 15% |
| Graceful degradation when the limit is tightened | 15% |
| Bonus: multilingual, smaller device, cached TTS | extra |

Judges speak **unseen requests** and measure on **our laptop** under our declared limit. So it has to be robust, not just demo-able.

## 4. Stretch goals (we want these, in this priority order after the core works)
1. **Cached / pre-synthesized TTS for common responses** to cut latency. Owner: **Voice**. Cheapest bonus, do it early.
2. **Keep quality as the resource limit is tightened further.** Owner: **Spine** (controller) + **Brain** (model tiers). Overlaps with the 15% degradation score.
3. **Multilingual support.** Owners: **Ears** (ASR), **Brain** (LLM reply language), **Voice** (TTS voice). **Spine** collects results. Be honest about quality limits.
4. **Run the loop on a smaller device the team owns** (phone, Raspberry Pi or similar). Owner: **Spine** leads. Ears, Brain and Voice each keep their stage portable (no laptop-only dependencies).

## 5. The contract between stages (agree now, do not change without telling everyone)
All stages talk using small JSON messages, one per line. This lets each person build and test alone with fake inputs.

**Ears → Brain**
```json
{"type":"partial","text":"what is the wea","t":12.31}
{"type":"final","text":"what is the weather like","t_eos":13.02,"t_endpoint":13.20}
```
**Brain → Voice**
```json
{"type":"chunk","text":"I can't check live weather, ","seq":0}
{"type":"chunk","text":"but I can help with other things.","seq":1,"last":true}
```
**Voice → speaker:** raw audio plays, and Voice logs `t_first_audio_out`.

**Shared log line (every stage writes these, Spine reads them):**
```json
{"stage":"brain","event":"first_token","t":13.41}
```
All times use one shared clock (seconds, monotonic).

**Interface rules**
- Python 3.10+, same virtual environment layout, one repo.
- Each stage is a class or module with `start()`, `feed(...)`, `stop()` and an async or queue output. Spine will wire them.
- Each stage must run **standalone with a mock** (Ears from a WAV file, Brain from typed text, Voice from hardcoded sentences).
- Every stage must work under the CPU/RAM limit on its own, not just when the others are idle.

## 6. Working agreement
- **Step 1, solo research (no fixed time limit, the team sets the clock; no peeking at each other or at any shared report).** Independent research gives us different ideas. Use your own search, GitHub, papers, docs.
- **Step 2, return your research as a `.md`** using the template in section 8 and send it to Sir Jabin in the merge chat.
- **Step 3, merge.** Sir Jabin combines all four into one architecture, stress-tests it, and sends back the final per-role build files.
- **Step 4, parallel build** with mocks. Integrate at the milestone below.

## 7. Milestones (the team sets the clock times, only the order is fixed)
1. **Half-baked end-to-end prototype before 6 pm:** speak → hear a reply, fully offline. Slow and ugly is fine.
2. **Baseline script measured as early as possible.** Every score is "vs baseline", so we need the number early. Spine owns this.
3. **Integrated and stable by hour 15.** After that we only refine, measure, run ablations and write up.
4. **Freeze code with enough buffer** for the demo rehearsal and a backup demo video.

## 8. Research return template (copy this, fill it, send back)
```
# <ROLE> research: <your name>
## 1. Top 3 options I found (name, size, speed, RAM, license, link)
## 2. My pick and why (and what I rejected and why)
## 3. How to install and run it (exact commands that worked)
## 4. Measured numbers (if I tried it): latency, RAM, CPU on how many cores
## 5. Risks and things that could break
## 6. One idea I think could be NEW (beyond the obvious stack)
## 7. Stretch goals: what my stage needs for multilingual / smaller device / cached TTS / tighter limits
## 8. Questions for other roles (what I need from them)
```
Rules for the research: **numbers beat opinions.** If you tried it, say so. If it's from a blog or vendor, say that too.
