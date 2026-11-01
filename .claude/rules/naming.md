# Naming

These apply to every file type. Language-specific rules add to them.

- Use the spec's domain terms exactly: `Layer`, `Node`, `KnowledgeItem`, `Issue`, `SubIssue`, `Executor`, `TransferPackage`, `RFP`, `Proposal`, `Rubric`, `JudgeScore`. No synonyms, e.g. not `Document` for `KnowledgeItem` or `Task` for `Issue`.
- If a new domain concept is needed, ask the user before naming it.
- One concept, one name, everywhere: code, tests, prompts, database tables and APIs.
- Avoid vague names: `data`, `info`, `manager`, `helper`, `util`, `handle`, `process`, `obj`, `tmp`.
- Abbreviate only well-known terms (`id`, `llm`, `rag`, `rfp`, `pdf`, `url`). Spell out everything else.
- Booleans read as a yes/no question: `is_active`, `has_parent`, `can_transfer`.
- Put the unit in the name when a number has one: `timeout_s`, `chunk_size_tokens`, `max_file_mb`.
- Branch names and commit messages follow `CONTRIBUTING.md`.
