#!/bin/bash
# this is a hack to work around how django-mozilla-product-details
# takes too long and always kills the vagrant VM on startup

dest=./lib/product_json
if [ ! -d $dest ]; then
    echo "usage: $0"
    echo ""
    echo "you must run this from the root of your zamboni checkout"
    exit 1
fi
if [ ! -f $dest/.last_update ]; then
    svn export --force http://svn.mozilla.org/libs/product-details/json/ $dest
    if [ $? -eq 0 ]; then
        # Bah. This isn't supported for some reason: date "+%a, %d %b %Y %H:%M:%S %Z"
        dd=`python -c 'import datetime,sys; sys.stdout.write(datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"))'`
        echo -n $dd > $dest/.last_update
        echo -n $dd > $dest/regions/.last_update
    fi
else
    echo "Already seeded product details JSON"
fi
