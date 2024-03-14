#! /bin/bash

# Exit immediately when a command fails.
set -e

# Make sure exit code are respected in a pipeline.
set -o pipefail

# Treat unset variables as an error an exit immediately.
set -u

ROBOT_EMAIL="addons-dev-automation+github@mozilla.com"
ROBOT_NAME="Mozilla Add-ons Robot"

DATE=$(date -u +%Y-%m-%d)
REV=$(git rev-parse --short HEAD)
MESSAGE="Extracted l10n messages from $DATE at $REV"

DRY_RUN=true

if [[ "${1:-}" != "--dry-run" ]]; then
  DRY_RUN=false
fi

# IF there are no uncommitted local changes, exit early.
if [[ -z "$(git status --porcelain)" ]]; then
  echo """
    There are no uncommited changes in the working directory.
    Run make extract_locales to extract the locales first.
  """
  exit 0
fi

if [[ $DRY_RUN == true ]]; then
  echo "Dry running..."
  echo "git config --global user.name \"$ROBOT_NAME\""
  echo "git config --global user.email \"$ROBOT_EMAIL\""
  echo "git commit -a -m \"$MESSAGE\""
  echo "git push"
else
  git config --global user.name "$ROBOT_NAME"
  git config --global user.email "$ROBOT_EMAIL"
  git commit -a -m "$MESSAGE"
  git push
fi
