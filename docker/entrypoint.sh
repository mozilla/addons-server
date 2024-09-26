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

function get_olympia_uid() { echo "$(id -u "$OLYMPIA_USER")"; }
function get_olympia_gid() { echo "$(id -g "$OLYMPIA_USER")"; }

# If the host user's uid is not the same as the olympia user's uid
# change the olympia user's uid to the host user's uid and
# change the ownership of the /data/olympia directory to the olympia user.
# This is necessary when using a remote image that was built with a different UID
# than the current host user's uid.
IMAGE_UID="$(get_olympia_uid)"
if [[ -n "${HOST_UID:-}" && "${HOST_UID}" != "${IMAGE_UID}" ]]; then
  echo "${OLYMPIA_USER} UID: ${IMAGE_UID} -> ${HOST_UID}"
  usermod -u ${HOST_UID} ${OLYMPIA_USER}
  chown -R ${OLYMPIA_USER} /data/olympia
fi

cat <<EOF | su -s /bin/bash $OLYMPIA_USER
  echo "Running command as ${OLYMPIA_USER} $(get_olympia_uid):$(get_olympia_gid)"
  set -xue
  $@
EOF
