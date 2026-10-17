#!/usr/bin/env bash
# PreToolUse hook: block GitHub writes (PR/issue bodies, comments, reviews) that lack
# the AI marker, so anything Claude posts is distinguishable from human-written text.
# Covers `gh pr|issue ...`, `gh api` on issue/PR endpoints, and GitHub MCP tools.
# Exit 2 blocks the call and hands stderr back to Claude; anything else lets it run.
# The same file is installed globally (~/.claude/hooks) and per repo (.claude/hooks).

HEADER='🤖 **AI-generated**'
FOOTER='Generated with [Claude Code]'

# The global copy defers to a repo copy, so the check runs once per call.
proj="${CLAUDE_PROJECT_DIR:-}/.claude/hooks/require-ai-marker.sh"
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -f "$proj" ] && ! [ "$proj" -ef "$0" ]; then
  exit 0
fi

input=$(cat)
tool=$(jq -r '.tool_name // empty' <<<"$input" 2>/dev/null)

if [ "$tool" = Bash ]; then
  cmd=$(jq -r '.tool_input.command // empty' <<<"$input")
  cd "$(jq -r '.cwd // "."' <<<"$input")" 2>/dev/null || true

  # `gh` at a command position; right after a quote it's text (grep "gh pr comment"), not a call
  at_cmd="(^|[^[:alnum:]_./\"'-])"
  cli_write="${at_cmd}gh[[:space:]]+(pr|issue)[[:space:]]+(create|comment|review|edit|close|reopen)([[:space:]]|\$)"
  cli_create='gh[[:space:]]+(pr|issue)[[:space:]]+create([[:space:]]|$)'
  cli_body='(^|[[:space:]])(--body|--body-file|-b|-F|--comment|-c)([[:space:]=]|$)'
  api_write="${at_cmd}gh[[:space:]]+api[[:space:]].*(issues|pulls|comments|reviews)"
  api_body='(^|[[:space:]])((-f|-F|--field|--raw-field)[[:space:]]+body=|--input[[:space:]])'

  needs=0
  if grep -Eq -- "$cli_write" <<<"$cmd"; then
    # create always needs a marked body (--fill would post commit messages unmarked)
    grep -Eq -- "$cli_create" <<<"$cmd" && needs=1
    grep -Eq -- "$cli_body" <<<"$cmd" && needs=1
  fi
  if grep -Eq -- "$api_write" <<<"$cmd" && grep -Eq -- "$api_body" <<<"$cmd"; then
    needs=1
  fi
  [ "$needs" = 1 ] || exit 0

  # Inline and heredoc bodies are in the command text; file bodies are read here.
  text="$cmd"
  while IFS= read -r m; do
    p=$(sed -E 's/^(--body-file|--input|-F)[[:space:]=]+//; s/^body=@//' <<<"$m" | tr -d "\"'")
    [ -f "$p" ] && text+=$'\n'"$(cat "$p")"
  done < <(grep -oE -- '(--body-file|--input|-F)[[:space:]=]+[^[:space:]]+' <<<"$cmd")
elif [[ "$tool" == mcp__* ]]; then
  text=$(jq -r '[.tool_input.body, .tool_input.comment] | map(select(type == "string")) | join("\n")' <<<"$input")
  [ -n "$text" ] || exit 0
else
  exit 0
fi

missing=()
[[ "$text" == *"$HEADER"* ]] || missing+=("header")
[[ "$text" == *"$FOOTER"* ]] || missing+=("footer")
[ ${#missing[@]} -eq 0 ] && exit 0

cat >&2 <<EOF
Blocked: this GitHub write is missing the AI marker (${missing[*]}).
Everything Claude posts to GitHub (PR/issue bodies, comments, reviews) must start with

> 🤖 **AI-generated** · Claude Code

and end with

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Add both lines to the body and run it again. Do not work around this check.
EOF
exit 2
