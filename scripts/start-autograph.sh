#!/bin/bash

# Install autograph

echo "installing autograph + dependencies"
go get go.mozilla.org/autograph
cd $GOPATH/src/go.mozilla.org/autograph

# Modify the default port to something free
sed -i "s@http://localhost:8000@$AUTOGRAPH_SERVER_URL@" autograph.yaml

# Start autograph in background
echo "start autograph in background at $(head autograph.yaml | grep listen)"
$GOPATH/bin/autograph -c autograph.yaml 2>&1 &
