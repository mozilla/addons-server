#! /bin/bash

# Exit immediately when a command fails.
set -e

# Make sure exit code are respected in a pipeline.
set -o pipefail

# Treat unset variables as an error an exit immediately.
set -u

CURRENT_EMAIL=$(git config --get user.email)
CURRENT_USER=$(git config --get user.name)
ROBOT_EMAIL="addons-dev-automation+github@mozilla.com"
ROBOT_NAME="Mozilla Add-ons Robot"

DATE=$(date -u +%Y-%m-%d)
REV=$(git rev-parse --short HEAD)
MESSAGE="Extracted l10n messages from $DATE at $REV"
DIFF_WITH_ONE_LINE_CHANGE="2 files changed, 2 insertions(+), 2 deletions(-)"

DRY_RUN=true

if [[ "${1:-}" != "--dry-run" ]]; then
  DRY_RUN=false
fi

git_diff_stat=$(git diff --shortstat locale/templates/LC_MESSAGES)

echo "git_diff_stat: $git_diff_stat"

# IF there are no uncommitted local changes, exit early.
if [[ -z "$git_diff_stat" ]] || [[ "$git_diff_stat" == *"$DIFF_WITH_ONE_LINE_CHANGE"* ]]; then
  echo """
    No substantial changes to l10n strings found. Exiting the process.
  """
  exit 0
fi

if [[ $DRY_RUN == true ]]; then
  echo "Dry running..."
  echo "git config --global user.name \"$ROBOT_NAME\""
  echo "git config --global user.email \"$ROBOT_EMAIL\""
  echo "git commit -a -m \"$MESSAGE\""
  echo "git push"
  echo "git config --global user.name \"$CURRENT_USER\""
  echo "git config --global user.email \"$CURRENT_EMAIL\""
else
  # Commit the changes and push them to the repository.
  git config --global user.name "$ROBOT_NAME"
  git config --global user.email "$ROBOT_EMAIL"
  git commit -a -m "$MESSAGE"
  git push
  # Reset the user name and email to the original values.
  git config --global user.name "$CURRENT_USER"
  git config --global user.email "$CURRENT_EMAIL"
fi
