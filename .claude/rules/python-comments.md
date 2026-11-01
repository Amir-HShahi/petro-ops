---
paths:
  - "**/*.py"
---
# Python comments and docstrings

- Use Google-style docstrings.
- Docstrings are required on public modules, classes, functions and methods, and on every port `Protocol` and its methods.
- Docstrings are optional on private helpers (`_name`) and not needed on tests; a good test name is enough.
- Start with a one-line summary in the imperative mood ("Return the active prompt version."). Add more only if it helps.
- Don't repeat types in docstrings; the type hints already show them. Describe meaning, units and limits instead.
- Document `Raises:` for domain errors a caller is expected to handle.
- In domain code, say which business rule or invariant a check enforces, and use the spec's terms (`Node`, `KnowledgeItem`, `Issue`, ...).
- Inline `#` comments only for non-obvious reasons: a workaround, a model quirk, a performance choice, a spec reference.
