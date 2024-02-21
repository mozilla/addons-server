# Extract code block into a function
get_next_uid() {
  local uid=$(awk -F: '{print $3}' /etc/passwd | sort -n | tail -1)
  echo $((uid + 1))
}

# Extract code block into a function
get_next_gid() {
  local gid=$(awk -F: '{print $3}' /etc/group | sort -n | tail -1)
  echo $((gid + 1))
}

NONROOT="nonroot"
DOCKER="docker"

# Create non-root user and group
addgroup -g $(get_next_gid) $NONROOT
adduser -u $(get_next_uid) -G $NONROOT -D -s /bin/sh $NONROOT


# Check if group docker exists
if ! getent group docker > /dev/null; then
  addgroup -g $(get_next_gid) $DOCKER
fi

# allow nonroot to use docker daemon
adduser $NONROOT $DOCKER

