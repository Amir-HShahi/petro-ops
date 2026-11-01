---
name: adr
description: Write an Architecture Decision Record in docs/adr/. Use when a significant design choice is made or changed, such as model selection, storage, chunking strategy, context boundaries or an API contract.
---

1. Find the next number in `docs/adr/`. Files are named `NNNN-short-title.md`, starting at `0001`.
2. If the decision replaces an earlier ADR, set the old one's status to `Superseded by NNNN` instead of deleting it.
3. Write the ADR with these sections, short and in plain language:

   ```markdown
   # NNNN. <Title>

   Date: <YYYY-MM-DD>
   Status: Proposed | Accepted | Superseded by NNNN

   ## Context
   The problem and the constraints (offline, hardware, spec requirements).

   ## Decision
   What we chose.

   ## Alternatives
   What else was considered and why it lost. Include eval numbers if there are any.

   ## Consequences
   What gets easier, what gets harder, what we'll need to revisit.
   ```

4. Use `Proposed` unless the user says the decision is final.
5. Mention the ADR number in the related PR description.
