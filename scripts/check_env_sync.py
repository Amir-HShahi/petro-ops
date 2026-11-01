"""Check that the local .env and .env.example define the same variable names.

Run by pre-commit. Values are never read or printed, only names. Skips when
there is no .env, such as in CI or a fresh clone.
"""

import sys
from pathlib import Path


def variable_names(path: Path) -> set[str]:
    """Return the variable names defined in a dotenv file."""
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line.split("=", 1)[0].strip() for line in lines if line and not line.startswith("#")}


def main() -> int:
    """Return 1 and list the differences if the two files are out of sync, else 0."""
    env, example = Path(".env"), Path(".env.example")
    if not env.is_file():
        return 0

    missing_in_example = variable_names(env) - variable_names(example)
    missing_in_env = variable_names(example) - variable_names(env)
    if not missing_in_example and not missing_in_env:
        return 0

    if missing_in_example:
        print("In .env but not in .env.example:", *sorted(missing_in_example), sep="\n  ")
    if missing_in_env:
        print("In .env.example but not in .env:", *sorted(missing_in_env), sep="\n  ")
    return 1


if __name__ == "__main__":
    sys.exit(main())
