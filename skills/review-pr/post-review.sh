#!/usr/bin/env bash
# The only GitHub write /review-pr makes: post one COMMENT review (never approve / request changes).
# The auto run gets this script instead of `gh api`, so a hostile PR can't steer it into other writes.
# Usage: post-review.sh <owner/repo> <pr-number> <head-sha> <body-file>
set -euo pipefail
die() { echo "post-review: $*" >&2; exit 2; }

[ $# -eq 4 ] || die "usage: post-review.sh <owner/repo> <pr-number> <head-sha> <body-file>"
repo=$1 n=$2 sha=$3 body=$4
[[ $repo =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "bad repo: $repo"
[[ $n =~ ^[0-9]+$ ]] || die "bad PR number: $n"
[[ $sha =~ ^[0-9a-f]{40}$ ]] || die "bad head SHA: $sha"
[ -f "$body" ] || die "no body file: $body"
grep -qF '🤖 **AI-generated**' "$body" || die "body is missing the AI header"
grep -qF 'Generated with [Claude Code]' "$body" || die "body is missing the AI footer"
grep -qF 'Reviewed by Agent' "$body" || die "body is missing the 'Reviewed by Agent' line"

jq -n --arg sha "$sha" --rawfile body "$body" '{commit_id: $sha, event: "COMMENT", body: $body}' |
  gh api "repos/$repo/pulls/$n/reviews" --method POST --input - --jq .html_url
