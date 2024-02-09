#! /bin/bash

# Exit immediately when a command fails.
set -e

# Make sure exit code are respected in a pipeline.
set -o pipefail

# Treat unset variables as an error an exit immediately.
set -u

# Extraction needs our django settings for jinja, so we need a django settings
# module set. Since this command is meant to be run in local envs, we use
# "settings".
DJANGO_SETTINGS_MODULE=settings

# gettext flags
CLEAN_FLAGS="--no-obsolete --width=200 --no-location"
MERGE_FLAGS="--update --width=200 --backup=none --no-fuzzy-matching"
UNIQ_FLAGS="--width=200"
DIFF_WITH_ONE_LINE_CHANGE="2 files changed, 2 insertions(+), 2 deletions(-)"

info() {
  local message="$1"

  echo ""
  echo "INFO: $message"
  echo ""
}

info "Extracting content strings..."
python3 manage.py extract_content_strings

info "Extracting strings from python..."
# We must set PYTHONPATH here because pybabel needs to be able to import our settings file from the root
PYTHONPATH=. DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE} pybabel extract -F babel.cfg -o locale/templates/LC_MESSAGES/django.pot -c 'L10n:' -w 80 --version=1.0 --project=addons-server --copyright-holder=Mozilla .
info "Extracting strings from javascript..."
PYTHONPATH=. DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE} pybabel extract -F babeljs.cfg -o locale/templates/LC_MESSAGES/djangojs.pot -c 'L10n:' -w 80 --version=1.0 --project=addons-server --copyright-holder=Mozilla .

pushd locale > /dev/null

git_diff_stat=$(git diff --shortstat)

if [[ -z "$git_diff_stat" ]] || [[ "$git_diff_stat" == *"$DIFF_WITH_ONE_LINE_CHANGE"* ]]; then
    info "No locale changes, nothing to update, ending process"
    git reset --hard
    exit 0
fi


info "Merging any new keys from templates/LC_MESSAGES/django.pot"
for i in `find . -name "django.po" | grep -v "en_US"`; do
    msguniq $UNIQ_FLAGS -o "$i" "$i"
    msgmerge $MERGE_FLAGS "$i" "templates/LC_MESSAGES/django.pot"
done
msgen templates/LC_MESSAGES/django.pot | msgmerge $MERGE_FLAGS en_US/LC_MESSAGES/django.po -

info "Merging any new keys from templates/LC_MESSAGES/djangojs.pot"
for i in `find . -name "djangojs.po" | grep -v "en_US"`; do
    msguniq $UNIQ_FLAGS -o "$i" "$i"
    msgmerge $MERGE_FLAGS "$i" "templates/LC_MESSAGES/djangojs.pot"
done
msgen templates/LC_MESSAGES/djangojs.pot | msgmerge $MERGE_FLAGS en_US/LC_MESSAGES/djangojs.po -

info "Cleaning out obsolete messages..."
for i in `find . -name "django.po"`; do
    msgattrib $CLEAN_FLAGS --output-file=$i $i
done
for i in `find . -name "djangojs.po"`; do
    msgattrib $CLEAN_FLAGS --output-file=$i $i
done

msgfilter -i sr/LC_MESSAGES/django.po -o sr_Latn/LC_MESSAGES/django.po recode-sr-latin

popd > /dev/null

info "Done extracting."
