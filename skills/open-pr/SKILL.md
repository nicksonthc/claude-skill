---
name: open-pr
description: Open (or bring up to date) a PR for the current branch, labelled `agent`, marked as AI-generated, with before/after screenshots when the UI changed, after you approve the draft.
disable-model-invocation: true
argument-hint: "[base-branch]"
---

Open one PR from the current branch with the `agent` label, so anyone scanning the PR list can see an agent opened it. Run every step in the current repo with `gh`. Steps 1–4 stay local and read-only on GitHub. Nothing is pushed or posted until the user approves the draft in step 4.

## 1. Branch

- If you're on the default branch (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`), create a local branch named `<type>/<kebab-slug>`, using the type from step 3.
- If `git status` shows uncommitted changes, ask whether they belong in this PR. Commit only the ones the user confirms.

Done when every change meant for the PR is committed on a non-default branch.

## 2. Existing PR

Run `gh pr view --json number,url,labels,body`. If a PR already exists for this branch, ask two things: add the `agent` label, and redraft its body to this skill's frame (screenshots included when the UI changed)?

- Label only: run `gh pr edit <n> --add-label agent`, report its URL, and stop.
- Redraft: continue with steps 3–5 against the existing PR. Step 3 keeps whatever the current body says that the frame has room for. Step 5 runs `gh pr edit` instead of `gh pr create`.

Done when you know there is no open PR for this branch, or you know what to do with the one that exists.

## 3. Draft

Base: the first argument if given, else the default branch. Read the full change with `git log --oneline <base>..HEAD` and `git diff <base>...HEAD`, not just the last commit.

- **Title**: a conventional commit, `<type>(<scope>): <summary>`, under 70 characters. The scope is the project directory the change lives in (`aed`, `kawana`, …). Copy the style of `git log` on the base branch.
- **Body**: this exact frame. Each Summary bullet is one change and why it was made. The Test plan lists what you actually ran, as checked items, and what is still unchecked, as open items.
- **Screenshots**: when the diff changes what a page shows (components, templates, styles, copy on screen), read [`SCREENSHOTS.md`](SCREENSHOTS.md). It covers capturing a before/after pair per changed surface and the section that holds them. Leave the section out when nothing visible changed.

```markdown
> 🤖 **AI-generated** · Claude Code

## Summary
- <change — why>

## Screenshots   ← only when the UI changed; see SCREENSHOTS.md
| | Before | After |
|---|---|---|
| **<surface>**: <state> | ![before](<url>) | ![after](<url>) |

## Test plan
- [x] <what you ran and saw pass>
- [ ] <what still needs checking>

Closes #<n>   ← only if the branch or conversation names an issue

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Done when every commit since the base is covered by a Summary bullet, and every changed surface by a screenshot pair.

## 4. Approval

Show the user the head → base branches, the title, the label `agent`, and the full body, verbatim. Write the screenshot cells as local file paths so the user can open each image. Then ask: post it, or what to change? Apply each change, and show the whole draft again.

Done when the user approves this exact draft.

## 5. Post

1. Run `gh label list --search agent`. If there is no exact `agent` label, create it with `gh label create agent --color 5319E7 --description "Opened by an AI agent"`.
2. Push with `git push -u origin HEAD`.
3. If the draft has screenshots, upload them (`SCREENSHOTS.md` §3) and swap each local path for its URL.
4. Create the PR with the approved draft. For an existing PR, use `gh pr edit <n> --add-label agent --title … --body …` instead:

```bash
gh pr create --base <base> --title "<title>" --label agent --body "$(cat <<'EOF'
<approved body>
EOF
)"
```

If the `require-ai-marker` hook blocks the call, fix the header and footer lines and run it again.

Done when `gh pr view --json url,labels` shows the PR with `agent` among its labels, and every screenshot in it loads. Reply with the PR URL.
