#!/bin/bash
# syntax:
# compile-mo.sh locale-dir/

# Make this script fail if any command exits wit exit code != 0
set -ue

function process_po_file() {
    pofile=$1
    dir=$(dirname "$pofile")
    lang=$(echo "$pofile" | cut -d "/" -f2)
    stem=$(basename "$pofile" .po)
    touch "${dir}/${stem}.mo"
    dennis-cmd lint --errorsonly "$pofile" && msgfmt -o "${dir}/${stem}.mo" "$pofile"
}

# We are spawning sub processes with `xargs`
# and the function needs to be available in that sub process
export -f process_po_file

function usage() {
    echo "syntax:"
    echo "compile-mo.sh locale-dir/"
    exit 1
}

# check if file and dir are there
if [[ ($# -ne 1) || (! -d "$1") ]]; then usage; fi

# Ensure dennis-cmd cli is available in the environment
hash dennis-cmd

echo "compiling django.po..."
find $1 -type f -name "django.po" -print0 | xargs -0 -n1 -P4 bash -c 'process_po_file "$@"' _

echo "compiling djangojs.po..."
find $1 -type f -name "djangojs.po" -print0 | xargs -0 -n1 -P4 bash -c 'process_po_file "$@"' _
