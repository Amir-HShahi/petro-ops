---
name: add-prompt-version
description: Add a new version of a prompt template (or a brand-new prompt) under prompts/, update the registry and its snapshot test. Use whenever a prompt's wording, variables or target model changes.
paths:
  - "prompts/**"
---

Prompts live in `prompts/<task>/v<N>.md`, and `prompts/registry.yaml` says which version each task uses.

1. Never edit an existing `v<N>.md`. Copy the latest version to `v<N+1>.md` and change the copy. For a new task, start at `v1.md`.
2. Fill in the front matter:

   ```yaml
   ---
   id: <task>
   version: <N+1>
   model: <local model it was tested with>
   variables: [<every {placeholder} used in the text>]
   changelog: <one line: what changed and why>
   ---
   ```

3. Check that every `{placeholder}` in the text is listed in `variables`, and nothing extra is listed.
4. Add or update the snapshot test in `tests/unit/model_prompt/` so the rendered output of the new version is pinned.
5. Leave `registry.yaml` on the old version unless the user says to switch. Switching should wait for the RAG eval results.
6. Tell the user which version was added and that it needs an eval run before it goes live.
