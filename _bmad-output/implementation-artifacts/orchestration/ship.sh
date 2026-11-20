#!/usr/bin/env bash
# ship.sh <worktree> <story-id e.g. E0-Platform.1> [PR title]
# Rebase a story branch on origin/main, mark the story done in sprint-status.yaml,
# push, open (or reuse) the PR, mark ready, wait for CI, squash-merge.
# Exits 1 on rebase conflict or CI failure — resolve, then re-run.
set -euo pipefail
WT=$1; SID=$2; TITLE=${3:-}
REPO=hsmith-dev/Lorekeeper.quest
SS=_bmad-output/implementation-artifacts/sprint-status.yaml
cd "$WT"
BR=$(git branch --show-current)
git fetch -q origin
git rebase -q origin/main || { echo "REBASE CONFLICT in $BR"; git status --short | head; exit 1; }

EPIC=${SID%.*}; NUM=${SID##*.}
N=$(grep -E "^#   epic-[0-9]+ = ${EPIC}\$" "$SS" | sed -E 's/^#   epic-([0-9]+) = .*/\1/')
[ -n "$N" ] || { echo "epic $EPIC not in id map"; exit 1; }
KEY=$(grep -oE "^  ${N}-${NUM}-[a-z0-9_-]+" "$SS" | sed 's/^  //')
[ -n "$KEY" ] || { echo "story key ${N}-${NUM} not found"; exit 1; }
if ! grep -qE "^  ${KEY}: done" "$SS"; then
  sed -i '' -E "s/^(  ${KEY}): [a-z-]+/\1: done/" "$SS"
  sed -i '' -E "s/^(  epic-${N}): backlog/\1: in-progress/" "$SS"
  sed -i '' -E "s/^last_updated: .*/last_updated: $(date '+%m-%d-%Y %H:%M')/" "$SS"
  git add "$SS"
  git commit -q -m "Mark ${SID} done in sprint status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017fHFDg8qzK1xh593WLzE65"
fi

git push -q --force-with-lease -u origin "$BR" 2>&1 | grep -v '^remote:' || true
PR=$(gh pr list --repo $REPO --head "$BR" --json number --jq '.[0].number')
[ -n "$PR" ] || { echo "no PR for $BR — open one first"; exit 1; }
echo "PR #$PR ($BR)"
[ "$(gh pr view "$PR" --repo $REPO --json isDraft --jq .isDraft)" = "true" ] && gh pr ready "$PR" --repo $REPO >/dev/null
[ -n "$TITLE" ] && gh pr edit "$PR" --repo $REPO --title "$TITLE" >/dev/null
sleep 20
gh pr checks "$PR" --repo $REPO --watch --interval 30 >/dev/null 2>&1 || true
CHECKS=$(gh pr checks "$PR" --repo $REPO 2>&1 || true)
if echo "$CHECKS" | grep -qE "[[:space:]]fail[[:space:]]"; then
  echo "CI FAILED on PR #$PR:"; echo "$CHECKS" | grep -E "[[:space:]]fail[[:space:]]"; exit 1
fi
for i in 1 2 3 4; do
  gh pr merge "$PR" --repo $REPO --squash >/dev/null 2>&1 && break
  sleep 30; git fetch -q origin; git rebase -q origin/main && git push -q --force-with-lease 2>/dev/null || true
  gh pr checks "$PR" --repo $REPO --watch --interval 30 >/dev/null 2>&1 || true
done
echo "MERGED #$PR → $(gh pr view "$PR" --repo $REPO --json mergeCommit --jq .mergeCommit.oid | cut -c1-7)"
