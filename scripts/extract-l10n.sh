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

    make -f Makefile-docker install_python_dev_dependencies
    make -f Makefile-docker install_node_js
}

if [[ $DRY_RUN == true ]]; then
  info "Dry run only. Not committing."
else
  info "This script will extract new strings and update the .po/.pot files."

  init_environment
fi

./scripts/run_l10n_extraction.sh

if [[ $DRY_RUN == false ]]; then
  ./scripts/push_l10n_extraction.sh
fi

