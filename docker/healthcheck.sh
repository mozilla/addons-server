#!/bin/bash

name=$1
timeout=$2
url="http://olympia.test/__heartbeat__"
wait_time=1
count=0

while (( $timeout > 0 ))
do
  count=$((count + 1))
  echo "Checking service: $name for $count time. ($timeout seconds left)"
  response=$(curl -s "$url")

  service=$(echo $response | jq -r ".${name}")

  if [[ $service == "null" ]]; then
    echo "Service: $name not found"
    exit 1
  fi

  state=$(echo $service | jq -r ".state")

  if [[ $state == "true" ]]; then
    echo "Service: $name is healthy"
    exit 0
  else
    status=$(echo $service | jq -r ".status")
    echo "Status: $status"
  fi

  # Wait for the exponential backoff time
  sleep $wait_time

  # Double the wait time for the next iteration
  wait_time=$((wait_time * 2))

  # Decrease the timeout
  timeout=$((timeout - wait_time))
done

echo "Timeout reached"
exit 1
