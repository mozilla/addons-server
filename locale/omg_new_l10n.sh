#! /bin/bash

# This script will do the following:
#   - Update your code
#   - Extract new strings and push to the .po files
#
# This script makes a lot of assumptions and has no error checking, so read it
# over before you run it.

# gettext flags
CLEAN_FLAGS="--no-obsolete --width=200 --no-location"
MERGE_FLAGS="--update --width=200 --backup=none"
UNIQ_FLAGS="--width=200"
DEBUG_LOCALES="dbl dbr"

# -------------------------------------------------------------------


if [ ! -d "locale" ]; then
    echo "Sorry, please run from the root of the project, eg.  ./locale/omg_new_l10n.sh"
    exit 1
fi

echo "Alright, here we go..."

./manage.py extract

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
