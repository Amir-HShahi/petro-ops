---
name: commit
description: Create a git commit for the current changes following CONTRIBUTING.md. Use only when the user explicitly asks to commit.
---

The branching and commit conventions are in `CONTRIBUTING.md`. Follow them.

1. Run `git status` and `git diff` (staged and unstaged) to see what will be committed.
2. Check the branch:
   - If on `master`, don't commit there. Suggest a branch name from `CONTRIBUTING.md`, create it with `git switch -c <name>` once the user agrees, then continue.
   - If the changes don't match the branch's purpose, say so and ask before committing.
3. Stage only files that belong to this change. Never stage secrets, `.env`, model weights or files under `data/`. If unrelated changes are mixed in, ask the user whether to split them.
4. Run `uv run ruff check . && uv run mypy && uv run lint-imports && uv run pytest tests/unit`. If something fails, report it and stop; don't commit around a failure.
5. Write a Conventional Commit message: type, optional scope (the bounded context), short imperative summary, and a body only when the reason isn't obvious.
6. Commit. If the pre-commit hooks change files, re-stage them and commit again. Never use `--no-verify`.
7. Show the commit with `git log -1 --stat`.
8. Never push. Tell the user the branch is ready and that they push it themselves.
