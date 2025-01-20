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

OLD_HOST_UID=$(get_olympia_uid)

# If the olympia user's uid is different in the container than from the build,
# we need to update the olympia user's uid to match the new one.
if [[ "${HOST_UID}" != "${OLD_HOST_UID}" ]]; then
  usermod -u ${HOST_UID} ${OLYMPIA_USER}
  echo "${OLYMPIA_USER} UID: ${OLD_HOST_UID} -> ${HOST_UID}"
fi

NEW_HOST_UID=$(get_olympia_uid)
OLYMPIA_ID_STRING="${NEW_HOST_UID}:$(get_olympia_gid)"

cat <<EOF | su -s /bin/bash $OLYMPIA_USER
  echo "Running command as ${OLYMPIA_USER} ${OLYMPIA_ID_STRING}"
  set -xue
  $@
EOF
