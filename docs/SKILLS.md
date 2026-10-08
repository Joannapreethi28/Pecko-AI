# Claude Code skills we use (optional dev tooling)

**What a "skill" is:** a folder with a `SKILL.md` instruction file (sometimes plus small helper scripts) that Claude Code loads when a task matches it. Think of it as a checklist written by an expert that Claude follows instead of improvising. Skills only change how Claude works while we build. **None of them are part of Pecko or run when Pecko runs.**

**Install (if you want them):** `bash scripts/install_skills.sh` (add `--with-gstack` for gstack; needs `npm install -g bun@1.4.2` first). It installs into your own `~/.claude/skills`, at the exact commits reviewed on 8 Oct 2026, and never overwrites a skill you already have. Works on Ubuntu and Windows Git Bash.

**Why a script and not the files in this repo:** the third-party skills are ~3,000 files of other people's code. Committing them would bloat our git history, which judges read (the rules forbid starting from pre-built code), and gstack must be built per machine anyway.

## What each one is for

| Skill | In plain words | When it fires for us | License |
|---|---|---|---|
| **impeccable** (`/impeccable audit`, `polish`, `critique`…) | A senior designer's checklist: layout, typography, colour, spacing, accessibility, "AI slop" patterns. | Building and polishing the **live dashboard** (Design & UX criterion). | Apache-2.0 |
| **emilkowalski/skills** (`animate`, `emil-design-eng`, `break-ui`, `review-animations`, …) | UI polish and motion done right, plus `break-ui` which stress-tests a screen with worst-case data. `write-swift`, `animate-expo`, `mobile-native` are iOS/Expo/mobile-web and won't fire for Pecko. | Dashboard polish, the C/R waterfall animation, worst-case transcripts. | MIT |
| **vercel-labs/agent-skills** (`react-best-practices`, `composition-patterns`, `web-design-guidelines`, `writing-guidelines`, …) | React/web performance and accessibility rules; a prose style review. | Only if the dashboard becomes a web page; `writing-guidelines` for README/deck text. | no license file in repo |
| **linkedin-agent-skill** (`li-post`, `li-carousel`, `li-human`, …) | Writing LinkedIn posts/carousels about the project. Drafts only; never posts without an explicit yes. | After submission, to post about Pecko. | MIT |
| **brag** / **brag-slim** | Turns the project into a short launch/demo video (uses `npx hyperframes`). | The **backup demo video** for the submission. | MIT |
| **shadcn-ui-mcp** (MCP server + skill) | Live reference for shadcn/ui React components, pinned to v3.0.0. Runs locally via `npx`; no token given (60 GitHub requests/hour). | Only if the dashboard is a React web page. | MIT |
| **gstack** (`/gstack-review`, `/gstack-qa`, `/gstack-investigate`, `/gstack-plan-eng-review`, …) | A full dev workflow kit: plan reviews, code review, QA, debugging, release docs. Installed in solo mode with a `gstack-` prefix; telemetry off; no hooks added. `/gstack-cso` needs VS 2022 C++ Build Tools on Windows. | Reviewing plans and code before merging to `main`. | MIT |
| **design-md-chrome** (Chrome extension) | Reads a web page's styles and writes a `DESIGN.md` for Claude to copy the look. Permission: only the tab you click it on; sends nothing anywhere. | Grabbing a style reference for the dashboard. Load: `chrome://extensions` → Developer mode → Load unpacked → `~/tools/design-md-chrome`. | MIT |

**Already built in (no install):** the `superpowers` process skills we lean on most: `writing-plans`, `test-driven-development`, `systematic-debugging`, `verification-before-completion`, `requesting-code-review`.

## Deliberately not installed
- `vercel-labs` **deploy-to-vercel** (uploads the whole project folder to a public Vercel URL), **vercel-cli-with-tokens**, **vercel-optimize**: Pecko is offline; no use, and an accidental upload is a real risk.
- **agent-reach**: uses your logged-in account cookies (ban risk).
- gstack **team mode** (would force gstack on every teammate via a committed hook) and its suggested CLAUDE.md rule banning the Claude-in-Chrome tools.

## Team Board mod (Claude Code)
A side pane + status line showing every role's handoff status, Brain modules on `main` and the latest pushes (refreshes from git every 60 s), toasts on new pushes or a changed contract, and a guard that blocks edits to `docs/CONTRACT.md`. Load it: `claude --plugin-dir tools/mods/team-board`, then `/team-board`. Tests: `claude plugin test tools/mods/team-board`.
