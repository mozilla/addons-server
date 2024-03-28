#!/bin/bash

if [[ ! -f '/addons-server-docker-container' ]]; then
  echo """
  ERROR: This script must be run inside the docker container.

  Try running your command via a make target, e.g.:

  $(make)

  """
  exit 1
fi
