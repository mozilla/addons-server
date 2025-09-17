#! /bin/bash

# Exit immediately when a command fails.
set -e

# Make sure exit code are respected in a pipeline.
set -o pipefail

# Treat unset variables as an error an exit immediately.
set -u

set -x

info() {
  local message="$1"

  echo ""
  echo "INFO: $message"
  echo ""
}

ROBOT_EMAIL="addons-dev-automation+github@mozilla.com"
ROBOT_NAME="Mozilla Add-ons Robot"

# Set git committer/author to the robot.
export GIT_AUTHOR_NAME="$ROBOT_NAME"
export GIT_AUTHOR_EMAIL="$ROBOT_EMAIL"
export GIT_COMMITTER_NAME="$ROBOT_NAME"
export GIT_COMMITTER_EMAIL="$ROBOT_EMAIL"

DATE=$(date -u +%Y-%m-%d)
REV=$(git rev-parse --short HEAD)
MESSAGE="Extracted l10n messages from $DATE at $REV"
DIFF_WITH_ONE_LINE_CHANGE="2 files changed, 2 insertions(+), 2 deletions(-)"

git_diff_stat=$(git diff --shortstat locale/templates/LC_MESSAGES)

info "git_diff_stat: $git_diff_stat"

# IF there are no uncommitted local changes, exit early.
if [[ -z "$git_diff_stat" ]] || [[ "$git_diff_stat" == *"$DIFF_WITH_ONE_LINE_CHANGE"* ]]; then
  info """
    No substantial changes to l10n strings found. Exiting the process.
  """
  exit 0
fi

info """
GIT_AUTHOR_NAME: $GIT_AUTHOR_NAME
GIT_AUTHOR_EMAIL: $GIT_AUTHOR_EMAIL
GIT_COMMITTER_NAME: $GIT_COMMITTER_NAME
GIT_COMMITTER_EMAIL: $GIT_COMMITTER_EMAIL

This script passes arguments directly to Git commands. We can pass --dry-run to test this script.
Without actually committing or pushing. Make sure to only pass arguments supported on both commit
and push.

ARGS: $@
"""

git commit -am "$MESSAGE" "$@"


if [[ "$@" =~ '--dry-run' ]]; then
  info """
    Skipping 'git push' because '--dry-run' is in ARGS so we should not have git credentials.
  """
  exit 0
fi

git push "$@"
