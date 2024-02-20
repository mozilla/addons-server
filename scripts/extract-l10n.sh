#! /bin/bash
#
# This script will do the following:
#   - checkout and update git master branch
#   - create a new branch (name should look like l10n-extract-<date>-<rev>)
#   - Extract new strings and update the .po/.pot files
#   - Commit that extraction to the branch
#
# If you provide a GITHUB_TOKEN variable to the environment then this script
# can also automatically push to a remote branch and create a pull request for
# you through addons-robot. Ask @diox or @muffinresearch for this token.

# Exit immediately when a command fails.
set -e

# Make sure exit code are respected in a pipeline.
set -o pipefail

# Treat unset variables as an error an exit immediately.
set -u

INITIAL_GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
GIT_CHANGES=$(git status --porcelain)
GIT_REMOTE="https://github.com/mozilla/addons-server.git"  # Upstream.
REV=""
MESSAGE=""
BRANCH_NAME=""
ROBOT_EMAIL="addons-dev-automation+github@mozilla.com"
ROBOT_NAME="Mozilla Add-ons Robot"

DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
fi

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
    # Detect local (uncommitted) changes.
    if [[ ! -z "$GIT_CHANGES" ]]; then
      error "You have local changes, therefore this script cannot continue."
    fi

    # Switch to the `master` branch if we are not on it already.
    if [[ "$INITIAL_GIT_BRANCH" != "master" ]]; then
      git checkout master
    fi

    # Make sure the 'master' branch is up-to-date.
    git pull "$GIT_REMOTE" master

    REV=$(git rev-parse --short HEAD)
    MESSAGE="Extracted l10n messages from $(date -u --iso-8601=date) at $REV"
    BRANCH_NAME="l10n-extract-$(date -u --iso-8601=date)-$REV"

    # Ensure the branch to extract the locales is clean.
    if [[ $(git branch --list "$BRANCH_NAME") ]]; then
      info "Deleting branch '$BRANCH_NAME' because it already exists"
      git branch -D "$BRANCH_NAME"
    fi

    info "Creating and switching to branch '$BRANCH_NAME'"
    git checkout -b "$BRANCH_NAME"

    make -f Makefile-docker update_deps
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
    git push -q "https://addons-robot:$GITHUB_TOKEN@github.com/mozilla/addons-server/"
    info "Creating the auto merge pull request for $BRANCH_NAME ..."
    curl --verbose -H "Authorization: token $GITHUB_TOKEN" --data "$(generate_post_data)" "https://api.github.com/repos/mozilla/addons-server/pulls"
    info "Pull request created."
}

if [[ $DRY_RUN == true ]]; then
  info "Dry run only. Not committing."
else
  info "This script will extract new strings and update the .po/.pot files."

  init_environment
fi

./scripts/run_l10n_extraction.sh

if [[ $DRY_RUN == false ]]; then
  commit

  # This script is meant to be run inside a virtualenv or inside our docker
  # container. If it's the latter, it doesn't necessarily have access to the ssh
  # config, therefore we can't reliably push and create a pull request without a
  # GitHub API token.
  if [[ -z "${GITHUB_TOKEN-}" ]]; then
    info "No github token present. You should now go back to your normal environment to push this branch and create the pull request."
  else
    create_pull_request
  fi
fi

