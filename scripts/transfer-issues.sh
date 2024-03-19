#! /bin/bash

COUNT=1

gh issue list \
  -s all \
  -L $COUNT \
  --json number \
  --search sort:created-asc \
  --jq '.[] | .number' | \
  xargs -I% gh issue transfer % https://github.com/mozilla/addons

