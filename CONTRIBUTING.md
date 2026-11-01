# Contributing

## Branching

We use trunk-based development. `master` is the trunk: it always builds, always passes CI, and is protected.

- Branch off the latest `master` for every change.
- Keep branches short-lived: merge within 1–2 days. Split big work into small PRs and hide unfinished features behind a config flag.
- Rebase on `master` daily to stay current.
- Branches are deleted automatically after merge.

Branch names: `<type>/<short-description>`, lowercase with hyphens.

| Prefix | Use for |
|---|---|
| `feat/` | new behavior, e.g. `feat/knowledge-dedup` |
| `fix/` | bug fixes, e.g. `fix/pdf-table-parsing` |
| `exp/` | model, prompt, chunking or retrieval experiments; most never merge |
| `refactor/` | code changes with no behavior change |
| `test/` | tests only |
| `docs/` | documentation and ADRs |
| `chore/` | tooling, CI, dependencies |

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/). The pre-commit hook checks the message.

```
<type>(<optional scope>): <short summary in imperative mood>

<optional body: why, not what>

<optional footer: BREAKING CHANGE: ..., Closes #12>
```

Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `ci`, `build`. Use the bounded context as the scope when it fits.

```
feat(knowledge): detect duplicate knowledge items by embedding similarity
fix(rag): keep table rows together when chunking PDFs
feat(transfer)!: change transfer package schema to v2
```

`!` or a `BREAKING CHANGE:` footer marks a breaking change.

## Pull requests

1. Open a PR to `master`. Open it as a draft early if you want feedback.
2. Fill in the PR template.
3. Before merging:
   - CI passes
   - 1 approval (code owner where one is set)
   - all review conversations resolved
   - branch is up to date with `master`
4. Changes to prompts, models, chunking or retrieval must include eval results (metric, before, after) in the PR.
5. Squash-merge only. The squash message must be a valid Conventional Commit, since it drives versioning and the changelog.

## Experiments

- Use `exp/` branches.
- Merge only if eval results are equal or better than `master`.
- Record the result, good or bad, in the PR or an ADR before closing the branch.

## Releases

- Versions follow SemVer, starting at `0.x`.
- Releases are automated with release-please. Every merge to `master` updates an open Release PR with the next version and `CHANGELOG.md`, based on the commit types.
- To release, merge the Release PR. That creates the `vX.Y.Z` tag and GitHub Release, and the wheel is built and attached to it.
- If a delivered version needs a fix while `master` has moved on, cut `release/X.Y` from its tag, merge the fix to `master` first, then cherry-pick it onto the release branch and release a patch from there.
