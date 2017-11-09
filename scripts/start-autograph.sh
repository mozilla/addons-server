#!/bin/bash

# Install autograph
go get go.mozilla.org/autograph
cd $GOPATH/src/go.mozilla.org/autograph

# Modify the default port to something free
sed -i '0,/^\([[:space:]]*listen: *\).*/s//\1"$AUTOGRAPH_SERVER_URL"/;' autograph.yaml

# Start autograph in background
$GOPATH/bin/autograph -c autograph.yaml 2>&1 &
