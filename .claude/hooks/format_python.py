"""Format the Python file Claude just edited.

Never blocks: anything ruff can't fix is left for the Stop check.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Format the edited file if it is Python."""
    file = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
    if not file.endswith(".py") or not Path(file).is_file():
        return

    project = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    for args in (["format", file], ["check", "--fix", "--quiet", file]):
        subprocess.run(["uv", "run", "--quiet", "ruff", *args], cwd=project, capture_output=True)


if __name__ == "__main__":
    main()
