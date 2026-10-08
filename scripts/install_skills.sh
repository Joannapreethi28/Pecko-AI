#!/usr/bin/env bash
# Optional: install the Claude Code skills Sir Jabin's Brain session uses, at the exact
# commits that were reviewed on 8 Oct 2026 (see docs/SKILLS.md). Dev tooling only:
# none of this is part of Pecko or runs at Pecko runtime.
#
# Usage:  bash scripts/install_skills.sh              # skills + shadcn MCP + Chrome extension files
#         bash scripts/install_skills.sh --with-gstack   # also gstack (needs bun >= 1.4.2)
# Works on Ubuntu and on Windows Git Bash. Installs into ~/.claude/skills (your user only).
set -euo pipefail

WITH_GSTACK=0
[ "${1:-}" = "--with-gstack" ] && WITH_GSTACK=1

SKILLS="$HOME/.claude/skills"
SRC="$(mktemp -d)"
trap 'rm -rf "$SRC"' EXIT
mkdir -p "$SKILLS"

# repo  pinned-commit
fetch() {
  local repo="$1" sha="$2" dir="$SRC/${1//\//_}"
  git init -q "$dir"
  git -C "$dir" fetch -q --depth 1 "https://github.com/$repo.git" "$sha"
  git -C "$dir" checkout -q FETCH_HEAD
  echo "$dir"
}

# copy <src-dir> into ~/.claude/skills, refusing to overwrite an existing skill
put() {
  local name; name="$(basename "$1")"
  if [ -e "$SKILLS/$name" ]; then echo "  skip $name (already installed)"; return; fi
  cp -r "$1" "$SKILLS/" && echo "  + $name"
}

echo "impeccable (UI design)"
d=$(fetch pbakaus/impeccable 778c8a7b71ccd5bfe3ca6ac68c15d9d872d0f87d)
put "$d/.claude/skills/impeccable"

echo "emilkowalski/skills (UI polish + animation)"
d=$(fetch emilkowalski/skills e8a175de22ae1e49370fc144c1f3bb9aeedf988d)
for s in "$d"/skills/*/; do put "${s%/}"; done

echo "vercel-labs/agent-skills (React/web; deploy-to-vercel, vercel-cli-with-tokens, vercel-optimize skipped)"
d=$(fetch vercel-labs/agent-skills 063bee94c3f4df8453406c830b0a7df0f2860278)
for s in composition-patterns react-best-practices react-native-skills react-view-transitions \
         web-design-guidelines writing-guidelines; do put "$d/skills/$s"; done

echo "linkedin-agent-skill (posts about the project)"
d=$(fetch Jakeschincariol/linkedin-agent-skill add2c23882fe79180737d242ff80a5da205eda6a)
for s in "$d"/skills/*/; do put "${s%/}"; done

echo "brag (demo / launch video)"
d=$(fetch latent-spaces/brag 7079945d391573edebe48fdc0a23b39c4b4e8726)
put "$d/skills/brag"; put "$d/skills/brag-slim"

echo "shadcn MCP (component reference for the dashboard)"
d=$(fetch Jpisnice/shadcn-ui-mcp-server 30efb8a0bf8d968e4c6635e4491c20da96e49d20)
put "$d/skills/shadcn-ui-mcp"
if command -v claude >/dev/null 2>&1; then
  if claude mcp get shadcn >/dev/null 2>&1; then
    echo "  shadcn MCP already registered"
  elif [ "$(uname -s | cut -c1-5)" = "MINGW" ] || [ "$(uname -s | cut -c1-4)" = "MSYS" ]; then
    # Git Bash rewrites "/c" to "C:/" unless path conversion is off (see brain/gotcha.md G1).
    MSYS_NO_PATHCONV=1 claude mcp add --scope user shadcn -- cmd /c npx -y @jpisnice/shadcn-ui-mcp-server@3.0.0
  else
    claude mcp add --scope user shadcn -- npx -y @jpisnice/shadcn-ui-mcp-server@3.0.0
  fi
else
  echo "  claude CLI not found; skipped MCP registration"
fi

echo "design-md-chrome (Chrome extension files -> ~/tools/design-md-chrome)"
d=$(fetch bergside/design-md-chrome 8e07614fb18752ab1ee14dd65a8ff93e63c9b13b)
if [ -e "$HOME/tools/design-md-chrome" ]; then echo "  skip (already present)"
else mkdir -p "$HOME/tools" && cp -r "$d" "$HOME/tools/design-md-chrome" && rm -rf "$HOME/tools/design-md-chrome/.git" \
  && echo "  + load it: chrome://extensions -> Developer mode -> Load unpacked -> ~/tools/design-md-chrome"
fi

if [ "$WITH_GSTACK" = 1 ]; then
  echo "gstack (dev workflow; solo mode, gstack- prefix, telemetry stays off)"
  command -v bun >/dev/null 2>&1 || { echo "  bun not found: npm install -g bun@1.4.2, then re-run"; exit 1; }
  if [ -e "$SKILLS/gstack" ]; then echo "  skip (already installed)"
  else
    git clone -q https://github.com/garrytan/gstack.git "$SKILLS/gstack"
    git -C "$SKILLS/gstack" checkout -q 9a1dc81a2b96e7b74a15e5911175bc04de7659e9
    (cd "$SKILLS/gstack" && ./setup --no-team --prefix < /dev/null)
  fi
fi

echo "Done. Restart Claude Code to pick up new skills."
