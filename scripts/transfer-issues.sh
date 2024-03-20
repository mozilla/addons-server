#! /bin/bash

COUNT=1

FROM_REPO="https://github.com/mozilla/addons-server"
TO_REPO="https://github.com/mozilla/addons"

gh label clone $FROM_REPO -R $TO_REPO --force

ISSUE_NUMBERS=$(gh issue list \
  -R $FROM_REPO \
  -s all \
  -L $COUNT \
  --json number \
  --search sort:created-asc \
  --jq '.[] | .number'
)

transfer_issue() {
  issue_number=$1
  to_repo=$2
  result=$(gh issue transfer "$issue_number" "$to_repo")

  echo $result
}

export -f transfer_issue

echo "Transferring issues from \"$FROM_REPO\" to \"$TO_REPO\""
echo "Issues: $ISSUE_NUMBERS"

echo "$ISSUE_NUMBERS" | xargs -P 4 -I % sh -c -e 'transfer_issue % '"$TO_REPO"
