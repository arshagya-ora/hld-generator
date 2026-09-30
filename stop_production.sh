#!/bin/bash
# ============================================
# HLD Generator v2 - Production Stop Script
# Stops: Frontend | Backend | Celery Worker
# Updated: 2026-03-16
# ============================================

set -euo pipefail

# ============================================
# Configuration
# ============================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="${ROOT_DIR}/run"
LOG_DIR="${ROOT_DIR}/logs"
LOG_RUNNER="${ROOT_DIR}/shared/run_with_log_rotation.py"

# Ports
FRONTEND_PORT=6601
BACKEND_PORT=6602

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
        log_info "${name}: No PID file found"
        return 0
    fi

    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -z "${pid:-}" ]; then
        log_warning "${name}: PID file empty, removing"
        rm -f "$pidfile"
        return 0
    fi

    if ! kill -0 "$pid" > /dev/null 2>&1; then
        log_warning "${name}: Process not running (PID: ${pid})"
        rm -f "$pidfile"
        return 0
    fi

    log_info "${name}: Stopping process (PID: ${pid})..."

    # Try graceful shutdown first (SIGTERM)
    kill -TERM "$pid" > /dev/null 2>&1 || true

    if wait_for_exit "$pid" 10; then
        log_success "  ${name} stopped gracefully"
    else
        log_warning "  ${name} did not stop, force killing..."
        kill -KILL "$pid" > /dev/null 2>&1 || true
        sleep 1
        log_success "  ${name} force killed"
    fi

    rm -f "$pidfile"
}

cleanup_log_wrappers() {
    if pkill -f "$LOG_RUNNER" > /dev/null 2>&1; then
        log_warning "  Killed remaining log rotation wrappers"
        sleep 1
    fi
}

# ============================================
# Main Script
# ============================================

echo ""
echo "============================================"
echo "  HLD Generator v2 - Stopping Services"
echo "============================================"
echo ""

log_info "Stopping services..."
echo ""

# Stop in reverse order: Frontend -> Celery -> Backend
stop_pidfile_process "Frontend" "${PID_DIR}/frontend.pid"
stop_pidfile_process "Celery Worker" "${PID_DIR}/celery.pid"
stop_pidfile_process "Backend API" "${PID_DIR}/backend.pid"

echo ""
log_info "Cleaning up leftover processes..."

# Kill any remaining processes on ports
if fuser -k ${FRONTEND_PORT}/tcp > /dev/null 2>&1; then
    log_warning "  Killed process on port ${FRONTEND_PORT} (Frontend)"
fi

if fuser -k ${BACKEND_PORT}/tcp > /dev/null 2>&1; then
    log_warning "  Killed process on port ${BACKEND_PORT} (Backend)"
fi

# Kill any remaining celery workers
if pkill -f "celery -A celery_app worker" > /dev/null 2>&1; then
    log_warning "  Killed remaining Celery workers"
    sleep 1
fi

cleanup_log_wrappers

echo ""
log_success "All services stopped!"
echo ""

# Verification
echo "============================================"
echo "  Verification"
echo "============================================"
echo ""

if lsof -i:${FRONTEND_PORT} > /dev/null 2>&1; then
    log_warning "Port ${FRONTEND_PORT} (Frontend) still in use"
else
    log_success "Port ${FRONTEND_PORT} (Frontend) is free"
fi

if lsof -i:${BACKEND_PORT} > /dev/null 2>&1; then
    log_warning "Port ${BACKEND_PORT} (Backend) still in use"
else
    log_success "Port ${BACKEND_PORT} (Backend) is free"
fi

if pgrep -f "celery.*worker" > /dev/null 2>&1; then
    log_warning "Celery workers still running"
else
    log_success "No Celery workers running"
fi

if pgrep -f "$LOG_RUNNER" > /dev/null 2>&1; then
    log_warning "Log rotation wrappers still running"
else
    log_success "No log rotation wrappers running"
fi

echo ""
echo "============================================"
echo "  Logs retained in: ${LOG_DIR}"
echo "  Rotated logs: backend.log.1, celery.log.1, frontend.log.1, etc."
echo "============================================"
echo ""
echo "============================================"
echo "  To restart: ./start_production.sh"
echo "============================================"
echo ""
