---
paths:
  - "**/*.py"
---
# Raising and catching errors

- Raise the project's own errors, defined as described in `python-error-classes.md`. Don't raise `Exception`, `ValueError` or `RuntimeError` for business or infrastructure failures.
- Adapters catch library errors and re-raise them as project errors with `raise ... from e`, so the original cause is kept and library types don't leak out.
- Catch errors only where you can do something useful: at the edge (`interface/`) to build the response, or where a real recovery exists, such as a retry or fallback.
- Inner layers let errors pass through. Don't catch an error just to log it and raise it again.
- Never use a bare `except:` or `except Exception: pass`.
- Don't return `None` or `False` to mean "it failed". Raise an error.
- At the edge, turn errors into the response format in `docs/errors.md`. Never send stack traces or file paths to clients; they go to the logs under the same `request_id`.
