#! /bin/bash
# This script is supposed to be running automatically via travis cronjobs.
# It's also possible to be run manually if necessary.
#
# This script will do the following:
#   - prepare git credentials for pull request push
#   - create a new branch (l10n-extract-2017-08-24-0b3bcaf2ca)
#   - Update your code
#   - Extract new strings and push to the .po files
#
# For the fully automated experience make sure to expose
# the following variables to the environment:
#   - GITHUB_TOKEN (to the github token of addons-robot,
#                   talk to @diox or @muffinresearch)
#   - TRAVIS_REPO_SLUG="mozilla/addons-server"
#   - TRAVIS_BRANCH="master"

set -o errexit -o nounset

REV=$(git rev-parse --short HEAD)
MESSAGE="Extracted l10n messages from $(date -u --iso-8601=date) at $REV"
BRANCH_NAME="l10n-extract-$(date -u --iso-8601=date)-$REV"
ROBOT_EMAIL="addons-dev-automation+github@mozilla.com"
ROBOT_NAME="Mozilla Add-ons Robot"

# gettext flags
CLEAN_FLAGS="--no-obsolete --width=200 --no-location"
MERGE_FLAGS="--update --width=200 --backup=none"
UNIQ_FLAGS="--width=200"

function init_environment {
    git checkout master
    git checkout -b "$BRANCH_NAME"

    make -f Makefile-docker install_python_test_dependencies
    make -f Makefile-docker install_node_js
}


function extract_locales {
    python manage.py extract_content_strings
    python manage.py extract

    pushd locale > /dev/null

    echo "Merging any new keys..."
    for i in `find . -name "django.po" | grep -v "en_US"`; do
        msguniq $UNIQ_FLAGS -o "$i" "$i"
        msgmerge $MERGE_FLAGS "$i" "templates/LC_MESSAGES/django.pot"
    done
    msgen templates/LC_MESSAGES/django.pot | msgmerge $MERGE_FLAGS en_US/LC_MESSAGES/django.po -

    echo "Merging any new javascript keys..."
    for i in `find . -name "djangojs.po" | grep -v "en_US"`; do
        msguniq $UNIQ_FLAGS -o "$i" "$i"
        msgmerge $MERGE_FLAGS "$i" "templates/LC_MESSAGES/djangojs.pot"
    done
    msgen templates/LC_MESSAGES/djangojs.pot | msgmerge $MERGE_FLAGS en_US/LC_MESSAGES/djangojs.po -

    echo "Cleaning out obsolete messages.  See bug 623634 for details."
    for i in `find . -name "django.po"`; do
        msgattrib $CLEAN_FLAGS --output-file=$i $i
    done
    for i in `find . -name "djangojs.po"`; do
        msgattrib $CLEAN_FLAGS --output-file=$i $i
    done

    msgfilter -i sr/LC_MESSAGES/django.po -o sr_Latn/LC_MESSAGES/django.po recode-sr-latin

    popd > /dev/null

    echo "done."
}

function git_commit {
    git commit -m "$MESSAGE" --author "$ROBOT_NAME <$ROBOT_EMAIL>" --no-gpg-sign locale/*/LC_MESSAGES/*.po locale/templates/
}

function git_push {
    git push -q "https://addons-robot:$GITHUB_TOKEN@github.com/$TRAVIS_REPO_SLUG/"
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


function create_auto_pull_request {
    CREATE_PULL_REQUEST_URL="https://api.github.com/repos/$TRAVIS_REPO_SLUG/pulls"
    echo "Creating the auto merge pull request for $BRANCH_NAME ..."
    curl --verbose -H "Authorization: token $GITHUB_TOKEN" --data "$(generate_post_data)" $CREATE_PULL_REQUEST_URL
    echo "auto merge pull request is created ..."
}

init_environment

extract_locales

git_commit

if [ "GITHUB_TOKEN" = "" ]
then
    echo "No Github token provided, you'll have to push the branch and create the pull request yourself."
else
    if [ "$TRAVIS_BRANCH" != "master" ]; then
      echo "This commit was made against the $TRAVIS_BRANCH and not the master! No extract!"
      exit 0
    fi
    git_push

    create_auto_pull_request
fi


