# Environment variables

- `.env` holds real values and is never committed. `.env.example` is committed and lists every variable `.env` has.
- Read variables only through `Settings` in `src/offline_rag/settings.py`. Never use `os.environ` or `os.getenv` elsewhere; ruff blocks it.
- Every `Settings` field has a matching line in `.env.example`; a unit test checks this.
- Keep them in sync. When code adds, renames or removes a variable, change `.env.example` in the same change, and tell the user to make the same change in their `.env`.
- You can't read or edit `.env`. Never ask the user to paste its contents.
- `.env.example` holds safe placeholders or harmless defaults, never real secrets, paths from a personal machine or real data.
- Give each variable a short comment above it saying what it's for, and its unit or allowed values when it has them.
- Group related variables together, in the same order as in the code that reads them.
- Name variables in upper snake case with the unit in the name when there is one: `CHUNK_SIZE_TOKENS`, `LLM_TIMEOUT_S`.
