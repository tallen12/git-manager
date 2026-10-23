---
name: git-workflow
description: Branch, worktree and merge workflow for this repository, built so several agents can work at once. Use when starting any new piece of work, creating a branch or worktree, finishing a task and merging it, or pushing.
---

# Git workflow

Work is organized by feature. Each feature has one long-lived **feature branch**. Every
task within a feature gets its own **work branch** in its own **worktree**, so several
agents can work at the same time without touching each other's checkout. When a task is
done, it lands on the feature branch as a single squashed commit. Write every commit
message with the `conventional-commits` skill.

```text
main
 └── feat/<feature>                      feature branch (one squashed commit per task)
      ├── work/<feature>/<task>          work branch, own worktree, local only
      └── work/<feature>/<other-task>    another agent, another worktree
```

## Names and locations

- **Feature branch:** `<type>/<feature>`, using a Conventional Commits type and a short
  kebab-case slug, for example `feat/branch-stacks` or `fix/detached-head`.
- **Work branch:** `work/<feature>/<task>`, for example `work/branch-stacks/restack-cli`.
  The separate `work/` prefix is required: git cannot hold both `feat/x` and `feat/x/task`.
- **Worktree:** `.worktrees/<feature>--<task>` inside the main checkout, for example
  `.worktrees/branch-stacks--restack-cli`. `.worktrees/` is listed in `.gitignore` and
  `.dockerignore`, so git, `ruff`, `ty` and Docker builds skip it, and `pytest` only
  collects from `tests/`. Never create worktrees outside the repository.

## 1. Start a feature

Skip this if the feature branch already exists (`git branch --list '<type>/<feature>'`).

```bash
git switch main
git switch -c feat/<feature>
```

The main checkout normally stays on the feature branch. Only one worktree can have a given
branch checked out, so this is where squashed commits land (step 4).

## 2. Start a task

From the main checkout, branch from the current tip of the feature branch into a new
worktree, then set it up:

```bash
git worktree add -b work/<feature>/<task> .worktrees/<feature>--<task> feat/<feature>
cd .worktrees/<feature>--<task>
just setup
```

Do all of the task's work inside that worktree. Never edit files in another agent's
worktree or in the main checkout while a task is in progress.

## 3. Do the work

- Commit on the work branch as you go. Small, focused commits are fine here; they are
  squashed later.
- Run `just check` before the final commit on the branch.
- **Never push a work branch.** Do not run `git push` with a `work/` branch, do not set an
  upstream for it and do not open a pull request from it. Work branches exist only locally.

## 4. Land the task on the feature branch

1. Bring the work branch up to date, since other agents may have landed tasks meanwhile. In
   the task worktree:

   ```bash
   git rebase feat/<feature>
   just check
   ```

   Resolve any conflicts in the task worktree, never on the feature branch.

2. In the main checkout (on `feat/<feature>`, with a clean `git status`), squash the work
   branch into one commit:

   ```bash
   git merge --squash work/<feature>/<task>
   git commit
   ```

   The commit message summarizes the whole task in Conventional Commits form: a subject
   for the outcome and a body listing the notable changes and why. Do not paste the work
   branch's individual commit messages.

3. Right after the squash commit, before anything else lands, confirm nothing was lost,
   then clean up. The diff must be empty before deleting:

   ```bash
   git diff feat/<feature> work/<feature>/<task>
   git worktree remove .worktrees/<feature>--<task>
   git branch -D work/<feature>/<task>
   ```

   `-D` is needed because a squash merge does not mark the branch as merged.

If two agents finish at once, land one task first; the other rebases (step 4.1) and lands
after it.

## 5. Finish the feature

Push the feature branch and open a pull request into `main` only when the user asks. Write
the title and description with the `pull-requests` skill:

```bash
git push -u origin feat/<feature>
```

The feature branch is the only branch that goes to GitHub.

## Rules

- Follow the commit rules in `AGENTS.md`: commit or push only when the user asks. Asking
  for work done under this workflow covers local commits on its work branch and the squash
  commit on the feature branch. It never covers a push.
- Do not commit directly on `main`, and do not do task work directly on a feature branch;
  the feature branch only receives squashed commits.
- Never force-push, rewrite the feature branch's history or delete a branch with unlanded
  work without the user's approval.
- If a worktree or work branch from an earlier task is still present, ask before removing
  it; another agent may be using it.
