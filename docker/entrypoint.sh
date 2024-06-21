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

echo "HOME:$HOME"
echo "HOST_UID:$HOST_UID"

if [[ -n "${HOST_UID:-}" && -n "${HOME:-}" ]]; then
  find $HOME -user $HOST_UID -exec chown $OLYMPIA_USER:$OLYMPIA_USER {} \;
fi

cat <<EOF | su -s /bin/bash $OLYMPIA_USER
  echo "Running command as ${OLYMPIA_USER}"
  set -xue
  $@
EOF
