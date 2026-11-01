"""Run the project checks before Claude finishes a turn.

Exit code 2 sends the failure back to Claude so it fixes it first.
"""

import json
import os
import subprocess
import sys

CHECKS = [
    ("ruff", ["ruff", "check", "."]),
    ("mypy", ["mypy"]),
    ("import-linter", ["lint-imports"]),
    ("unit tests", ["pytest", "tests/unit", "-q", "--no-cov"]),
]

# pytest exits with 5 when it collects no tests, which is fine until the first tests exist.
NO_TESTS_COLLECTED = 5


def run(args: list[str], project: str) -> subprocess.CompletedProcess[str]:
    """Run a tool inside the project environment."""
    return subprocess.run(
        ["uv", "run", "--quiet", *args], cwd=project, capture_output=True, text=True
    )


def main() -> int:
    """Return 2 with the failure output if a check fails, else 0."""
    # Already blocked once this turn; let Claude stop instead of looping.
    if json.load(sys.stdin).get("stop_hook_active"):
        return 0

    project = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    changed = subprocess.run(
        ["git", "status", "--porcelain", "--", "*.py", "pyproject.toml"],
        cwd=project,
        capture_output=True,
        text=True,
    ).stdout
    if not changed.strip():
        return 0

    for name, args in CHECKS:
        result = run(args, project)
        ok = result.returncode == 0 or (
            name == "unit tests" and result.returncode == NO_TESTS_COLLECTED
        )
        if not ok:
            output = (result.stdout + result.stderr).strip().splitlines()[-40:]
            print(f"{name} failed. Fix it before finishing:", *output, sep="\n", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
