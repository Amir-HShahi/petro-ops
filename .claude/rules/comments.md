# Comments

These apply to every file type. Language-specific rules add to them.

- Comment why, not what. If the code already says it, don't repeat it.
- Prefer clearer names or a small function over a comment that explains confusing code.
- No banner or section-divider comments like `# ---------- ruff ----------`.
- No commented-out code. Delete it; git keeps the history.
- No comments about the change itself ("added X", "fixed bug", "new"). That belongs in the commit message.
- A `TODO` needs a reason or an issue number: `# TODO(#42): handle scanned PDFs`.
- Write in short, plain English sentences.
- Keep comments in sync: when you change the code, update or delete the comment next to it.
