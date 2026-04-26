#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$RUN_DIR/logs"
PID_FILE="$RUN_DIR/services.json"
TRACE_FILE="$RUN_DIR/start_trace.log"

PYTHON_EXE="${PYTHON_EXE:-}"
YOLO_PYTHON_EXE="${YOLO_PYTHON_EXE:-}"
MAVEN_EXE="${MAVEN_EXE:-mvn}"
JAVA_EXE="${JAVA_EXE:-java}"
PORT="${PORT:-8000}"
MAX_PORT="${MAX_PORT:-8010}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-20}"
ENABLE_EXTERNAL_EXCEL="${ENABLE_EXTERNAL_EXCEL:-0}"
WAIT_FOR_READY="${WAIT_FOR_READY:-0}"
ENABLE_RELOAD="${ENABLE_RELOAD:-0}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}"
DISABLE_AUTO_PUBLIC_BASE="${DISABLE_AUTO_PUBLIC_BASE:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python-exe)
      PYTHON_EXE="$2"; shift 2 ;;
    --yolo-python-exe)
      YOLO_PYTHON_EXE="$2"; shift 2 ;;
    --maven-exe)
      MAVEN_EXE="$2"; shift 2 ;;
    --java-exe)
      JAVA_EXE="$2"; shift 2 ;;
    --port)
      PORT="$2"; shift 2 ;;
    --max-port)
      MAX_PORT="$2"; shift 2 ;;
    --startup-timeout-seconds)
      STARTUP_TIMEOUT_SECONDS="$2"; shift 2 ;;
    --enable-external-excel)
      ENABLE_EXTERNAL_EXCEL="1"; shift ;;
    --wait-for-ready)
      WAIT_FOR_READY="1"; shift ;;
    --enable-reload)
      ENABLE_RELOAD="1"; shift ;;
    --public-base-url)
      PUBLIC_BASE_URL="$2"; shift 2 ;;
    --disable-auto-public-base)
      DISABLE_AUTO_PUBLIC_BASE="1"; shift ;;
    -h|--help)
      cat <<'EOF'
Usage: ./start_all.sh [options]
  --python-exe <path|cmd>          Python executable (default: python3/python)
  --yolo-python-exe <path|cmd>     Preferred python executable
  --port <int>                     Start port (default 8000)
  --max-port <int>                 Max port (default 8010)
  --enable-reload                  Enable uvicorn reload
  --wait-for-ready                 Wait service ready check
  --enable-external-excel          Try start Java checkinexcel service
  --public-base-url <url|host>     Public base URL used in QR links
  --disable-auto-public-base       Disable LAN IP auto-detection
EOF
      exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"
: > "$TRACE_FILE"

write_trace() {
  local msg="$1"
  local line
  line="[$(date +'%H:%M:%S.%3N')] $msg"
  echo "$line" | tee -a "$TRACE_FILE"
}

command_exists() {
  local cmd="$1"
  [[ -z "$cmd" ]] && return 1
  if [[ -x "$cmd" ]]; then
    return 0
  fi
  command -v "$cmd" >/dev/null 2>&1
}

is_pid_alive() {
  local pid="$1"
  [[ -z "$pid" || "$pid" == "null" ]] && return 1
  kill -0 "$pid" >/dev/null 2>&1
}

is_port_in_use() {
  local port="$1"
  if command_exists ss; then
    ss -ltn "sport = :$port" 2>/dev/null | tail -n +2 | grep -q .
    return $?
  fi
  if command_exists lsof; then
    lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1
    return $?
  fi
  if command_exists netstat; then
    netstat -ltn 2>/dev/null | awk '{print $4}' | grep -E "[:.]$port$" >/dev/null 2>&1
    return $?
  fi
  return 1
}

http_ok() {
  local url="$1"
  if command_exists curl; then
    curl -fsS --max-time 2 "$url" >/dev/null 2>&1
    return $?
  fi
  if command_exists wget; then
    wget -q -T 2 -O- "$url" >/dev/null 2>&1
    return $?
  fi
  "$PYTHON_EXE" -c "import urllib.request; urllib.request.urlopen('$url', timeout=2).read(1)" >/dev/null 2>&1
}

wait_service_ready() {
  local url="$1"
  local timeout="$2"
  local end_time
  end_time=$(( $(date +%s) + timeout ))
  while [[ $(date +%s) -lt "$end_time" ]]; do
    if http_ok "$url"; then
      return 0
    fi
    sleep 0.4
  done
  return 1
}

json_number_value() {
  local key="$1"
  local file="$2"
  grep -oE "\"$key\"[[:space:]]*:[[:space:]]*[0-9]+" "$file" | head -n1 | grep -oE "[0-9]+" || true
}

get_available_port() {
  local start="$1"
  local end="$2"
  local p
  for ((p=start; p<=end; p++)); do
    if ! is_port_in_use "$p"; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

get_preferred_local_ipv4() {
  local all_ips ip
  all_ips="$(ip -o -4 addr show up scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)"
  for ip in $all_ips; do
    [[ "$ip" =~ ^127\. ]] && continue
    [[ "$ip" =~ ^169\.254\. ]] && continue
    if [[ "$ip" =~ ^192\.168\. ]] || [[ "$ip" =~ ^10\. ]]; then
      echo "$ip"
      return 0
    fi
    if [[ "$ip" =~ ^172\.([0-9]+)\. ]]; then
      local seg="${BASH_REMATCH[1]}"
      if (( seg >= 16 && seg <= 31 )); then
        echo "$ip"
        return 0
      fi
    fi
  done
  for ip in $all_ips; do
    [[ "$ip" =~ ^127\. ]] && continue
    [[ "$ip" =~ ^169\.254\. ]] && continue
    echo "$ip"
    return 0
  done
  return 1
}

resolve_public_base_for_port() {
  local base="$1"
  local port="$2"
  [[ -z "$base" ]] && return 0
  base="${base%/}"
  if [[ ! "$base" =~ ^https?:// ]]; then
    base="http://$base"
  fi
  if [[ "$base" =~ ^https?://[^/]+:[0-9]+(/.*)?$ ]]; then
    echo "${base%%/}"
  else
    echo "${base%%/}:$port"
  fi
}

write_trace "Script start."

if [[ -z "$PYTHON_EXE" ]]; then
  if [[ -n "$YOLO_PYTHON_EXE" ]] && command_exists "$YOLO_PYTHON_EXE"; then
    PYTHON_EXE="$YOLO_PYTHON_EXE"
  elif command_exists python3; then
    PYTHON_EXE="python3"
  elif command_exists python; then
    PYTHON_EXE="python"
  else
    echo "Python command not found. Set --python-exe or install python3." >&2
    exit 1
  fi
fi

if ! command_exists "$PYTHON_EXE"; then
  echo "Python command not found: $PYTHON_EXE" >&2
  exit 1
fi
write_trace "Python resolved: $PYTHON_EXE"

if [[ -f "$PID_FILE" ]]; then
  old_fastapi_pid="$(json_number_value "fastapi_pid" "$PID_FILE")"
  old_excel_pid="$(json_number_value "excel_pid" "$PID_FILE")"
  alive=()
  if is_pid_alive "$old_fastapi_pid"; then alive+=("$old_fastapi_pid"); fi
  if is_pid_alive "$old_excel_pid"; then alive+=("$old_excel_pid"); fi
  if [[ ${#alive[@]} -gt 0 ]]; then
    echo "Existing service process(es) still running: ${alive[*]}" >&2
    echo "Run ./stop_all.sh first if you want to restart." >&2
    exit 1
  fi
fi

INITIAL_PORT="$(get_available_port "$PORT" "$MAX_PORT" || true)"
if [[ -z "$INITIAL_PORT" ]]; then
  echo "No available port in range $PORT-$MAX_PORT." >&2
  exit 1
fi
write_trace "Initial available port candidate: $INITIAL_PORT"

RUN_ID="$(date +%Y%m%d_%H%M%S)"
FASTAPI_PID=""
FASTAPI_OUT=""
FASTAPI_ERR=""
SELECTED_PORT=""
SELECTED_PUBLIC_BASE_URL=""
EXCEL_MODE="builtin"
EXCEL_PID=""
EXCEL_OUT="$LOG_DIR/excel.$RUN_ID.out.log"
EXCEL_ERR="$LOG_DIR/excel.$RUN_ID.err.log"

PUBLIC_BASE_SEED=""
if [[ -n "$PUBLIC_BASE_URL" ]]; then
  PUBLIC_BASE_SEED="$PUBLIC_BASE_URL"
  write_trace "Public base provided by parameter: $PUBLIC_BASE_SEED"
elif [[ -n "${FACE_SERVICE_PUBLIC_BASE_URL:-}" ]]; then
  PUBLIC_BASE_SEED="$FACE_SERVICE_PUBLIC_BASE_URL"
  write_trace "Public base provided by env FACE_SERVICE_PUBLIC_BASE_URL: $PUBLIC_BASE_SEED"
elif [[ "$DISABLE_AUTO_PUBLIC_BASE" != "1" ]]; then
  LAN_IP="$(get_preferred_local_ipv4 || true)"
  if [[ -n "$LAN_IP" ]]; then
    PUBLIC_BASE_SEED="http://$LAN_IP"
    write_trace "Auto-detected LAN IP for public links: $LAN_IP"
  fi
fi

HAS_MAVEN="0"
HAS_JAVA="0"
if command_exists "$MAVEN_EXE"; then HAS_MAVEN="1"; fi
if command_exists "$JAVA_EXE"; then HAS_JAVA="1"; fi

JAR_FILE=""
if [[ -d "$ROOT_DIR/checkinexcel/target" ]]; then
  JAR_FILE="$(find "$ROOT_DIR/checkinexcel/target" -maxdepth 1 -type f -name "*.jar" ! -name "original*" | sort | tail -n1 || true)"
fi

if [[ "$ENABLE_EXTERNAL_EXCEL" == "1" ]]; then
  if [[ "$HAS_MAVEN" == "1" ]]; then
    EXCEL_MODE="maven"
  elif [[ "$HAS_JAVA" == "1" && -n "$JAR_FILE" ]]; then
    EXCEL_MODE="jar"
  fi
fi
write_trace "Excel mode selected: $EXCEL_MODE"

for ((candidate=INITIAL_PORT; candidate<=MAX_PORT; candidate++)); do
  CANDIDATE_OUT="$LOG_DIR/fastapi.$RUN_ID.p$candidate.out.log"
  CANDIDATE_ERR="$LOG_DIR/fastapi.$RUN_ID.p$candidate.err.log"
  CANDIDATE_PUBLIC_BASE="$(resolve_public_base_for_port "$PUBLIC_BASE_SEED" "$candidate" || true)"
  write_trace "FastAPI start attempt on port $candidate"

  if [[ "$ENABLE_RELOAD" == "1" ]]; then
    FACE_SERVICE_PUBLIC_BASE_URL="$CANDIDATE_PUBLIC_BASE" "$PYTHON_EXE" -m uvicorn api:app --host 0.0.0.0 --port "$candidate" --reload >"$CANDIDATE_OUT" 2>"$CANDIDATE_ERR" &
  else
    FACE_SERVICE_PUBLIC_BASE_URL="$CANDIDATE_PUBLIC_BASE" "$PYTHON_EXE" -m uvicorn api:app --host 0.0.0.0 --port "$candidate" >"$CANDIDATE_OUT" 2>"$CANDIDATE_ERR" &
  fi
  PROBE_PID=$!

  READY="0"
  for _ in {1..10}; do
    sleep 0.5
    if ! is_pid_alive "$PROBE_PID"; then
      break
    fi
    if http_ok "http://127.0.0.1:$candidate/docs"; then
      READY="1"
      break
    fi
  done

  if [[ "$READY" != "1" ]]; then
    if is_pid_alive "$PROBE_PID"; then
      kill -9 "$PROBE_PID" >/dev/null 2>&1 || true
    fi
    write_trace "FastAPI process not ready on port $candidate. Trying next port."
    continue
  fi

  FASTAPI_PID="$PROBE_PID"
  FASTAPI_OUT="$CANDIDATE_OUT"
  FASTAPI_ERR="$CANDIDATE_ERR"
  SELECTED_PORT="$candidate"
  SELECTED_PUBLIC_BASE_URL="$CANDIDATE_PUBLIC_BASE"
  break
done

if [[ -z "$FASTAPI_PID" ]]; then
  echo "FastAPI failed to start on any port in range $INITIAL_PORT-$MAX_PORT." >&2
  exit 1
fi
write_trace "FastAPI process started. PID=$FASTAPI_PID port=$SELECTED_PORT"

if [[ "$WAIT_FOR_READY" == "1" ]]; then
  if ! wait_service_ready "http://127.0.0.1:$SELECTED_PORT/docs" "$STARTUP_TIMEOUT_SECONDS"; then
    kill -9 "$FASTAPI_PID" >/dev/null 2>&1 || true
    echo "FastAPI startup timeout (${STARTUP_TIMEOUT_SECONDS}s). Process stopped." >&2
    exit 1
  fi
fi

if [[ "$EXCEL_MODE" == "maven" ]]; then
  "$MAVEN_EXE" -f "$ROOT_DIR/checkinexcel/pom.xml" spring-boot:run >"$EXCEL_OUT" 2>"$EXCEL_ERR" &
  EXCEL_PID=$!
elif [[ "$EXCEL_MODE" == "jar" ]]; then
  "$JAVA_EXE" -jar "$JAR_FILE" >"$EXCEL_OUT" 2>"$EXCEL_ERR" &
  EXCEL_PID=$!
fi

if [[ -n "$EXCEL_PID" ]]; then
  sleep 1
  if ! is_pid_alive "$EXCEL_PID"; then
    EXCEL_PID=""
    EXCEL_MODE="builtin"
    write_trace "External checkinexcel failed to start, switched to builtin."
  fi
fi

LOCAL_BASE_URL="http://localhost:$SELECTED_PORT"
if [[ -n "$SELECTED_PUBLIC_BASE_URL" ]]; then
  PUBLIC_BASE_FINAL="$SELECTED_PUBLIC_BASE_URL"
else
  PUBLIC_BASE_FINAL="$LOCAL_BASE_URL"
fi

HOME_URL="$PUBLIC_BASE_FINAL/"
CHECKIN_URL="$PUBLIC_BASE_FINAL/checkin-ui"
ANALYSIS_URL="$PUBLIC_BASE_FINAL/analysis-ui"
DOCS_URL="$PUBLIC_BASE_FINAL/docs"
if [[ "$EXCEL_MODE" == "builtin" ]]; then
  EXCEL_API_URL="$PUBLIC_BASE_FINAL/api/excel/generate"
else
  EXCEL_API_URL="http://localhost:8080/api/excel/generate"
fi

EXCEL_PID_JSON="null"
if [[ -n "$EXCEL_PID" ]]; then
  EXCEL_PID_JSON="$EXCEL_PID"
fi

cat > "$PID_FILE" <<EOF
{
  "started_at": "$(date +'%Y-%m-%d %H:%M:%S')",
  "python_exe": "$PYTHON_EXE",
  "fastapi_pid": $FASTAPI_PID,
  "excel_pid": $EXCEL_PID_JSON,
  "excel_mode": "$EXCEL_MODE",
  "port": $SELECTED_PORT,
  "local_base_url": "$LOCAL_BASE_URL",
  "public_base_url": "$PUBLIC_BASE_FINAL",
  "home_url": "$HOME_URL",
  "checkin_url": "$CHECKIN_URL",
  "analysis_url": "$ANALYSIS_URL",
  "docs_url": "$DOCS_URL",
  "excel_api_url": "$EXCEL_API_URL",
  "fastapi_out_log": "$FASTAPI_OUT",
  "fastapi_err_log": "$FASTAPI_ERR",
  "excel_out_log": "$EXCEL_OUT",
  "excel_err_log": "$EXCEL_ERR"
}
EOF

write_trace "Status file written: $PID_FILE"

echo
echo "Services started:"
echo "Python: $PYTHON_EXE"
echo "1) FastAPI (PID=$FASTAPI_PID): $LOCAL_BASE_URL"
if [[ "$EXCEL_MODE" == "builtin" ]]; then
  echo "2) Excel API mode: builtin (served by FastAPI on $EXCEL_API_URL)"
else
  echo "2) checkinexcel (PID=$EXCEL_PID): http://localhost:8080"
fi
echo
echo "Public Base: $PUBLIC_BASE_FINAL"
echo "Home: $HOME_URL"
echo "Stop: ./stop_all.sh"
echo "Logs: $LOG_DIR"
write_trace "Script end."
