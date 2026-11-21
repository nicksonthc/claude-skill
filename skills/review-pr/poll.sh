#!/usr/bin/env bash
# Poll GitHub for open PRs that request my review or mention me, and run `/review-pr --auto`
# once per new head commit. Started by launchd (see review-pr.plist).
set -uo pipefail
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
# Only these orgs/users (space-separated): PR text is untrusted, so stay inside repos whose authors you know.
# Set REVIEW_PR_OWNERS, or list them in ~/.config/review-pr/owners (kept outside the skill repo).
OWNERS="${REVIEW_PR_OWNERS:-$(cat "$HOME/.config/review-pr/owners" 2>/dev/null)}"
WORK="$HOME/.cache/review-pr"
AI_MARK='🤖 **AI-generated**'
mkdir -p "$WORK/repos" "$WORK/wt"
touch "$WORK/done"
exec >>"$WORK/poll.log" 2>&1
log() { echo "$(date '+%F %T') $*"; }
[ -n "${OWNERS// /}" ] || { log "no owners configured: set REVIEW_PR_OWNERS or ~/.config/review-pr/owners"; exit 1; }

# One run at a time; a lock older than 2h is from a crashed run.
if ! mkdir "$WORK/lock" 2>/dev/null; then
  [ -n "$(find "$WORK/lock" -maxdepth 0 -mmin +120)" ] || exit 0
  rm -rf "$WORK/lock"; mkdir "$WORK/lock"
fi
trap 'rm -rf "$WORK/lock"' EXIT

me=$(gh api user -q .login) || { log "GitHub unreachable or gh not authenticated"; exit 1; }
owner_flags=(); for o in $OWNERS; do owner_flags+=(--owner "$o"); done

# Why to skip a PR, or nothing: anything of mine is on it already, by hand or by the agent.
# Covers reviews, conversation comments and line comments.
skip_reason() {  # <owner/repo> <n>
  local posts
  posts=$(for ep in "repos/$1/pulls/$2/reviews" "repos/$1/issues/$2/comments" "repos/$1/pulls/$2/comments"; do
    gh api --paginate "$ep" --jq ".[] | select(.user.login == \"$me\")
      | if (.body // \"\" | contains(\"$AI_MARK\")) then \"agent\" else \"human\" end"
  done)
  if grep -qx human <<<"$posts"; then echo "already reviewed/commented by $me"
  elif grep -qx agent <<<"$posts"; then echo "agent already reviewed it"
  fi
}

urls=$( {
  gh search prs --review-requested=@me --state=open --draft=false "${owner_flags[@]}" --json url --jq '.[].url'
  gh search prs --mentions=@me --state=open --draft=false "${owner_flags[@]}" --json url --jq '.[].url'
} | sort -u )

for url in $urls; do
  read -r author sha < <(gh pr view "$url" --json author,headRefOid --jq '"\(.author.login) \(.headRefOid)"') || continue
  [ "$author" = "$me" ] && continue
  key="$url@$sha"
  grep -qxF "$key" "$WORK/done" && continue

  # url = https://github.com/<owner>/<repo>/pull/<n>
  IFS=/ read -r _ _ _ owner repo _ n <<<"$url"

  reason=$(skip_reason "$owner/$repo" "$n")
  if [ -n "$reason" ]; then
    log "skip $url: $reason"
    echo "$key" >>"$WORK/done"
    continue
  fi

  clone="$WORK/repos/$owner/$repo"
  wt="$WORK/wt/$owner-$repo-$n-${sha:0:7}"
  log "reviewing $key"
  [ -d "$clone/.git" ] || gh repo clone "$owner/$repo" "$clone" -- --filter=blob:none --quiet || continue
  git -C "$clone" fetch --quiet origin "pull/$n/head" || continue
  git -C "$clone" worktree add --quiet --detach "$wt" "$sha" || continue

  # dontAsk denies every call not listed here (the global `auto` mode would approve them).
  # Read-only gh/git, file writes only under .review/, and the one GitHub write: post-review.sh.
  # The skill is symlinked into ~/.claude/skills, and the agent may call the wrapper by either
  # path; permission rules match the literal string, so allow both.
  (cd "$wt" && claude -p "/review-pr $url --auto" --permission-mode dontAsk \
      --allowedTools "Read" "Grep" "Glob" "Agent" "Edit(.review/**)" \
        "Bash(gh pr view:*)" "Bash(gh pr diff:*)" "Bash(gh issue view:*)" "Bash(gh auth status:*)" \
        "Bash(git log:*)" "Bash(git show:*)" "Bash(git diff:*)" "Bash(git rev-parse:*)" \
        "Bash($SKILL_DIR/post-review.sh:*)" "Bash($HOME/.claude/skills/review-pr/post-review.sh:*)" \
      --max-turns 60)
  # claude exits 0 even when a tool call was denied, so check GitHub for the posted review.
  if [ -n "$(skip_reason "$owner/$repo" "$n")" ]; then
    log "posted $key"
    echo "$key" >>"$WORK/done"
  else
    if [ -f "$wt/.review/body.md" ]; then
      mkdir -p "$WORK/unposted"
      cp "$wt/.review/body.md" "$WORK/unposted/$owner-$repo-$n-${sha:0:7}.md"
    fi
    # Each attempt is a full agent run; give up on this commit after 3.
    if [ "$(grep -cF "FAILED $key" "$WORK/poll.log")" -ge 2 ]; then
      log "FAILED $key: no review on the PR, giving up on this commit after 3 attempts"
      echo "$key" >>"$WORK/done"
    else
      log "FAILED $key: no review on the PR (will retry next poll)"
    fi
  fi
  git -C "$clone" worktree remove --force "$wt"
done
