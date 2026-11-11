#!/usr/bin/env bash
# Walk through Organizational Hierarchy step by step (phase 6): start Postgres,
# create the tables, import the case-study Nodes, register one more, show the
# hierarchy rules refusing bad Nodes, define the transfer rules of Layers 0 to 3,
# and print the chart. Safe to run again: known Nodes are left as they are.
# Runs on the bash 3.2 that ships with macOS.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: docker/organization-demo.sh [options]

  --no-docker   Use the Postgres already running at DATABASE_URL instead of
                starting it from docker/docker-compose.yml. The chart is not
                printed at the end, since that reads Postgres through Docker.
  --reset       Delete every Node and every transfer rule first, so the run
                starts from an empty chart. The five Layers stay.
  -h, --help    Show this help.
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
organization=.venv/bin/organization
python=.venv/bin/python
error_file=$(mktemp)
trap 'rm -f "$error_file"' EXIT

step_number=0
step() {
  step_number=$((step_number + 1))
  echo
  echo "== $step_number. $* =="
}

# Print one field of the JSON on stdin, such as `registered` or `type`.
json_field() {
  "$python" -c 'import json, sys
value = json.loads(sys.stdin.read())[sys.argv[1]]
print((", ".join(value) or "none") if isinstance(value, list) else value)' "$1"
}

# The Problem Details body is the last line on stderr; log lines come before it.
problem_type() {
  tail -n 1 "$error_file" | json_field type
}

# Run a command that must succeed, or that may only say the Node already exists.
run_ok() {
  local output
  if output=$("$organization" "$@" 2>"$error_file"); then
    printf '%s\n' "$output"
    return
  fi
  local code
  code=$(problem_type)
  if [[ $code == ORGANIZATION_NODE_ALREADY_REGISTERED ]]; then
    echo "   already registered, left as it is"
    return
  fi
  echo "   FAILED with $code" >&2
  cat "$error_file" >&2
  exit 1
}

# Run a command the rules must refuse, and check it is refused for the right reason.
expect_refused() {
  local expected=$1
  shift
  if "$organization" "$@" >/dev/null 2>"$error_file"; then
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

# Keep log lines short in the demo; errors still reach stderr as Problem Details.
export LOG_LEVEL=warning

if $start_docker; then
  step "Start Postgres"
  "${compose[@]}" up -d --wait postgres
fi

step "Create the tables and the five Layers (Alembic migrations)"
uv run alembic upgrade head
echo "   done"

if $reset; then
  step "Reset: delete every Node and every transfer rule"
  "$python" - <<'EOF'
import psycopg

from offline_rag.settings import Settings

with psycopg.connect(Settings().database_url) as connection:
    deleted = connection.execute("DELETE FROM node").rowcount
    connection.execute(
        "UPDATE layer SET required_topics = NULL, excluded_topics = NULL, output_format = NULL,"
        " min_judge_score_points = NULL, max_package_length_tokens = NULL,"
        " source_reference_level = NULL"
    )
print(f"   deleted {deleted} Nodes")
EOF
fi

step "Import the case-study chart from fixtures/registry/nodes.csv"
imported=$(run_ok import-nodes)
echo "   registered:         $(json_field registered <<<"$imported")"
echo "   already registered: $(json_field already_registered <<<"$imported")"

step "Register one more Node: an NDT team under Platform SP-12"
run_ok register-node sp12_ndt_team --name "SP-12 NDT Team" --layer 3 \
  --parent platform_sp12 --activity-area "non-destructive testing" --reporting-rule weekly

step "The hierarchy rules refuse bad Nodes"
echo " - a team under Platform SP-14, whose inside is outside the system boundary"
expect_refused ORGANIZATION_PARENT_STRUCTURE_NOT_TRACKED \
  register-node sp14_new_team --name "SP-14 Team" --layer 3 \
  --parent platform_sp14 --activity-area maintenance --reporting-rule weekly
echo " - a unit in Layer 2 under Platform SP-12, which is also in Layer 2"
expect_refused ORGANIZATION_PARENT_NOT_IN_HIGHER_LAYER \
  register-node sp12_sub_unit --name "SP-12 Sub Unit" --layer 2 \
  --parent platform_sp12 --activity-area production --reporting-rule weekly
echo " - a second Node in Layer 0, which holds one Node at the top"
expect_refused ORGANIZATION_TOP_LAYER_NODE_ALREADY_REGISTERED \
  register-node second_ministry --name "Second Ministry" --layer 0 \
  --activity-area oversight --reporting-rule quarterly
echo " - a team whose parent is not registered"
expect_refused ORGANIZATION_NODE_NOT_FOUND \
  register-node ghost_team --name "Ghost Team" --layer 3 \
  --parent platform_sp99 --activity-area maintenance --reporting-rule weekly

# Topics follow the detail levels of spec §6.4.
step "Define what each Layer requires of the packages it receives"
echo " - Layer 0, top executive"
run_ok define-transfer-rule 0 --detail-level top_executive \
  --required-topic "key achievements" --required-topic "major risks" \
  --required-topic "unresolved issues" --required-topic "strategic recommendations" \
  --excluded-topic "shift rosters" --output-format markdown \
  --max-package-length-tokens 800 --source-reference-level document
echo " - Layer 1, managerial"
run_ok define-transfer-rule 1 --detail-level managerial \
  --required-topic "project status" --required-topic "issue status" \
  --required-topic "research gaps" --required-topic "decisions needed" \
  --excluded-topic "shift rosters" --output-format markdown \
  --max-package-length-tokens 1500 --source-reference-level document
echo " - Layer 2, technical summary"
run_ok define-transfer-rule 2 --detail-level technical_summary \
  --required-topic "methods" --required-topic "research results" \
  --required-topic "solution options" --output-format markdown \
  --max-package-length-tokens 3000 --source-reference-level section
echo " - Layer 3, detailed technical"
run_ok define-transfer-rule 3 --detail-level detailed_technical \
  --required-topic "full issue details" --required-topic "source evidence" \
  --output-format markdown --max-package-length-tokens 6000 --source-reference-level page
echo " - Layer 4 only provides knowledge, so it takes no rule"
expect_refused ORGANIZATION_LAYER_RECEIVES_NO_PACKAGE \
  define-transfer-rule 4 --detail-level detailed_technical --output-format markdown \
  --max-package-length-tokens 6000 --source-reference-level page

if $start_docker; then
  step "The chart as stored in Postgres"
  "${compose[@]}" exec -T postgres psql -U petro_ops -d petro_ops -At <<'EOF'
WITH RECURSIVE tree AS (
    SELECT node_id, layer_index, 0 AS depth, node_id AS path
    FROM node WHERE parent_node_id IS NULL
    UNION ALL
    SELECT node.node_id, node.layer_index, tree.depth + 1, tree.path || '/' || node.node_id
    FROM node JOIN tree ON node.parent_node_id = tree.node_id
)
SELECT 'Layer ' || layer_index || '  ' || repeat('    ', depth) || node_id
FROM tree ORDER BY path;
SELECT 'Layer ' || layer_index || ' receives ' || coalesce(received_detail_level, 'nothing')
    || coalesce(', max ' || max_package_length_tokens || ' tokens, judge >= '
        || min_judge_score_points || '/20', '')
FROM layer ORDER BY layer_index;
EOF
fi

echo
echo "Done. Run it again any time; add --reset to start from an empty chart."
