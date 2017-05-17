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
unset DOALLTHETHINGS

# -------------------------------------------------------------------

function confirm {
    if [ ! -z $DOALLTHETHINGS ]; then
        return 0
    fi

    PROMPT=$1
    read -p "$PROMPT [y/n]: " YESNO
    if [[ $YESNO == 'y' ]]
    then
        return 0
    else
        return 1
    fi
}

if [[ "$1" == "--do-all-the-things" ]]; then
    DOALLTHETHINGS=1
fi

if [ ! -d "locale" ]; then
    echo "Sorry, please run from the root of the project, eg.  ./locale/omg_new_l10n.sh"
    exit 1
fi

echo "Alright, here we go..."

./manage.py extract

pushd locale > /dev/null

podebug --rewrite=unicode templates/LC_MESSAGES/django.pot dbg/LC_MESSAGES/django.po
podebug --rewrite=unicode templates/LC_MESSAGES/djangojs.pot dbg/LC_MESSAGES/djangojs.po

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

msgattrib $CLEAN_FLAGS --output-file=dbg/LC_MESSAGES/django.po dbg/LC_MESSAGES/django.po
msgattrib $CLEAN_FLAGS --output-file=dbg/LC_MESSAGES/djangojs.po dbg/LC_MESSAGES/djangojs.po
msgfilter -i sr/LC_MESSAGES/django.po -o sr_Latn/LC_MESSAGES/django.po recode-sr-latin

popd > /dev/null

unset DOALLTHETHINGS
echo "done."
