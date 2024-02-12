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
find $1 -type f -name "django.po" | parallel 'pofile={}; dir=$(dirname "$pofile"); lang=$(echo "$pofile" | cut -d "/" -f2); stem=$(basename "$pofile" .po); dennis-cmd lint --errorsonly "$pofile" && msgfmt -o "${dir}/${stem}.mo" "$pofile"'

echo
echo "compiling djangojs.po..."
find $1 -type f -name "djangojs.po" | parallel 'pofile={}; dir=$(dirname "$pofile"); lang=$(echo "$pofile" | cut -d "/" -f2); stem=$(basename "$pofile" .po); touch "${dir}/${stem}.mo"; dennis-cmd lint --errorsonly "$pofile" && msgfmt -o "${dir}/${stem}.mo" "$pofile"'
