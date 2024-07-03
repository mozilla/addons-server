#!/bin/bash

set -ue

# Load environment variables from .env file
# This gives us access to DOCKER_TAG
if [ -f .env ]; then
  source .env
else
  echo ".env file not found! Run 'make setup' first"
  exit 1
fi

# Docker tag determines how we will load the image
# @<digest> - pull the image
# :<!local> - pull the image
# :local - build the image
DOCKER_TAG="${DOCKER_TAG}"

# GH_* indicates we are downloading a CI image
# these are not pushed to a registry but can be downloaded via the gh cli
GH_RUN_ID="${GH_RUN_ID:-}"
GH_ARTIFACT_NAME="${GH_ARTIFACT_NAME:-}"

cat <<EOF
DOCKER_TAG: ${DOCKER_TAG}
GH_RUN_ID: ${GH_RUN_ID}
GH_ARTIFACT_NAME: ${GH_ARTIFACT_NAME}
EOF

if [ -n "${GH_RUN_ID}" ] && [ -n "${GH_ARTIFACT_NAME}" ]; then
echo "Downloading image from Github Actions Artifact"

timeout=120
max_attempts=5
attempt_num=0
success=false

function download() {
  make download_docker_image \
    GH_RUN_ID="${GH_RUN_ID}" \
    GH_ARTIFACT_NAME="${GH_ARTIFACT_NAME}"
}

export -f download

while [ $success = false ] && [ $attempt_num -le $max_attempts ]; do
  attempt_num=$(( attempt_num + 1 ))
  if timeout $timeout bash -c download; then
    success=true
  else
    delay=$(( 2 ** (attempt_num - 1) ))
    echo "Attempt $attempt_num failed. Trying again in $delay seconds..."
    sleep $delay
  fi
done

if [ $success = false ]; then
  echo "All attempts failed."
  exit 1
fi

elif [[ "$DOCKER_TAG" == *":local" ]]; then
echo "Building image locally"

make build_docker_image

else
echo "Pulling image from docker registry"

docker pull --platform linux/amd64 ${DOCKER_TAG}

fi
