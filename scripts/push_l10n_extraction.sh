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
  echo "git commit --author=\"$ROBOT_NAME <$ROBOT_EMAIL>\" -a -m \"$MESSAGE\""
  echo "git push"
else
  # Commit the changes and push them to the repository.
  git commit --author="$ROBOT_NAME <$ROBOT_EMAIL>" -a -m "$MESSAGE"
  git push
fi
