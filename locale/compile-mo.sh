#!/bin/bash

# syntax:
# compile-mo.sh locale-dir/

function usage() {
    echo "syntax:"
    echo "compile.sh locale-dir/"
    exit 1
}

# check if file and dir are there
if [[ ($# -ne 1) || (! -d "$1") ]]; then usage; fi

echo "compiling messages.po...."
for lang in `find $1 -type f -name "messages.po"`; do
    dir=`dirname $lang`
    stem=`basename $lang .po`
    msgfmt -o ${dir}/${stem}.mo $lang
done

echo "compiling javascript.po...."
for lang in `find $1 -type f -name "javascript.po"`; do
    dir=`dirname $lang`
    stem=`basename $lang .po`
    touch "${dir}/${stem}.mo"
    msgfmt -o ${dir}/${stem}.mo $lang
done
