#!/bin/bash

set -xue

# if we are on a tag, we should use the tag as the version
# if we are on a branch, we should use the branch name as the version
version=$1
# we use the current HEAD as commit
commit=$2
# link to the job which produced the image
build=$3

cat <<EOF > version.json
{
  "commit": "$commit",
  "version": "$version",
  "build": "$build",
  "source": "https://github.com/mozilla/addons-server"
}
EOF

cat version.json
