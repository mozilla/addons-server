#!/bin/sh
# Example usage:
#
# $ docker build -t amoloadtests:latest -f Dockerfile.perftests
# $ docker run -ti -e LOCUST_OPTS="-c 1 --no-web" \
#   -e ATTACKED_HOST="https://addons.allizom.org" \
#   amoloadtests:latest
#   /code//tests/performance/run-locust.sh

set -e
LOCUST_MODE=${LOCUST_MODE:-standalone}
LOCUST_MASTER_BIND_PORT=${LOCUST_MASTER_BIND_PORT:-5557}
CURRENT_FOLDER=$(dirname $(realpath $0))
DEFAULT_LOCUST_FILE="$CURRENT_FOLDER/locustfile.py"
LOCUST_FILE=${LOCUST_FILE:-$DEFAULT_LOCUST_FILE}

if [ -z ${ATTACKED_HOST+x} ] ; then
    echo "You need to set the URL of the host to be tested (ATTACKED_HOST)."
    exit 1
fi

LOCUST_OPTS="-f ${LOCUST_FILE} --host=${ATTACKED_HOST} --no-reset-stats $LOCUST_OPTS"

case `echo ${LOCUST_MODE} | tr 'a-z' 'A-Z'` in
"MASTER")
    LOCUST_OPTS="--master --master-bind-port=${LOCUST_MASTER_BIND_PORT} $LOCUST_OPTS"
    ;;
"SLAVE")
    LOCUST_OPTS="--slave --master-host=${LOCUST_MASTER} --master-port=${LOCUST_MASTER_BIND_PORT} $LOCUST_OPTS"
    if [ -z ${LOCUST_MASTER+x} ] ; then
        echo "You need to set LOCUST_MASTER."
        exit 1
    fi
    ;;
esac

locust ${LOCUST_OPTS}
