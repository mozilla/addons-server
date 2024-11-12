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

if [[ -n "${HOST_UID:-}" ]]; then
  usermod -u ${HOST_UID} ${OLYMPIA_USER}
  echo "${OLYMPIA_USER} UID: ${OLYMPIA_UID} -> ${HOST_UID}"
fi

# TODO: this doesn't work but we have to check if the image we built is production
# but we are for some reason trying to run it using development dependencies.
# this is pretty typical for CI... we could consider just building ci images though as a simpler solution. It's just nice to test the image you already pushed cause muh CI/CD...
if [[ "${DOCKER_VERSION:-}" != 'local' && "${DOCKER_TARGET:-}" == 'production' ]]; then
  echo "Running remote image. Re-installing with development dependencies..."
  rm -rf /deps
  mkdir -p /deps
  chown -R ${get_olympia_uid}:${get_olympia_gid} /deps
  su -s /bin/bash $OLYMPIA_USER -c "make update_deps"
fi

cat <<EOF | su -s /bin/bash $OLYMPIA_USER
  echo "Running command as ${OLYMPIA_USER} $(get_olympia_uid):$(get_olympia_gid)"
  set -xue
  $@
EOF
