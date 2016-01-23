set -e
python manage.py extract

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

podebug --rewrite=unicode locale/templates/LC_MESSAGES/messages.pot locale/dbg/LC_MESSAGES/messages.po
podebug --rewrite=unicode locale/templates/LC_MESSAGES/javascript.pot locale/dbg/LC_MESSAGES/javascript.po
msgfilter -i sr/LC_MESSAGES/messages.po -o sr_Latn/LC_MESSAGES/messages.po recode-sr-latin

./compile-mo.sh .

git config user.name "pobot"
git config user.email "pobot@mozilla.com"

git commit locale -m "l10n extraction script"
git push mozilla master
