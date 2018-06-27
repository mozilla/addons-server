#!/bin/bash

# Install autograph
echo "installing autograph + dependencies"
curl -sL -o ./gimme https://raw.githubusercontent.com/travis-ci/gimme/v1.2.0/gimme
chmod +x ./gimme
eval "$(./gimme 1.10)"
go get go.mozilla.org/autograph@2.1.3

# Start autograph in background
echo "start autograph in background at $(head ./scripts/autograph_travis_test_config.yaml | grep listen)"
nohup $GOPATH/bin/autograph -c ./scripts/autograph_travis_test_config.yaml 2>&1 &
