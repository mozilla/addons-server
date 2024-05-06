#!/bin/bash

set -ue

while IFS= read -r package; do
  package=$(echo "$package" | tr -d '[:space:]') # Remove whitespace from package name
  if ! dpkg -s "$package" >/dev/null 2>&1; then
    echo "$package is missing."
    exit 1
  else
    echo "$package installed."
  fi
done <  <(grep -v '^#' docker/debian_packages.txt)

echo "All required packages are present."
