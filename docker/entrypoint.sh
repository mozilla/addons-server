#!/bin/bash

### This is the entrypoint script used for local and CI environments
### It allows the web/worker containers to be run as root, but execute
### the commands as the olympia user. This is necessary because the
### id of the olympia user sometimes should match the host user's id
### to avoid permission issues with mounted volumes.

set -ue

if [[ $(id -u) -ne 0 ]]; then
  echo "This script must be run as root"
  exit 1
fi

OLYMPIA_USER="olympia"

if [[ -n "${HOST_UID:-}" ]]; then
  usermod -u ${HOST_UID} ${OLYMPIA_USER}
  echo "${OLYMPIA_USER} UID: ${OLYMPIA_UID} -> ${HOST_UID}"
fi

uid=$(id -u $OLYMPIA_USER)
gid=$(id -g $OLYMPIA_USER)

cat <<EOF | su -s /bin/bash $OLYMPIA_USER
  echo "Running command as ${OLYMPIA_USER} ${uid}:${gid}"
  set -xue
  $@
EOF
