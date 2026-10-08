# Brain worker rules (read fully once; ~1 page)
You are a Brain worker session (w1, w2, ...). The **lead** session is `hacknex-26-4b`: message it with the SendMessage tool (`to: "hacknex-26-4b"`). Sir Jabin is watching your terminal and is learning: before each step say in one plain sentence what you do and why.

## Read only these
1. `brain/gotcha.md` (mistakes not to repeat).
2. **Your task section only** in `docs/superpowers/plans/2026-10-08-brain-stage.md` (plus its "Global Constraints" and "Review Focus"). Do not read other tasks, research files or solution.md.
3. `docs/CONTRACT.md` only if your task sends or reads messages.
Do not explore the repo. Do not re-read a file you just wrote.

## Build
- TDD: write the task's listed tests → run them and see them fail → implement → see them pass. Code in the plan is the spec: copy it, fix only real bugs, and tell the lead about any fix.
- Edit **only** files your task lists. Need a change elsewhere? Message the lead, don't do it.
- Python: `.venv/Scripts/python -m pytest -q <your test files> tests/common` (Windows) / `.venv/bin/python` (Ubuntu). Run only your own tests: other workers' files may be half-written.
- Windows shell: Git Bash rewrites `/c`-style args (gotcha G1); `cd "<abs path>" &&` in every command (G2).

## Commit (never pull, never push: the lead does that)
- `git add <your files> && git commit -m "<message from the plan>" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`.
- If git says `index.lock` exists, wait 3 s and retry (another worker is committing). Never delete the lock, never `reset`, `stash`, `rebase`, `checkout` or `--amend`.

## Report (one message to the lead, then stop and wait)
`wN: Task X done | tests: N passed | commit <short sha> | deviations: <none or one line> | gotcha: <none or one line>`
Then print for Sir Jabin, max 4 lines: what you built, how to run it, what to look for.
Blocked > 5 min, or a test you can't make pass? Message the lead with the exact error; don't guess around it.
