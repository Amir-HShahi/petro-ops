"""Block edits to released prompt versions and to files Claude must never touch by hand."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

RELEASED_PROMPT = re.compile(r"^prompts/.+/v\d+\.md$")


def blocked_reason(rel: PurePosixPath, project: str) -> str | None:
    """Return why Claude may not write this path, or None if it may."""
    name, top = rel.name, rel.parts[0] if rel.parts else ""

    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return f"Don't edit {rel}. Environment files hold secrets and are managed by the user."
    if top == "models" and str(rel) != "models/manifest.yaml":
        return "Don't write to models/. Model weights are managed outside git (DVC/LFS)."
    if top == "data":
        return "Don't write to data/. It holds real organizational data."
    if str(rel) == "uv.lock":
        return "Don't edit uv.lock by hand. Use 'uv add' or 'uv remove'."

    # A prompt version already in git is released and must not change.
    if RELEASED_PROMPT.match(str(rel)):
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", str(rel)],
            cwd=project,
            capture_output=True,
        )
        if tracked.returncode == 0:
            return (
                f"{rel} is a released prompt version. "
                "Create the next version instead (use the add-prompt-version skill)."
            )
    return None


def main() -> int:
    """Return 2 if the target file is protected, else 0."""
    file = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
    if not file:
        return 0

    project = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    try:
        rel = Path(file).resolve().relative_to(Path(project).resolve())
    except ValueError:
        return 0  # outside the project

    reason = blocked_reason(PurePosixPath(rel.as_posix()), project)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
