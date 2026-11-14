#!/usr/bin/env bash
# Walk through Issue Management step by step (phase 7): start Postgres, create the
# tables, register the case-study Nodes, raise an Issue and a similar one, split it
# into a tree of SubIssues, order them, make one wait for another, show the rules
# refusing bad changes, close the SubIssues, resolve the Issue and print its tree.
# Every run raises new Issues; add --reset to start from no Issues.
# Runs on the bash 3.2 that ships with macOS.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: docker/issue-demo.sh [options]

  --no-docker   Use the Postgres already running at DATABASE_URL instead of
                starting it from docker/docker-compose.yml.
  --reset       Delete every Issue first. Nodes and knowledge stay.
  -h, --help    Show this help.

Asking the LLM for SubIssues (`issue decompose`) needs Ollama and a chunked
KnowledgeItem, so it is not part of this demo; see README.md.
EOF
}

start_docker=true
reset=false
while (($#)); do
  case "$1" in
    --no-docker) start_docker=false; shift ;;
    --reset) reset=true; shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
compose=(docker compose -f docker/docker-compose.yml)
issue_cli=.venv/bin/issue
python=.venv/bin/python
error_file=$(mktemp)
trap 'rm -f "$error_file"' EXIT

step_number=0
step() {
  step_number=$((step_number + 1))
  echo
  echo "== $step_number. $* =="
}

# Print one field of the JSON on stdin; a dotted path such as `sub_issues.0.title`
# walks into objects and lists.
json_field() {
  "$python" -c 'import json, sys
value = json.loads(sys.stdin.read())
for key in sys.argv[1].split("."):
    value = value[int(key)] if isinstance(value, list) else value[key]
print(json.dumps(value) if isinstance(value, (list, dict)) else value)' "$1"
}

# The Problem Details body is the last line on stderr; log lines come before it.
problem_type() {
  tail -n 1 "$error_file" | json_field type
}

# Run an `issue` command that must succeed and print its JSON result.
run_ok() {
  if ! "$issue_cli" "$@" 2>"$error_file"; then
    echo "   FAILED with $(problem_type)" >&2
    cat "$error_file" >&2
    exit 1
  fi
}

# Run an `issue` command the rules must refuse, and check it is refused for the right reason.
expect_refused() {
  local expected=$1
  shift
  if "$issue_cli" "$@" >/dev/null 2>"$error_file"; then
    echo "   ACCEPTED, but it should have been refused with $expected" >&2
    exit 1
  fi
  local code
  code=$(problem_type)
  if [[ $code != "$expected" ]]; then
    echo "   refused with $code, expected $expected" >&2
    cat "$error_file" >&2
    exit 1
  fi
  echo "   refused as expected: $code"
}

# Add a SubIssue and print its new id.
add_sub_issue() {
  run_ok add-sub-issue "$@" | json_field added_sub_issue_id
}

# Keep log lines short in the demo; errors still reach stderr as Problem Details.
export LOG_LEVEL=warning

if $start_docker; then
  step "Start Postgres"
  "${compose[@]}" up -d --wait postgres
fi

step "Create the tables (Alembic migrations) and register the case-study Nodes"
uv run alembic upgrade head
.venv/bin/organization import-nodes >/dev/null
echo "   done"

if $reset; then
  step "Reset: delete every Issue"
  "$python" - <<'EOF'
import psycopg

from offline_rag.settings import Settings

with psycopg.connect(Settings().database_url) as connection:
    deleted = connection.execute("DELETE FROM issue").rowcount
print(f"   deleted {deleted} Issues, with their SubIssues, flags and candidates")
EOF
fi

step "Raise an Issue for Platform SP-12"
raised=$(run_ok raise --node platform_sp12 \
  --title "Riser R-3 splash zone corrosion" \
  --description "Gas export riser R-3 is losing wall in the splash zone, where the coating has failed and cathodic protection does not reach." \
  --domain "asset integrity" --tag riser --tag "splash zone")
issue_id=$(json_field issue_id <<<"$raised")
echo "   issue_id: $issue_id"
echo "   status:   $(json_field status <<<"$raised")"

step "Raise the same problem in other words: it is kept, and flagged (ADR 0012)"
again=$(run_ok raise --node platform_sp12 \
  --title "Splash zone corrosion on riser R-3" \
  --description "Riser R-3 is losing wall in the splash zone because the coating failed.")
echo "   similar_issues: $(json_field similar_issues <<<"$again")"

step "Split the Issue into SubIssues, and the repair option further"
survey=$(add_sub_issue "$issue_id" --title "Rope access UT survey of the splash zone" \
  --description "Measure the remaining wall between EL +5 m and EL +9 m.")
repair=$(add_sub_issue "$issue_id" --title "Permanent repair option" \
  --description "Choose between a clamp-on sleeve and a riser section replacement.")
wrap=$(add_sub_issue "$issue_id" --title "Temporary splash zone wrap" \
  --description "Wrap the splash zone within 6 months, until the repair is in place.")
sleeve=$(add_sub_issue "$issue_id" --parent "$repair" --title "Clamp-on sleeve" \
  --description "Check whether a sleeve can carry the riser loads.")
replacement=$(add_sub_issue "$issue_id" --parent "$repair" --title "Riser section replacement" \
  --description "Estimate the shutdown and cost of replacing the section.")
echo "   five SubIssues added, two of them under the repair option"

step "Order and dependencies (spec §12.3)"
echo " - the temporary wrap is urgent, so it moves to the first place"
run_ok move-sub-issue "$issue_id" "$wrap" --position 1 >/dev/null
echo " - the repair option waits for the UT survey"
run_ok add-dependency "$issue_id" "$repair" --on "$survey" >/dev/null
echo " - the UT survey cannot wait for the repair option in turn"
expect_refused ISSUE_SUB_ISSUE_DEPENDENCY_CYCLE add-dependency "$issue_id" "$survey" --on "$repair"
echo " - the repair option has only two places for its own SubIssues"
expect_refused ISSUE_SUB_ISSUE_POSITION_OUT_OF_RANGE \
  move-sub-issue "$issue_id" "$sleeve" --position 3

step "Priority and status (spec §14.1, §14.2)"
run_ok set-priority "$issue_id" high >/dev/null
run_ok change-status "$issue_id" in_execution >/dev/null
echo "   priority high, status in_execution"
echo " - the Issue is resolved only with a resolution summary"
expect_refused ISSUE_RESOLVE_REQUIRED change-status "$issue_id" resolved
echo " - and only once every SubIssue is closed"
expect_refused ISSUE_HAS_OPEN_SUB_ISSUES resolve "$issue_id" --summary "Riser section replaced."

step "Close the SubIssues and resolve the Issue"
for sub_issue_id in "$wrap" "$survey" "$replacement"; do
  run_ok change-status "$issue_id" resolved --sub-issue "$sub_issue_id" >/dev/null
done
run_ok change-status "$issue_id" unresolved --sub-issue "$sleeve" >/dev/null
run_ok change-status "$issue_id" resolved --sub-issue "$repair" >/dev/null
resolved=$(run_ok resolve "$issue_id" \
  --summary "Splash zone wrapped in May 2027; riser section replaced in the August shutdown.")
echo "   status: $(json_field status <<<"$resolved")"
echo " - a resolved Issue takes no new SubIssues until its status changes again"
expect_refused ISSUE_CLOSED add-sub-issue "$issue_id" --title "Late idea" --description "Too late."

step "The Issue as stored"
shown_file=$(mktemp)
run_ok show "$issue_id" >"$shown_file"
"$python" - "$shown_file" <<'EOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as shown:
    issue = json.load(shown)
print(f"   {issue['title']}  [{issue['status']}, priority {issue['priority']}]")
print(f"   resolution: {issue['resolution_summary']}")
titles = {}


def collect(sub_issues):
    for sub in sub_issues:
        titles[sub["sub_issue_id"]] = sub["title"]
        collect(sub["sub_issues"])


def show(sub_issues, depth):
    for sub in sub_issues:
        waits = ", ".join(titles[other] for other in sub["depends_on"])
        suffix = f"  (waits for: {waits})" if waits else ""
        indent = "    " * depth
        print(f"   {indent}{sub['position']}. {sub['title']}  [{sub['status']}]{suffix}")
        show(sub["sub_issues"], depth + 1)


collect(issue["sub_issues"])
show(issue["sub_issues"], 1)
EOF
rm -f "$shown_file"

echo
echo "Done. Run it again any time; add --reset to start from no Issues."
