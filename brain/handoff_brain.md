# Brain handoff (read this to know where Brain is; Brain updates it every time it pushes)
Owner: Sir Jabin · Last update: 8 Oct, evening · Branch: `main` (team decision: everyone pushes to main, own folders only, `git pull --rebase` before push)

## Status
- ✅ Repo, plan, contract, role specs pushed. Build plan: `docs/superpowers/plans/2026-10-08-brain-stage.md` (12 tasks).
- ✅ Windows dev env: Python 3.13 `.venv`, `brain/requirements.txt`, llama.cpp **b11501** CPU build in `models/llama.cpp/b11501-win/`. Qwen3-0.6B Q4_K_M + Q8_0 downloading.
- ⏳ Next: Task 1 (`common/clock.py`, `common/log.py`), then Tasks 2/3/4/8 in parallel.
- Judged runs happen in the **Ubuntu VM** under the cgroup. Windows numbers are dev-only.

## What other roles need to know / do (please reply in your own handoff file)
| To | Ask | Why |
|---|---|---|
| **Spine** | Brain is writing `common/clock.py` (`now()`) and `common/log.py` (`EventLog`) now, exactly the line format in CONTRACT.md. Extend, don't change. Also adds root `pyproject.toml` (pytest config only). | Everyone imports them; first come, first served. |
| **Spine** | Bake-off (Task 9) and Brain ablation (Task 12) must run inside your cgroup wrapper. Need the `systemd-run` command working in the VM. | Judged numbers only under the cap. |
| **Ears** | `partial.stable`, `tentative_final.text` and `final.norm` must use the **same normalization** (lowercase, no punctuation, same filler handling). Brain builds the prompt from these. | If they differ, early prefill misses the KV cache and saves 0 ms. |
| **Voice** | Brain will push `brain/intents.yaml`: each `clip` + exact `say` text is a reply you pre-synthesize (incl. `didnt_catch`, `low_power`). Brain sends a final **empty** chunk with `last:true` when the reply ends. | Cached replies skip the LLM; empty last = end of turn. |
| **Voice** | Every Brain chunk ends with a space except the last; first chunk cut at the first `, . ? ! ; :` after ≥ 2 words. | So your phrase chunker can trust boundaries. |
| **All** | Hold-and-release (contract v2.1: `held:true`, `commit`) is Task 11, built only after all four agree. Brain will log `held_valid{gen, match}` so Spine knows when to send `commit`. | Contract changes need all four. |
| **Mobile** | llama.cpp b11501 ships a prebuilt `llama-b11501-bin-android-arm64.tar.gz`; may save the Termux build. | Phone spike speed. |

## How to run Brain (once Task 6 lands)
`python -m brain.mock_cli` with `llama-server` on :8080. Tests: `pytest -q`.

## Skills (optional)
`bash scripts/install_skills.sh` (see `docs/SKILLS.md`).

## Mistakes we already made (don't repeat): `brain/gotcha.md`
