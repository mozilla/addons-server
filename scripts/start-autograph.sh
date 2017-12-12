#!/bin/bash

# Install autograph

echo "installing autograph + dependencies"
go get go.mozilla.org/autograph

# Start autograph in background
echo "start autograph in background at $(head autograph.yaml | grep listen)"
nohup $GOPATH/bin/autograph -c ./scripts/autograph_travis_test_config.yaml 2>&1 &
