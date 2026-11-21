---
name: open-issue
description: Open an agent-ready issue labelled `groomed` (your approval) and marked as AI-generated, after you approve the draft.
disable-model-invocation: true
argument-hint: "[what the issue is about]"
---

Open one issue that is **groomed**: someone could pick it up and build it without asking a question. The `groomed` label records the user's approval, and pipelines build issues that carry it, so the issue is posted only after the user approves the exact draft in step 3. Run every step in the current repo with `gh`.

## 1. Substance

Take the subject from the argument, or from the conversation. Collect the following, reading the code where you need to:

- **Problem**: what is wrong or missing, and who it affects.
- **Evidence**: `file:line` pointers, error text, steps to reproduce. Check each one against the current code.
- **Acceptance criteria**: checkable outcomes. "Scanning a duplicate SN shows an inline error" is checkable; "improve validation" is not.
- **Scope**: the project directory it lives in (`aed`, `kawana`, …), and anything explicitly out of scope.

If an acceptance criterion depends on a decision only the user can make, ask before going on.

Done when every acceptance criterion is checkable and every pointer exists in the code.

## 2. Duplicates

Search for 2–3 key terms with `gh issue list --state all --search "<terms>" --limit 10`. If an issue already covers this subject, show it to the user and ask: comment on that one, or open a new one?

Done when you've ruled out a duplicate, or the user has decided.

## 3. Approval

Draft the title and body:

- **Title**: `<scope>: <imperative summary>`, under 70 characters.
- **Body**: this exact frame.

```markdown
> 🤖 **AI-generated** · Claude Code

## Problem
<what and who it affects>

## Evidence
- `<file:line>` — <what it shows>

## Acceptance criteria
- [ ] <checkable outcome>

## Out of scope
- <item>   ← drop the section if nothing is out of scope

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Show the user the title, the label `groomed`, and the full body, verbatim. Then ask: post it, or what to change? Apply each change, and show the whole draft again.

Done when the user approves this exact draft.

## 4. Post

1. Run `gh label list --search groomed`. If there is no exact `groomed` label, create it with `gh label create groomed --color 0E8A16 --description "Approved: agent-ready, with acceptance criteria"`.
2. Create the issue with the approved draft:

```bash
gh issue create --title "<title>" --label groomed --body "$(cat <<'EOF'
<approved body>
EOF
)"
```

If the `require-ai-marker` hook blocks the call, fix the header and footer lines and run it again.

Done when `gh issue view <n> --json url,labels` shows `groomed` among its labels. Reply with the issue URL.
