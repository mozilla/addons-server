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


EMAIL_FROM="Marketplace Developers <dev-l10n-web@lists.mozilla.org>"
EMAIL_TO="Awesome Localizers <dev-l10n-web@lists.mozilla.org>"
EMAIL_SUBJECT="[Marketplace] .po files updated"

# A link to the .po files
EMAIL_SOURCE="https://github.com/mozilla/zamboni/tree/master/locale"

# gettext flags
CLEAN_FLAGS="--no-obsolete --width=200"
MERGE_FLAGS="--update --no-fuzzy-matching --width=200 --backup=none"
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

if [ ! -z "$(git status --porcelain)" ]; then
    echo "Looks like you have some local changes.  Please clean up your root before we start committing random things."
    git status
    exit 1
fi

echo "Alright, here we go..."

if confirm "Update locales?"; then
    git co master --quiet
    git pull
fi

if confirm "Extract new strings?"; then
    ./manage.py extract
fi

if confirm "Merge new strings to .po files?"; then
    pushd locale > /dev/null

    echo "Merging any new keys..."
    for i in `find . -name "messages.po" | grep -v "en_US"`; do
        msgmerge $MERGE_FLAGS "$i" "templates/LC_MESSAGES/messages.pot"
    done
    msgen templates/LC_MESSAGES/messages.pot | msgmerge $MERGE_FLAGS en_US/LC_MESSAGES/messages.po -

    echo "Merging any new javascript keys..."
    for i in `find . -name "javascript.po" | grep -v "en_US"`; do
        msgmerge $MERGE_FLAGS "$i" "templates/LC_MESSAGES/javascript.pot"
    done
    msgen templates/LC_MESSAGES/javascript.pot | msgmerge $MERGE_FLAGS en_US/LC_MESSAGES/javascript.po -

    echo "Cleaning out obsolete messages.  See bug 623634 for details."
    for i in `find . -name "messages.po"`; do
        msgattrib $CLEAN_FLAGS --output-file=$i $i
    done
    for i in `find . -name "javascript.po"`; do
        msgattrib $CLEAN_FLAGS --output-file=$i $i
    done
    popd > /dev/null
fi

if confirm "Process your debug language?"; then
    podebug --rewrite=unicode locale/templates/LC_MESSAGES/messages.pot locale/dbg/LC_MESSAGES/messages.po
    podebug --rewrite=unicode locale/templates/LC_MESSAGES/javascript.pot locale/dbg/LC_MESSAGES/javascript.po
fi

if [ -z "$(git status --porcelain)" ]; then
    echo "Looks like there are no new strings to commit."
    exit 0
fi

if confirm "Compile all the .po files?"; then
    pushd locale > /dev/null
    ./compile-mo.sh .
    popd > /dev/null
fi

if confirm "Commit your changes?"; then
    git commit locale -m "Extract/compile script.  Today's lucky number is $RANDOM."
    git push mozilla master
fi

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

`./stats-po.sh`

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
if confirm "Do you want to send that to $EMAIL_TO?"; then
    echo "$CHANGES" | /usr/lib/sendmail -t
fi

unset DOALLTHETHINGS
echo "done."
