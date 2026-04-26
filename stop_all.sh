#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.run/services.json"
KNOWN_PORTS=(8000 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010 8080)

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

is_pid_alive() {
  local pid="${1:-}"
  [[ -z "$pid" || "$pid" == "null" ]] && return 1
  kill -0 "$pid" >/dev/null 2>&1
}

json_number_value() {
  local key="$1"
  local file="$2"
  grep -oE "\"$key\"[[:space:]]*:[[:space:]]*[0-9]+" "$file" | head -n1 | grep -oE "[0-9]+" || true
}

stop_pid() {
  local pid="$1"
  local name="${2:-process}"
  if ! is_pid_alive "$pid"; then
    echo "$name: process not found (PID=$pid)"
    return 0
  fi

  kill "$pid" >/dev/null 2>&1 || true
  sleep 0.3
  if is_pid_alive "$pid"; then
    kill -9 "$pid" >/dev/null 2>&1 || true
    sleep 0.2
  fi

  if is_pid_alive "$pid"; then
    echo "Warning: $name failed to stop (PID=$pid)"
  else
    echo "$name: stopped (PID=$pid)"
  fi
}

pids_listening_on_port() {
  local port="$1"
  if command_exists lsof; then
    lsof -t -iTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | sort -u || true
    return 0
  fi
  if command_exists ss; then
    ss -ltnp "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | grep -oE '[0-9]+' | sort -u || true
    return 0
  fi
  if command_exists netstat; then
    netstat -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p"$" {split($7,a,"/"); if (a[1] ~ /^[0-9]+$/) print a[1]}' | sort -u || true
    return 0
  fi
}

stop_project_port_listeners() {
  local killed=()
  local port pid proc_name
  for port in "${KNOWN_PORTS[@]}"; do
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      [[ "$pid" == "$$" ]] && continue
      if ! is_pid_alive "$pid"; then
        continue
      fi
      proc_name="$(ps -p "$pid" -o comm= 2>/dev/null | tr '[:upper:]' '[:lower:]' | xargs || true)"
      case "$proc_name" in
        python|python3|java|mvn|bash|sh|pwsh|powershell)
          stop_pid "$pid" "port=$port $proc_name"
          killed+=("$port:$pid:$proc_name")
          ;;
      esac
    done < <(pids_listening_on_port "$port")
  done

  if [[ ${#killed[@]} -gt 0 ]]; then
    echo "Port cleanup killed:"
    local item
    for item in "${killed[@]}"; do
      echo "  $item"
    done
  fi
}

if [[ ! -f "$PID_FILE" ]]; then
  echo "No PID file found. Nothing to stop."
  stop_project_port_listeners
  exit 0
fi

fastapi_pid="$(json_number_value "fastapi_pid" "$PID_FILE")"
excel_pid="$(json_number_value "excel_pid" "$PID_FILE")"

if [[ -n "$fastapi_pid" ]]; then
  stop_pid "$fastapi_pid" "FastAPI"
fi
if [[ -n "$excel_pid" ]]; then
  stop_pid "$excel_pid" "checkinexcel"
fi

rm -f "$PID_FILE"
stop_project_port_listeners
echo "Stop completed."
