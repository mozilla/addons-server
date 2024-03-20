#! /bin/bash

set -x

COUNT=1

GITHUB_URL="https://github.com"
GITHUB_ORG="mozilla"

FROM_NAME="addons-server"
TO_NAME="addons"

FROM_REPO="$GITHUB_URL/$GITHUB_ORG/$FROM_NAME"
TO_REPO="$GITHUB_URL/$GITHUB_ORG/$TO_NAME"

REPO_LABEL="repository:$FROM_NAME"

gh label clone $FROM_REPO -R $TO_REPO --force

gh label create $REPO_LABEL

transfer_issue() {
  issue_number=$1
  from_repo=$2
  to_repo=$3
  repo_label=$4

  echo "$from_repo/issues/$issue_number" >> old-issues.txt

  result=$(gh issue transfer "$issue_number" "$to_repo")

  echo "$result" >> new-issues.txt

  echo "Transferred issue $issue_number to $result"

  gh issue -R $to_repo edit $result --add-label $repo_label
}

export -f transfer_issue

echo "Transferring issues from \"$FROM_REPO\" to \"$TO_REPO\""

gh issue list -R "$FROM_REPO" -s all -L $COUNT --json number --search sort:created-asc --jq '.[] | .number' | xargs -P 4 -I % bash -c -e 'transfer_issue % '"$FROM_REPO $TO_REPO $REPO_LABEL" 2>&1
