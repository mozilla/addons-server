#! /bin/bash

# Exit immediately when a command fails.
set -e

# Make sure exit code are respected in a pipeline.
set -o pipefail

# Treat unset variables as an error an exit immediately.
set -u

ROBOT_EMAIL="addons-dev-automation+github@mozilla.com"
ROBOT_NAME="Mozilla Add-ons Robot"

REV=$(git rev-parse --short HEAD)
MESSAGE="Extracted l10n messages from $(date -u --iso-8601=date) at $REV"
BRANCH_NAME="l10n-extract-$(date -u --iso-8601=date)-$REV"

GITHUB_TOKEN="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"

info() {
  local message="$1"

  echo ""
  echo "INFO: $message"
  echo ""
}

error() {
  local message="$1"

  echo "ERROR: $message"
  exit 1
}


function generate_post_data()
{
  cat <<EOF
{
    "title": "$MESSAGE",
    "head": "$BRANCH_NAME",
    "base":"master"
}
EOF
}

function create_pull_request {
    info "Pushing the branch..."
    git push -q "https://addons-robot:$GITHUB_TOKEN@github.com/mozilla/addons-server/"
    info "Creating the auto merge pull request for $BRANCH_NAME ..."
    curl --verbose -H "Authorization: token $GITHUB_TOKEN" --data "$(generate_post_data)" "https://api.github.com/repos/mozilla/addons-server/pulls"
    info "Pull request created."
}


info "Creating and switching to branch '$BRANCH_NAME'"
git checkout -b "$BRANCH_NAME"
info "Committing..."
git -c user.name="$ROBOT_NAME" -c user.email="$ROBOT_EMAIL" commit -m "$MESSAGE" --author "$ROBOT_NAME <$ROBOT_EMAIL>" --no-gpg-sign locale/*/LC_MESSAGES/*.po locale/templates/
info "Committed locales extraction to local branch."

# This script is meant to be run inside a virtualenv or inside our docker
# container. If it's the latter, it doesn't necessarily have access to the ssh
# config, therefore we can't reliably push and create a pull request without a
# GitHub API token.
if [[ -z "${GITHUB_TOKEN-}" ]]; then
  info "No github token present. You should now go back to your normal environment to push this branch and create the pull request."
else
  create_pull_request
fi

