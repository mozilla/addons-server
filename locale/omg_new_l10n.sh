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

#if [ ! -z "$(git status --porcelain)" ]; then
#    echo "Looks like you have some local changes.  Please clean up your root before we start committing random things."
#    git status
#    exit 1
#fi

echo "Alright, here we go..."

./manage.py extract

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
popd > /dev/null

podebug --rewrite=unicode locale/templates/LC_MESSAGES/django.pot locale/dbg/LC_MESSAGES/django.po
podebug --rewrite=unicode locale/templates/LC_MESSAGES/djangojs.pot locale/dbg/LC_MESSAGES/djangojs.po

msgattrib $CLEAN_FLAGS --output-file=locale/dbg/LC_MESSAGES/django.po locale/dbg/LC_MESSAGES/django.po
msgattrib $CLEAN_FLAGS --output-file=locale/dbg/LC_MESSAGES/djangojs.po locale/dbg/LC_MESSAGES/djangojs.po

pushd locale > /dev/null
msgfilter -i sr/LC_MESSAGES/django.po -o sr_Latn/LC_MESSAGES/django.po recode-sr-latin
popd > /dev/null

# pushd locale > /dev/null
# ./compile-mo.sh .
# popd > /dev/null

#if confirm "Commit your changes?"; then
#    git commit locale -m "Extract/compile script. Today's lucky number is $RANDOM."
#    git push mozilla master
#fi

echo "Calculating changes...."
pushd locale > /dev/null
CHANGES=$(cat <<MAIL
From: $EMAIL_FROM
To: $EMAIL_TO
Subject: $EMAIL_SUBJECT

Hi,

I am an automated script letting you know some .po files have just been
updated.  Unless something unusual is happening, we do weekly pushes on
Tuesdays so any strings committed by then will go live.  To give you an idea of
the number of new strings I will calculate untranslated strings below.

`./stats-po.sh .`

Source files: $EMAIL_SOURCE

If you have any questions please reply to the list.

Thanks so much for all your help!


MAIL
)
popd > /dev/null

echo "-----------------------------------------------"
echo "$CHANGES"
echo "-----------------------------------------------"

# Uses sendmail so we can set a real From address
#if confirm "Do you want to send that to $EMAIL_TO?"; then
#    echo "$CHANGES" | /usr/lib/sendmail -t
#fi

unset DOALLTHETHINGS
echo "done."
