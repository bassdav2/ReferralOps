#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FRONTEND_PORT_CONFIGURED="${FRONTEND_PORT+x}"
FRONTEND_URL_CONFIGURED="${FRONTEND_URL+x}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:$BACKEND_PORT}"
FRONTEND_URL="${FRONTEND_URL:-http://127.0.0.1:$FRONTEND_PORT}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/tmp/judge-demo}"
OPEN_BROWSER="${OPEN_BROWSER:-true}"
export NO_EXTERNAL_AI_CALLS=true

mkdir -p "$LOG_DIR"

BACKEND_HEALTH="$BACKEND_URL/api/health"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

prompt_yes_no() {
  local prompt="$1"
  local answer

  case "${INSTALL_SYSTEM_DEPS:-prompt}" in
    1|true|TRUE|yes|YES) return 0 ;;
    0|false|FALSE|no|NO) return 1 ;;
  esac

  if [ ! -t 0 ]; then
    return 1
  fi

  read -r -p "$prompt [y/N] " answer || return 1
  case "$answer" in
    y|Y|yes|YES|Yes) return 0 ;;
    *) return 1 ;;
  esac
}

find_python_cmd() {
  if [ -n "${PYTHON:-}" ]; then
    printf '%s\n' "$PYTHON"
    return 0
  fi

  for candidate in python3.12 python3 python; do
    if command_exists "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done

  return 1
}

python_runtime_ok() {
  local candidate
  candidate="$(find_python_cmd)" || return 1
  "$candidate" scripts/check_runtime.py >/dev/null 2>&1
}

node_runtime_ok() {
  command_exists node || return 1
  [ "$(node -p 'Number(process.versions.node.split(".")[0]) >= 22 ? "ok" : "old"' 2>/dev/null)" = "ok" ]
}

load_homebrew() {
  if command_exists brew; then
    return 0
  fi

  for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew "$HOME/.linuxbrew/bin/brew"; do
    if [ -x "$brew_bin" ]; then
      eval "$("$brew_bin" shellenv)"
      return 0
    fi
  done

  return 1
}

configure_tesseract_environment() {
  if ! command_exists tesseract; then
    return 0
  fi

  export TESSERACT_CMD="$(command -v tesseract)"

  local prefix
  prefix="$(cd "$(dirname "$TESSERACT_CMD")/.." && pwd)"
  for tessdata_dir in \
    "$prefix/share/tessdata" \
    /opt/homebrew/share/tessdata \
    /usr/local/share/tessdata \
    /usr/share/tesseract-ocr/5/tessdata \
    /usr/share/tesseract-ocr/4.00/tessdata \
    /usr/share/tessdata; do
    if [ -d "$tessdata_dir" ]; then
      export TESSDATA_PREFIX="${TESSDATA_PREFIX:-$tessdata_dir}"
      return 0
    fi
  done
}

ensure_homebrew() {
  if load_homebrew; then
    return 0
  fi

  if ! command_exists curl; then
    fail "Homebrew is needed for automatic macOS installs, but curl is missing. Install Homebrew from https://brew.sh/ and rerun this launcher."
  fi

  if ! prompt_yes_no "Homebrew is required to install missing macOS dependencies automatically. Install Homebrew now?"; then
    return 1
  fi

  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  load_homebrew || fail "Homebrew installed, but this shell cannot find brew. Open a new terminal or rerun Start ReferralOps.command."
}

print_manual_install_hint() {
  case "$(uname -s)" in
    Darwin)
      cat <<'EOF'
Manual macOS install:
  brew install python@3.12 node tesseract tesseract-lang
EOF
      ;;
    Linux)
      cat <<'EOF'
Manual Debian/Ubuntu install:
  sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv nodejs npm tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu curl
EOF
      ;;
    *)
      echo "Install Python 3.12+, Node.js 22+, npm, curl, and Tesseract OCR, then rerun this launcher."
      ;;
  esac
}

install_macos_dependencies() {
  ensure_homebrew || return 1

  local packages=()
  python_runtime_ok || packages+=(python@3.12)
  if ! node_runtime_ok || ! command_exists npm; then
    packages+=(node)
  fi
  command_exists tesseract || packages+=(tesseract tesseract-lang)

  if [ "${#packages[@]}" -gt 0 ]; then
    brew install "${packages[@]}"
  fi
}

install_linux_dependencies() {
  local packages=()

  if command_exists apt-get; then
    python_runtime_ok || packages+=(python3.12 python3.12-venv)
    node_runtime_ok || packages+=(nodejs)
    command_exists npm || packages+=(npm)
    command_exists curl || packages+=(curl)
    command_exists tesseract || packages+=(tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu)
    sudo apt-get update
    sudo apt-get install -y "${packages[@]}"
  elif command_exists dnf; then
    python_runtime_ok || packages+=(python3)
    node_runtime_ok || packages+=(nodejs)
    command_exists npm || packages+=(npm)
    command_exists curl || packages+=(curl)
    command_exists tesseract || packages+=(tesseract tesseract-langpack-eng tesseract-langpack-deu)
    sudo dnf install -y "${packages[@]}"
  elif command_exists pacman; then
    python_runtime_ok || packages+=(python)
    node_runtime_ok || packages+=(nodejs)
    command_exists npm || packages+=(npm)
    command_exists curl || packages+=(curl)
    command_exists tesseract || packages+=(tesseract tesseract-data-eng tesseract-data-deu)
    sudo pacman -S --needed --noconfirm "${packages[@]}"
  else
    return 1
  fi
}

install_missing_system_dependencies() {
  local missing_required=()
  local missing_optional=()

  python_runtime_ok || missing_required+=("Python 3.12+")
  node_runtime_ok || missing_required+=("Node.js 22+")
  command_exists npm || missing_required+=("npm")
  command_exists curl || missing_required+=("curl")
  command_exists tesseract || missing_optional+=("Tesseract OCR for scanned PDFs")

  if [ "${#missing_required[@]}" -eq 0 ] && [ "${#missing_optional[@]}" -eq 0 ]; then
    return 0
  fi

  echo "Missing system dependencies:"
  for dependency in "${missing_required[@]}"; do
    echo "  - $dependency"
  done
  for dependency in "${missing_optional[@]}"; do
    echo "  - $dependency"
  done
  echo

  if prompt_yes_no "Install missing system dependencies now?"; then
    case "$(uname -s)" in
      Darwin) install_macos_dependencies || fail "Automatic macOS install is unavailable. Install the dependencies manually and rerun this launcher." ;;
      Linux) install_linux_dependencies || fail "Automatic Linux install is unavailable for this distribution. Install the dependencies manually and rerun this launcher." ;;
      *) fail "Automatic install is not supported on this OS. Install the dependencies manually and rerun this launcher." ;;
    esac
  else
    if [ "${#missing_required[@]}" -gt 0 ]; then
      print_manual_install_hint
      fail "Required system dependencies are missing."
    fi
  fi

  local still_missing_required=()
  python_runtime_ok || still_missing_required+=("Python 3.12+")
  node_runtime_ok || still_missing_required+=("Node.js 22+")
  command_exists npm || still_missing_required+=("npm")
  command_exists curl || still_missing_required+=("curl")

  if [ "${#still_missing_required[@]}" -gt 0 ]; then
    print_manual_install_hint
    fail "Some required dependencies are still missing after installation: ${still_missing_required[*]}"
  fi

  if ! command_exists tesseract; then
    echo "Warning: Tesseract is still missing. Selectable PDFs work; scanned PDFs need OCR."
  fi
}

url_ok() {
  curl -fsS --max-time 2 "$1" >/dev/null 2>&1
}

port_in_use() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

listener_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
  fi
}

port_owned_by_repo() {
  local port="$1"
  local pid
  local command_line

  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if printf '%s\n' "$command_line" | grep -F "$ROOT_DIR" >/dev/null 2>&1; then
      return 0
    fi
  done < <(listener_pids "$port")

  return 1
}

listener_summary() {
  local port="$1"

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sed '1d' || true
  fi
}

fail_port_conflict() {
  local label="$1"
  local port="$2"
  local url="$3"
  local env_name="$4"

  listener_summary "$port"
  fail "$label port $port is already in use by another process, so the launcher cannot safely reuse $url. Stop that process or rerun with $env_name set to a free port."
}

find_available_port() {
  local start_port="$1"
  local end_port="$2"
  local port

  for port in $(seq "$start_port" "$end_port"); do
    if ! port_in_use "$port"; then
      printf '%s\n' "$port"
      return 0
    fi
  done

  return 1
}

resolve_frontend_port() {
  local fallback_port

  if ! port_in_use "$FRONTEND_PORT" || port_owned_by_repo "$FRONTEND_PORT"; then
    return 0
  fi

  if [ -n "$FRONTEND_PORT_CONFIGURED" ] || [ -n "$FRONTEND_URL_CONFIGURED" ]; then
    fail_port_conflict "Frontend" "$FRONTEND_PORT" "$FRONTEND_URL" "FRONTEND_PORT"
  fi

  fallback_port="$(find_available_port "$((FRONTEND_PORT + 1))" "$((FRONTEND_PORT + 50))")" \
    || fail_port_conflict "Frontend" "$FRONTEND_PORT" "$FRONTEND_URL" "FRONTEND_PORT"

  echo "Frontend port $FRONTEND_PORT is already in use by another process; using $fallback_port instead."
  FRONTEND_PORT="$fallback_port"
  FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"
}

configure_cors_origins() {
  export BACKEND_CORS_ORIGINS="${BACKEND_CORS_ORIGINS:-$FRONTEND_URL,http://localhost:$FRONTEND_PORT,http://127.0.0.1:$FRONTEND_PORT}"
}

preflight_port_conflicts() {
  if port_in_use "$BACKEND_PORT" && ! port_owned_by_repo "$BACKEND_PORT"; then
    fail_port_conflict "Backend" "$BACKEND_PORT" "$BACKEND_HEALTH" "BACKEND_PORT"
  fi

  if port_in_use "$FRONTEND_PORT" && ! port_owned_by_repo "$FRONTEND_PORT"; then
    fail_port_conflict "Frontend" "$FRONTEND_PORT" "$FRONTEND_URL" "FRONTEND_PORT"
  fi
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local log_file="$3"

  for _ in $(seq 1 90); do
    if url_ok "$url"; then
      echo "$label ready: $url"
      return 0
    fi
    sleep 1
  done

  echo "$label did not become ready. Last log lines:" >&2
  tail -n 80 "$log_file" >&2 || true
  exit 1
}

open_dashboard() {
  if ! is_truthy "$OPEN_BROWSER"; then
    return 0
  fi

  echo "Opening dashboard in your browser: $FRONTEND_URL"

  if [ "$(uname -s)" = "Darwin" ]; then
    if /usr/bin/open "$FRONTEND_URL" >/dev/null 2>&1; then
      return 0
    fi
    if command_exists osascript && osascript -e "open location \"$FRONTEND_URL\"" >/dev/null 2>&1; then
      return 0
    fi
  elif command -v xdg-open >/dev/null 2>&1; then
    if xdg-open "$FRONTEND_URL" >/dev/null 2>&1; then
      return 0
    fi
  fi

  echo "Could not open the dashboard automatically. Open it manually: $FRONTEND_URL"
}

configure_tesseract_environment
resolve_frontend_port
configure_cors_origins
preflight_port_conflicts
install_missing_system_dependencies
configure_tesseract_environment

PYTHON_CMD="$(find_python_cmd)" || fail "Python 3.12+ is required."
"$PYTHON_CMD" scripts/check_runtime.py

if [ ! -f .env ]; then
  cp .env.local-model.example .env
  echo "Created .env from .env.local-model.example"
fi

VENV_PY="$ROOT_DIR/.venv/bin/python"
VENV_PIP="$ROOT_DIR/.venv/bin/pip"
VENV_UVICORN="$ROOT_DIR/.venv/bin/uvicorn"

if [ ! -x "$VENV_PY" ] || [ ! -x "$VENV_UVICORN" ] || [ ! -d frontend/node_modules ]; then
  echo "Installing local Python and frontend dependencies..."
  "$PYTHON_CMD" -m venv .venv
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PIP" install -e ".[dev]"
  npm --prefix frontend ci
else
  echo "Local dependencies already installed."
fi

echo "Preparing synthetic guideline demo data..."
"$VENV_PY" scripts/ingest_guidelines.py

if url_ok "$BACKEND_HEALTH" && port_owned_by_repo "$BACKEND_PORT"; then
  echo "Backend already running: $BACKEND_HEALTH"
elif port_in_use "$BACKEND_PORT"; then
  if port_owned_by_repo "$BACKEND_PORT"; then
    fail "Backend port $BACKEND_PORT is owned by this repo, but $BACKEND_HEALTH is not healthy. Stop the existing backend process and rerun this launcher."
  else
    fail_port_conflict "Backend" "$BACKEND_PORT" "$BACKEND_HEALTH" "BACKEND_PORT"
  fi
else
  echo "Starting backend on $BACKEND_URL..."
  nohup "$VENV_UVICORN" backend.app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --reload-dir "$ROOT_DIR/backend" --reload-dir "$ROOT_DIR/configs" >"$BACKEND_LOG" 2>&1 &
  echo "$!" >"$LOG_DIR/backend.pid"
  wait_for_url "Backend" "$BACKEND_HEALTH" "$BACKEND_LOG"
fi

if url_ok "$FRONTEND_URL" && port_owned_by_repo "$FRONTEND_PORT"; then
  echo "Frontend already running: $FRONTEND_URL"
elif port_in_use "$FRONTEND_PORT"; then
  if port_owned_by_repo "$FRONTEND_PORT"; then
    fail "Frontend port $FRONTEND_PORT is owned by this repo, but $FRONTEND_URL is not reachable. Stop the existing frontend process and rerun this launcher."
  else
    fail_port_conflict "Frontend" "$FRONTEND_PORT" "$FRONTEND_URL" "FRONTEND_PORT"
  fi
else
  echo "Starting frontend on $FRONTEND_URL..."
  nohup env VITE_API_BASE_URL="$BACKEND_URL" npm --prefix frontend run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" --strictPort >"$FRONTEND_LOG" 2>&1 &
  echo "$!" >"$LOG_DIR/frontend.pid"
  wait_for_url "Frontend" "$FRONTEND_URL" "$FRONTEND_LOG"
fi

open_dashboard

cat <<EOF

ReferralOps judge demo is ready.

Dashboard: $FRONTEND_URL
Backend:   $BACKEND_HEALTH
Logs:      $LOG_DIR

In the dashboard:
1. Open Local Model.
2. Enter your local OpenAI-compatible endpoint and model id.
3. Click Test connection.
4. Drag PDFs from demos/referral_inbox_samples/ into PDF-Inbox.

To stop servers started by this launcher:
  kill \$(cat "$LOG_DIR"/*.pid)
EOF
