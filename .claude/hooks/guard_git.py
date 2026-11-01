"""Block push and PR commands, including forms the settings deny list misses.

For example `git -C dir push` or `git add . && git push`.
"""

import json
import re
import sys

PUSH = re.compile(r"(^|[;&|(`\s])git(\s+-[^;&|]*)?\s+push\b")
PULL_REQUEST = re.compile(r"\bgh\s+pr\s+(create|merge|edit|ready|close|reopen)\b")


def main() -> int:
    """Return 2 if the command pushes or changes a pull request, else 0."""
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")

    if PUSH.search(command):
        print(
            "Pushing is not allowed. Tell the user the branch is ready "
            "and that they push it themselves.",
            file=sys.stderr,
        )
        return 2
    if PULL_REQUEST.search(command):
        print(
            "Opening or changing pull requests is not allowed. Tell the user to do it themselves.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
