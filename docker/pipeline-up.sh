#!/usr/bin/env bash
# Start the whole ingestion pipeline with one command (docs/running-ingestion.md):
# Postgres and RabbitMQ in Docker, then the tables, the outbox relay, the text
# workers, the vision worker, the chunking worker and the API as local processes. Ctrl+C stops the
# processes; the containers keep running unless --down is given.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: docker/pipeline-up.sh [options]

  --text-workers N   Text workers to start (default 1). Use 0 to let the queue
                     fill, then start one by hand: uv run knowledge worker run --lane text
  --no-vision        Do not start the vision worker, for example when Ollama is not running.
  --no-docker        Use the Postgres and RabbitMQ already running at DATABASE_URL and
                     RABBITMQ_URL instead of starting docker/docker-compose.yml.
  --down             Also stop the containers on exit. Their data is kept.
  -h, --help         Show this help.

Each process logs to <DATA_DIR>/logs/<name>.log.
EOF
}

text_workers=1
start_vision=true
start_docker=true
stop_docker=false
while (($#)); do
  case "$1" in
    --text-workers)
      [[ ${2:-} =~ ^[0-9]+$ ]] || { echo "--text-workers needs a number" >&2; exit 2; }
      text_workers=$2
      shift 2
      ;;
    --no-vision) start_vision=false; shift ;;
    --no-docker) start_docker=false; shift ;;
    --down) stop_docker=true; shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
compose=(docker compose -f docker/docker-compose.yml)

# The outbox relay must run once only (ADR 0005), so an earlier start must be stopped first.
if pgrep -f "knowledge (relay|worker|api) run" >/dev/null; then
  echo "Pipeline processes are already running:" >&2
  pgrep -af "knowledge (relay|worker|api) run" >&2
  echo "Stop them first (Ctrl+C in their terminals)." >&2
  exit 1
fi

if $start_docker; then
  echo "Starting Postgres and RabbitMQ…"
  "${compose[@]}" up -d --wait postgres rabbitmq
  "${compose[@]}" run --rm rabbitmq-policies
fi

echo "Creating the tables…"
uv run alembic upgrade head

# Read the settings through Settings, so .env and environment variables apply as in the core.
read -r data_dir api_host api_port ollama_url < <(
  .venv/bin/python -c 'from offline_rag.settings import Settings
s = Settings()
print(s.data_dir, s.api_host, s.api_port, s.ollama_url)'
)
log_dir="$data_dir/logs"
mkdir -p "$log_dir"

pids=()
names=()

stop_all() {
  trap - INT TERM EXIT
  echo
  echo "Stopping the pipeline…"
  for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  for pid in "${pids[@]}"; do wait "$pid" 2>/dev/null || true; done
  if $stop_docker && $start_docker; then
    "${compose[@]}" down
  fi
  echo "Stopped."
}
trap 'stop_all; exit 130' INT TERM
trap stop_all EXIT

start() {
  local name=$1
  shift
  # Called straight from .venv, so a stop signal reaches the process itself.
  .venv/bin/knowledge "$@" >"$log_dir/$name.log" 2>&1 &
  pids+=("$!")
  names+=("$name")
  echo "  $name (pid $!) → $log_dir/$name.log"
}

echo "Starting the processes…"
start relay relay run
for ((number = 1; number <= text_workers; number++)); do
  start "text-worker-$number" worker run --lane text
done
if $start_vision; then
  if ! curl -sf --max-time 2 "$ollama_url/api/tags" >/dev/null; then
    echo "  Ollama does not answer at $ollama_url; scanned pages wait until it runs."
  fi
  start vision-worker worker run --lane vision
fi
start chunking-worker worker run --lane chunking
start api api run

page_url="http://$api_host:$api_port/pipeline"
for _ in $(seq 1 60); do
  curl -sf --max-time 1 "http://$api_host:$api_port/health" >/dev/null && break
  sleep 0.5
done
echo
echo "Pipeline page: $page_url"
echo "Press Ctrl+C to stop."

# Stop everything when one process dies, so a crash is not missed during a demo.
set +e
wait -n "${pids[@]}"
set -e
for index in "${!pids[@]}"; do
  if ! kill -0 "${pids[$index]}" 2>/dev/null; then
    echo
    echo "${names[$index]} stopped. Last lines of $log_dir/${names[$index]}.log:"
    tail -n 5 "$log_dir/${names[$index]}.log"
  fi
done
exit 1
