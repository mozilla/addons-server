#!/bin/bash
# docker-entrypoint.sh
# Entrypoint script for ECS Fargate containers
#
# Service modes:
#   web          -- Run uWSGI Django application (default)
#   worker       -- Run Celery worker
#   versioncheck -- Run versioncheck uWSGI service
#   scheduler    -- Run Celery beat scheduler
#   shell        -- Drop into bash shell
#   manage       -- Run Django management command
#
# Usage examples:
#   docker run image web
#   docker run image worker --queues default,priority
#   docker run image manage migrate
#
set -e

# Colour codes for logging (disabled if not a TTY)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    NC=''
fi

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Default values (can be overridden by environment variables)
: "${UWSGI_PROCESSES:=4}"
: "${UWSGI_THREADS:=4}"
: "${UWSGI_PORT:=8000}"
: "${UWSGI_HARAKIRI:=30}"
: "${UWSGI_MAX_REQUESTS:=5000}"
: "${CELERY_CONCURRENCY:=4}"
: "${CELERY_QUEUES:=default,devhub,images,limited,priority,reviews}"
: "${CELERY_LOGLEVEL:=info}"
: "${DJANGO_SETTINGS_MODULE:=settings}"

export DJANGO_SETTINGS_MODULE

# Working directory
cd /data/olympia

# Function to run Django management commands
run_manage() {
    log_info "Running management command: $*"
    exec python3 manage.py "$@"
}

# Function to start uWSGI for web service
start_web() {
    log_info "Starting uWSGI web server..."
    log_info "Processes: ${UWSGI_PROCESSES}, Threads: ${UWSGI_THREADS}, Port: ${UWSGI_PORT}"

    # Update product details before starting
    python3 manage.py update_product_details || log_warn "Failed to update product details"

    exec uwsgi \
        --module=olympia.wsgi:django_app \
        --master \
        --http=0.0.0.0:${UWSGI_PORT} \
        --processes=${UWSGI_PROCESSES} \
        --threads=${UWSGI_THREADS} \
        --enable-threads \
        --offload-threads=2 \
        --harakiri=${UWSGI_HARAKIRI} \
        --max-requests=${UWSGI_MAX_REQUESTS} \
        --buffer-size=32768 \
        --limit-post=100000000 \
        --post-buffering=8192 \
        --http-timeout=20 \
        --http-connect-timeout=20 \
        --http-keepalive=1 \
        --thunder-lock \
        --single-interpreter \
        --need-app \
        --die-on-term \
        --vacuum \
        --ignore-sigpipe \
        --ignore-write-errors \
        --disable-write-exception \
        --log-5xx \
        --log-slow=1000 \
        --stats=:9191 \
        --stats-http \
        "$@"
}

# Function to start uWSGI for versioncheck service
start_versioncheck() {
    log_info "Starting uWSGI versioncheck server..."
    log_info "Processes: ${UWSGI_PROCESSES}, Threads: ${UWSGI_THREADS}, Port: ${UWSGI_PORT}"

    exec uwsgi \
        --module=services.wsgi.versioncheck:application \
        --master \
        --http-socket=0.0.0.0:${UWSGI_PORT} \
        --processes=${UWSGI_PROCESSES} \
        --threads=${UWSGI_THREADS} \
        --enable-threads \
        --offload-threads=2 \
        --max-requests=${UWSGI_MAX_REQUESTS} \
        --die-on-term \
        --vacuum \
        --ignore-sigpipe \
        --ignore-write-errors \
        --disable-write-exception \
        --stats=:9191 \
        --stats-http \
        "$@"
}

# Function to start Celery worker
start_worker() {
    log_info "Starting Celery worker..."
    log_info "Concurrency: ${CELERY_CONCURRENCY}, Queues: ${CELERY_QUEUES}, Loglevel: ${CELERY_LOGLEVEL}"

    exec celery \
        -A olympia.amo.celery \
        worker \
        --loglevel=${CELERY_LOGLEVEL} \
        --concurrency=${CELERY_CONCURRENCY} \
        -Q "${CELERY_QUEUES}" \
        "$@"
}

# Function to start Celery beat scheduler
start_scheduler() {
    log_info "Starting Celery beat scheduler..."

    exec celery \
        -A olympia.amo.celery \
        beat \
        --loglevel=${CELERY_LOGLEVEL} \
        "$@"
}

# Main entrypoint logic
main() {
    SERVICE_MODE="${1:-web}"

    log_info "Service mode: ${SERVICE_MODE}"
    log_info "Django settings: ${DJANGO_SETTINGS_MODULE}"

    case "${SERVICE_MODE}" in
        web)
            shift || true
            start_web "$@"
            ;;
        versioncheck)
            shift || true
            start_versioncheck "$@"
            ;;
        worker)
            shift || true
            start_worker "$@"
            ;;
        scheduler|beat)
            shift || true
            start_scheduler "$@"
            ;;
        shell)
            log_info "Starting shell..."
            exec /bin/bash
            ;;
        manage)
            shift
            run_manage "$@"
            ;;
        *)
            # If the command doesn't match a known service, run it directly
            log_info "Running command: $*"
            exec "$@"
            ;;
    esac
}

main "$@"
