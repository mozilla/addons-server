#!/bin/sh
# this is a hack to work around how django-mozilla-product-details
# takes too long and always kills the vagrant VM on startup

dest=./lib/product_json
if [ ! -d $dest ]; then
    echo "usage: $0"
    echo ""
    echo "you must run this from the root of your zamboni checkout"
    exit 1
fi
svn export --force http://svn.mozilla.org/libs/product-details/json/ $dest
if [ $? -eq 0 ]; then
    date "+%a, %d %b %Y %H:%M:%S %Z" > $dest/.last_update
fi
