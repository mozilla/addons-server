#! /bin/bash

# This script will do the following:
#   - Update your code
#   - Extract new strings and push to the .po files
#   - Compile all .po files
#   - Commit all your changes
#   - Email the l10n list
#
# This script makes a lot of assumptions and has no error checking, so read it
# over before you run it.
#
# Questions?  Talk to clouserw.


EMAIL_FROM="AMO Developers <amo-developers@mozilla.org>"
EMAIL_TO="Awesome Localizers <dev-l10n-web@lists.mozilla.org>"
EMAIL_SUBJECT="[AMO] .po files updated"

# A link to the .po files
EMAIL_SOURCE="https://github.com/mozilla/olympia/tree/master/locale"

# gettext flags
CLEAN_FLAGS="--no-obsolete --width=200 --add-location=file"
MERGE_FLAGS="--update --width=200 --backup=none"
UNIQ_FLAGS="--width=200"

DEBUG_LOCALES="dbl dbr"

# -------------------------------------------------------------------

if [ ! -d "locale" ]; then
    echo "Sorry, please run from the root of the project, eg.  ./locale/omg_new_l10n.sh"
    exit 1
fi

# if [ ! -z "$(git status --porcelain)" ]; then
#    echo "Looks like you have some local changes.  Please clean up your root before we start committing random things."
#    git status
#    exit 1
# fi

echo "Alright, here we go..."

./manage.py extract

pushd locale > /dev/null

for debugLocale in $DEBUG_LOCALES; do
    for domain in django djangojs; do
        if [ "$locale" == "dbl" ]; then
            rewrite="unicode"
        else
            rewrite="flipped"
        fi

        echo "generating debug locale '$debugLocale' for '$domain' using '$rewrite'"

        podebug -i "templates/LC_MESSAGES/$domain.pot" -o "$debugLocale/LC_MESSAGES/$domain.po" --rewrite "$rewrite"
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

unset DOALLTHETHINGS
echo "done."
