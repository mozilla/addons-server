#!/bin/bash

set -ue

requirements_file="${PWD}/requirements/$1"

# Check if a file at ${PWD}/requirements/${requirements_file} exists
if [ ! -f "$requirements_file" ]; then
    echo "File ${requirements_file} does not exist."
    exit 1
else
    echo "Checking Packages for Requirements File ${requirements_file}."
fi

# Extract package names from the file
packages=$(grep -oP '^[a-zA-Z0-9\-_]+(?==)' "${requirements_file}")

# Check each package
for package in $packages; do
  output=$(pip show $package)
  if [[ $output == *"not found"* ]]; then
    echo $output
    exit 1
  else
    echo "Package: $package is installed."
  fi
done

echo "All packages are installed."
