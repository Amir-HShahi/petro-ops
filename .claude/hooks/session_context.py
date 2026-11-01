"""Print the repo state at session start. Claude Code adds stdout to Claude's context."""

import os
import subprocess


def git(*args: str) -> str:
    """Return the output of a git command run in the project."""
    project = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    return subprocess.run(["git", *args], cwd=project, capture_output=True, text=True).stdout


def main() -> None:
    """Print the branch, uncommitted changes and recent commits."""
    changes = git("status", "--short").splitlines()[:30]
    print(f"Branch: {git('branch', '--show-current').strip()}")
    print("\nUncommitted changes:", *changes, sep="\n")
    print("\nRecent commits:", git("log", "--oneline", "-3"), sep="\n")


if __name__ == "__main__":
    main()
