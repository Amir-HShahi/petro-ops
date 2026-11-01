---
paths:
  - "prompts/**"
---
# Prompt template comments

- Never put comments in the template body. Everything in the body is sent to the model.
- Notes about a version go in the front matter `changelog` field.
- Longer reasoning about a prompt change goes in the PR description or an ADR.
- `registry.yaml` may use `#` comments, for example why a version is active or was rolled back.
