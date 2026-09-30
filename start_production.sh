#!/bin/bash
# ============================================
# HLD Generator v2 - Production Startup Script
# Manages: Frontend (6601) | Backend (6602) | Celery Worker | Redis (6379)
# Bind application services to loopback; publish through a TLS reverse proxy.
# ============================================

set -euo pipefail

# ============================================
# Configuration
# ============================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_SCRIPT="${ROOT_DIR}/serve_frontend.py"
LOG_DIR="${ROOT_DIR}/logs"
PID_DIR="${ROOT_DIR}/run"
LOG_RUNNER="${ROOT_DIR}/shared/run_with_log_rotation.py"

# Ensure project virtualenv binaries are always discoverable (docling, celery, uvicorn, etc.).
# This prevents subprocess-based checks (e.g., `docling --version`) from failing in worker processes.
if [ -d "${ROOT_DIR}/venv/bin" ]; then
    export PATH="${ROOT_DIR}/venv/bin:${PATH}"
fi

# Ports
FRONTEND_PORT=6601
BACKEND_PORT=6602
REDIS_PORT=6379

# Log rotation
LOG_MAX_BYTES=$((20 * 1024 * 1024))
LOG_BACKUP_COUNT=10

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================
# Helper Functions
# ============================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

wait_for_exit() {
    local pid="$1"
    local timeout="${2:-10}"
    local elapsed=0
    while kill -0 "$pid" > /dev/null 2>&1; do
        if [ "$elapsed" -ge "$timeout" ]; then
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 0
}

stop_pidfile_process() {
    local name="$1"
    local pidfile="$2"

    if [ ! -f "$pidfile" ]; then
        return 0
    fi

    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -z "${pid:-}" ]; then
        rm -f "$pidfile"
        return 0
    fi

    if kill -0 "$pid" > /dev/null 2>&1; then
        log_warning "Stopping stale ${name} process (PID: ${pid})..."
        kill -TERM "$pid" > /dev/null 2>&1 || true
        if ! wait_for_exit "$pid" 10; then
            log_warning "  ${name} did not stop with SIGTERM, sending SIGKILL..."
            kill -KILL "$pid" > /dev/null 2>&1 || true
        fi
        log_success "  ${name} stopped"
    fi

    rm -f "$pidfile"
}

resolve_python_cmd() {
    local preferred="$1"
    if [ -f "$preferred" ]; then
        echo "$preferred"
    else
        echo "python3"
    fi
}

start_logged_service() {
    local pidfile="$1"
    local logfile="$2"
    shift 2

    nohup "$LOG_WRAPPER_PYTHON" "$LOG_RUNNER" \
        --log-file "$logfile" \
        --max-bytes "$LOG_MAX_BYTES" \
        --backup-count "$LOG_BACKUP_COUNT" \
        -- "$@" > /dev/null 2>&1 &
    local pid=$!
    echo "$pid" > "$pidfile"
    echo "$pid"
}

# Check if Redis is running, start if needed
check_redis() {
    log_info "Checking Redis status..."

    if ! command -v redis-cli &> /dev/null; then
        log_error "redis-cli not found. Please install Redis."
        exit 1
    fi

    # Check if Redis is already running
    if redis-cli -p $REDIS_PORT ping > /dev/null 2>&1; then
        log_success "  Redis is already running on port $REDIS_PORT"
        return 0
    fi

    # Redis is not running, try to start it
    log_warning "  Redis is not running, attempting to start..."

    # Try systemctl first (most common)
    if command -v systemctl &> /dev/null; then
        if sudo systemctl start redis-server > /dev/null 2>&1 || sudo systemctl start redis > /dev/null 2>&1; then
            sleep 2
            # Verify Redis started
            if redis-cli -p $REDIS_PORT ping > /dev/null 2>&1; then
                log_success "  Redis started successfully via systemctl"
                return 0
            fi
        fi
    fi

    # Try service command (older systems)
    if command -v service &> /dev/null; then
        if sudo service redis-server start > /dev/null 2>&1 || sudo service redis start > /dev/null 2>&1; then
            sleep 2
            # Verify Redis started
            if redis-cli -p $REDIS_PORT ping > /dev/null 2>&1; then
                log_success "  Redis started successfully via service"
                return 0
            fi
        fi
    fi

    # Try direct redis-server command
    if command -v redis-server &> /dev/null; then
        log_info "  Trying to start Redis server directly..."
        redis-server --daemonize yes --port $REDIS_PORT > /dev/null 2>&1
        sleep 2
        # Verify Redis started
        if redis-cli -p $REDIS_PORT ping > /dev/null 2>&1; then
            log_success "  Redis started successfully as daemon"
            return 0
        fi
    fi

    # If we get here, Redis couldn't be started
    log_error "  Failed to start Redis automatically"
    log_error "  Please start Redis manually with one of:"
    log_error "    sudo systemctl start redis-server"
    log_error "    sudo service redis-server start"
    log_error "    redis-server --daemonize yes"
    exit 1
}

# Verify frontend build exists
check_frontend_build() {
    log_info "Checking frontend build..."

    local dist_dir="${ROOT_DIR}/frontend/dist"

    if [ ! -d "$dist_dir" ]; then
        log_error "Frontend build not found at: $dist_dir"
        log_error "Build the frontend first: cd frontend && npm run build"
        exit 1
    fi

    if [ ! -f "$dist_dir/index.html" ]; then
        log_error "index.html not found in: $dist_dir"
        log_error "Rebuild the frontend: cd frontend && npm run build"
        exit 1
    fi

    log_success "  Frontend build found"
}

# ============================================
# Main Script
# ============================================

echo ""
echo "============================================"
echo "  HLD Generator v2 - Production Startup"
echo "============================================"
echo ""

# Step 1: Create directories
log_info "Creating directories..."
mkdir -p "$LOG_DIR" "$PID_DIR"

if [ ! -f "$LOG_RUNNER" ]; then
    log_error "Log wrapper not found: $LOG_RUNNER"
    exit 1
fi

LOG_WRAPPER_PYTHON="$(resolve_python_cmd "${ROOT_DIR}/venv/bin/python")"

# Step 2: Stop existing services
log_info "STEP 1: Stopping existing services..."
echo ""

stop_pidfile_process "Backend" "${PID_DIR}/backend.pid"
stop_pidfile_process "Celery" "${PID_DIR}/celery.pid"
stop_pidfile_process "Frontend" "${PID_DIR}/frontend.pid"

# Stop any leftover listeners
log_info "Cleaning up ports..."
fuser -k ${FRONTEND_PORT}/tcp > /dev/null 2>&1 || true
fuser -k ${BACKEND_PORT}/tcp > /dev/null 2>&1 || true
pkill -f "celery -A celery_app worker" > /dev/null 2>&1 || true
sleep 1

log_success "All existing services stopped"
echo ""

# Step 3: Pre-flight checks
log_info "STEP 2: Running pre-flight checks..."
echo ""

check_redis
check_frontend_build

# Retain the script's historical root SQLite location unless a custom URL is set.
ENV_DATABASE_URL=""
if [ -f "${BACKEND_DIR}/.env" ]; then
    ENV_DATABASE_URL="$(sed -n 's/^DATABASE_URL=//p' "${BACKEND_DIR}/.env" | tail -n 1)"
fi
if [ -z "${DATABASE_URL:-}" ] && { [ -z "${ENV_DATABASE_URL}" ] || [ "${ENV_DATABASE_URL}" = "sqlite+aiosqlite:///./hld_generator.db" ]; }; then
    export DATABASE_URL="sqlite+aiosqlite:///${ROOT_DIR}/hld_generator.db"
fi
log_info "Using database configuration from backend/.env or environment"

echo ""
log_success "All pre-flight checks passed"
echo ""

# Step 4: Start services
log_info "STEP 3: Starting services..."
echo ""

# Start Backend (FastAPI with Uvicorn) on loopback
log_info "Starting Backend API on 127.0.0.1:${BACKEND_PORT}..."
cd "${BACKEND_DIR}"

# Check if venv exists, otherwise use system python3
PYTHON_CMD="$(resolve_python_cmd "../venv/bin/python")"

BACKEND_PID="$(start_logged_service "${PID_DIR}/backend.pid" "${LOG_DIR}/backend.log" \
    "$PYTHON_CMD" -m uvicorn main:app \
    --host 127.0.0.1 \
    --port ${BACKEND_PORT} \
    --workers 1)"
log_success "  Backend started (PID: $BACKEND_PID)"
cd "${ROOT_DIR}"
sleep 2

# Verify backend started
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    log_error "Backend failed to start. Check logs: ${LOG_DIR}/backend.log"
    exit 1
fi

# Start Celery Worker
log_info "Starting Celery Worker..."
cd "${BACKEND_DIR}"

if [ -f "../venv/bin/celery" ]; then
    CELERY_CMD="../venv/bin/celery"
else
    CELERY_CMD="celery"
fi

CELERY_PID="$(start_logged_service "${PID_DIR}/celery.pid" "${LOG_DIR}/celery.log" \
    "$CELERY_CMD" -A celery_app worker \
    --loglevel=info \
    --concurrency=10 \
    --pool=prefork \
    --max-tasks-per-child=10 \
    -Q celery,hld_generation)"
log_success "  Celery Worker started (PID: $CELERY_PID)"
cd "${ROOT_DIR}"
sleep 3

# Verify celery started
if ! kill -0 $CELERY_PID 2>/dev/null; then
    log_error "Celery Worker failed to start. Check logs: ${LOG_DIR}/celery.log"
    exit 1
fi

# Start Frontend Server on loopback
log_info "Starting Frontend Server on 127.0.0.1:${FRONTEND_PORT}..."

PYTHON_CMD="$(resolve_python_cmd "${ROOT_DIR}/venv/bin/python")"

FRONTEND_PID="$(start_logged_service "${PID_DIR}/frontend.pid" "${LOG_DIR}/frontend.log" \
    "$PYTHON_CMD" "${FRONTEND_SCRIPT}" \
    --host 127.0.0.1 \
    --port ${FRONTEND_PORT} \
    --backend-port ${BACKEND_PORT} \
    --backend-host localhost \
    --dist-dir frontend/dist)"
log_success "  Frontend started (PID: $FRONTEND_PID)"
sleep 2

# Verify frontend started
if ! kill -0 $FRONTEND_PID 2>/dev/null; then
    log_error "Frontend failed to start. Check logs: ${LOG_DIR}/frontend.log"
    exit 1
fi

echo ""
log_success "All services started successfully!"
echo ""

# Step 5: Display status
echo "============================================"
echo "  Service Status"
echo "============================================"
echo ""
echo "  Backend API:"
echo "    - PID: $BACKEND_PID"
echo "    - Local: http://127.0.0.1:${BACKEND_PORT}"
echo "    - API Docs: http://127.0.0.1:${BACKEND_PORT}/api/docs"
echo "    - Logs: ${LOG_DIR}/backend.log"
echo ""
echo "  Celery Worker:"
echo "    - PID: $CELERY_PID"
echo "    - Concurrency: 10 workers"
echo "    - Pool: prefork"
echo "    - Logs: ${LOG_DIR}/celery.log"
echo ""
echo "  Frontend:"
echo "    - PID: $FRONTEND_PID"
echo "    - Local: http://127.0.0.1:${FRONTEND_PORT}"
echo "    - Logs: ${LOG_DIR}/frontend.log"
echo ""
echo "  Redis:"
echo "    - Port: $REDIS_PORT"
echo ""
echo "  Database:"
echo "    - Configured in backend/.env or environment"
echo ""
echo "============================================"
echo "  Access Application"
echo "============================================"
echo ""

echo "  Local Access:"
echo "    http://127.0.0.1:${FRONTEND_PORT}"
echo "  For remote access, configure a TLS reverse proxy to this local port."
echo ""
echo "============================================"
echo "  Management Commands"
echo "============================================"
echo ""
echo "  Stop all services:"
echo "    ./stop_production.sh"
echo ""
echo "  View logs (live):"
echo "    tail -f ${LOG_DIR}/*.log"
echo ""
echo "  View specific logs:"
echo "    tail -f ${LOG_DIR}/backend.log"
echo "    tail -f ${LOG_DIR}/celery.log"
echo "    tail -f ${LOG_DIR}/frontend.log"
echo "    ls -lh ${LOG_DIR}/backend.log* ${LOG_DIR}/celery.log* ${LOG_DIR}/frontend.log*"
echo ""
echo "  Check service status:"
echo "    ps aux | grep -E 'uvicorn|celery|serve_frontend'"
echo ""
echo "============================================"
echo ""
