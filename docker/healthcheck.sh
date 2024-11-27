#!/bin/bash

set -ue

worker_healthcheck() {
  if DJANGO_SETTINGS_MODULE=olympia celery -A olympia.amo.celery status; then
    echo "Celery worker is running"
    return 0
  else
    echo "Celery worker is not running"
    return 1
  fi
}

web_healthcheck() {
  if curl --fail --show-error --include --location http://127.0.0.1:8002/__version__ > /dev/null; then
    echo "uWSGI is running"
    return 0
  else
    echo "uWSGI is not running"
    return 1
  fi
}

worker_healthcheck &
worker_pid=$!

web_healthcheck &
web_pid=$!

# Wait for both processes to complete
wait $worker_pid
worker=$?

wait $web_pid
web=$?

if [[ $worker -eq 0 && $web -eq 0 ]]; then
  echo "Healthcheck passed"
  exit 0
else
  echo "Healthcheck failed"
  echo "worker: $worker"
  echo "web: $web"
  exit 1
fi
