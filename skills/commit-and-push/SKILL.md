---
name: commit-and-push
description: >
  Git commit and push workflow with strong commit message quality.
  Use when user asks to review staged changes, commit, push, or both.
---

Follow this every time:

## Goal

Ship clean commit history with accurate scope, tested changes, and clear commit messages.

## Workflow

1. Inspect repo state.
Run `git status --short --branch`.
If staged changes exist, review staged diff first with `git diff --cached`.
If no staged changes, review unstaged diff and stage only intended files.

2. Validate change scope.
Check no unrelated files included.
If unrelated edits present, do not stage them.

3. Verify behavior.
Run focused tests for touched code paths when possible.
If tests cannot run, state that explicitly in final report.

4. Stage explicit files.
Use path-based `git add <file...>`.
Avoid blanket adds unless user asked for all changes.

5. Write commit message.
Subject line format: `<type>(<scope>): <what changed>`
Keep subject under 72 chars.
Use imperative voice.
Body lines explain:
- what changed
- why it changed
- key risks or compatibility notes

6. Commit.
Run `git commit` with subject plus body bullets.
Do not amend unless user explicitly asks.

7. Push.
Push current branch to remote with explicit branch name when known.
Example: `git push origin main`.

8. Report back.
Provide quick summary first, then details:
- commit hash
- branch pushed
- tests run and result
- files included

## Guardrails

- Never use destructive history rewrite commands unless user requests.
- Never revert unrelated user changes.
- If no commit happened, clearly say why and what blocked it.
