#!/bin/bash

# syntax:
# stats-po.sh

echo "Printing number of untranslated strings found in locales:"

for lang in `find $1 -type f -name "messages.po" | sort`; do
    dir=`dirname $lang`
    stem=`basename $lang .po`
    js="$dir/javascript.po"
    count=$(msgattrib --untranslated $lang | grep -c "msgid")
    count2=$(msgattrib --untranslated $js | grep -c "msgid")
    echo -e "$(dirname $dir)\t\tmain=$count\tjs=$count2"
done
