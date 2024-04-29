#!/bin/bash

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
