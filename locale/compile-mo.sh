#!/bin/bash
# syntax:
# compile-mo.sh locale-dir/

# Make this script fail if any command exits wit exit code != 0
set -e

function usage() {
    echo "syntax:"
    echo "compile-mo.sh locale-dir/"
    exit 1
}

# check if file and dir are there
if [[ ($# -ne 1) || (! -d "$1") ]]; then usage; fi

hash dennis-cmd 2>/dev/null || source $VENV/bin/activate

echo "compiling django.po..."
for pofile in `find $1 -type f -name "django.po"`; do
    dir=`dirname $pofile`
    lang=`echo $pofile | cut -d "/" -f2`
    stem=`basename $pofile .po`
    if [ $lang != 'dbr' ] && [ $lang != 'dbl' ]
    then
        # lint the .po file
        dennis-cmd lint --errorsonly "$pofile"
    fi
    if [ $? -ne 0 ]
    then
        exit 1
    else
        msgfmt -o ${dir}/${stem}.mo $pofile
    fi
done

echo
echo "compiling djangojs.po..."
for pofile in `find $1 -type f -name "djangojs.po"`; do
    dir=`dirname $pofile`
    lang=`echo $pofile | cut -d "/" -f2`
    stem=`basename $pofile .po`
    touch "${dir}/${stem}.mo"
    if [ $lang != 'dbr' ] && [ $lang != 'dbl' ]
    then
        # lint the .po file
        dennis-cmd lint --quiet --errorsonly "$pofile"
    fi
    if [ $? -ne 0 ]
    then
        echo "Skipping $pofile, errors detected. Run the following to list errors:"
        echo "dennis-cmd lint --errorsonly $pofile"
    else
        msgfmt -o ${dir}/${stem}.mo $pofile
    fi
done
