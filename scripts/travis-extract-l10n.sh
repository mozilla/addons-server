#! /bin/bash
# This script is supposed to be running automatically via travis cronjobs.
#
# This script will do the following:
#   - prepare git credentials for pull request push
#   - create a new branch (l10n-extract-2017-08-24-0b3bcaf2ca)
#   - Update your code
#   - Extract new strings and push to the .po files
#
# This script makes a lot of assumptions and has no error checking, so read it
# over before you run it.

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
DEBUG_LOCALES="dbl dbr"


function init_environment {
    echo "machine github.com login $GITHUB_TOKEN password x-oauth-basic" >> ~/.netrc
    chmod 0600 ~/.netrc

    git config --global user.email "$ROBOT_EMAIL"
    git config --global user.name "$ROBOT_NAME"
    git remote set-url --push origin "https://addons-robot:$GITHUB_TOKEN@github.com/$TRAVIS_REPO_SLUG/"
    git checkout -b "$BRANCH_NAME"

    make -f Makefile-docker install_python_dependencies
    make -f Makefile-docker install_node_js
}


function extract_locales {
    python manage.py extract

    pushd locale > /dev/null

    for debugLocale in $DEBUG_LOCALES; do
        for domain in django djangojs; do
            if [ "$debugLocale" == "dbr" ]; then
                rewrite="mirror"
            else
                rewrite="unicode"
            fi

            echo "generating debug locale '$debugLocale' for '$domain' using '$rewrite'"

            npm run potools debug -- --format "$rewrite" "locale/templates/LC_MESSAGES/$domain.pot" --output "locale/$debugLocale/LC_MESSAGES/$domain.po"
        done
    done

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


function commit_and_push {
    git add -A .
    git commit -m "$MESSAGE"
    git push -q origin
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



# if [ "$TRAVIS_BRANCH" != "master" ]
# then
#   echo "This commit was made against the $TRAVIS_BRANCH and not the master! No extract!"
#   exit 0
# fi

# if [ "GITHUB_TOKEN" == "" ]
# then
#     echo "Must provide github token"
#     exit 0
# fi

# init_environment

# extract_locales

commit_and_push

create_auto_pull_request
