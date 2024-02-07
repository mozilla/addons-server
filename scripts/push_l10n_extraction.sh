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
BRANCH_NAME="l10n-extract-$DATE-$REV"

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

function init_environment {
  # IF there are no uncommitted local changes, exit early.
  if [[ -z "$(git status --porcelain)" ]]; then
    error """
      There are no uncommited changes in the working directory.
      Run make extract_locales to extract the locales first.
    """
  fi

  if [[ -z "${GITHUB_TOKEN-}" ]]; then
    error "No github token present. Cannot create pull request"
  fi

  info "This script will commit the extracted locales to a new branch and create a pull request."
  info "Branch name: $BRANCH_NAME"
  info "Commit message: '$MESSAGE'"

  # Ensure the branch to extract the locales is clean.
  if [[ $(git branch --list "$BRANCH_NAME") ]]; then
    info "Deleting branch '$BRANCH_NAME' because it already exists"
    git branch -D "$BRANCH_NAME"
  fi

  info "Creating and switching to branch '$BRANCH_NAME'"
  git checkout -b "$BRANCH_NAME"
}

function commit {
  info "Committing..."
  git -c user.name="$ROBOT_NAME" -c user.email="$ROBOT_EMAIL" commit -m "$MESSAGE" --author "$ROBOT_NAME <$ROBOT_EMAIL>" --no-gpg-sign locale/*/LC_MESSAGES/*.po locale/templates/
  info "Committed locales extraction to local branch."
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
  git push -u origin "$BRANCH_NAME"
  info "Creating the auto merge pull request for $BRANCH_NAME ..."
  curl --verbose -H "Authorization: token $GITHUB_TOKEN" --data "$(generate_post_data)" "https://api.github.com/repos/mozilla/addons-server/pulls"
  info "Pull request created."
}


init_environment
commit
create_pull_request


