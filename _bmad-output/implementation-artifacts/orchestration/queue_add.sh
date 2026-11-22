#!/usr/bin/env bash
# queue_add.sh <worktree> <markdown-section-file>
# Rebase the story branch on origin/main and append a section to the desktop verification queue.
set -euo pipefail
cd "$1"; git fetch -q origin; git rebase -q origin/main
Q=_bmad-output/implementation-artifacts/desktop-verification-queue.md
printf '\n' >> "$Q"; cat "$2" >> "$Q"
git add "$Q"; git commit -q -m "Add desktop verification items

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017fHFDg8qzK1xh593WLzE65"
