#!/bin/bash
# The current directory is a mounted volume, and is owned by the
# user running Docker on the host machine under linux (inc docker-machine).
#
# We don't want to trample all over the contents of this directory
# with files owned by root. So create a new user with the same UID,
# and drop privileges before running any commands.

# Get the numeric user ID of the current directory.
uid=$(ls -nd . | awk '{ print $3 }')

# Create an `olympia` user with that ID, and the current directory
# as its home directory.
if [[ $uid -ne 0 ]]; then
    # Don't try and create a user with uid 0 since it will fail.
    # Works around issue with docker for mac running containers
    # as root and not the user. Instead we just create the olympia
    # user since files will still be owned by the host's user
    # due to the way osxfs works.
    useradd -Md $(pwd) olympia
else
    useradd -Md $(pwd) -u $uid olympia
fi

deps_uid=$(ls -nd . | awk '{ print $3 }')

# Fix /deps/ folder so that we're able to update the image
# with the `olympia` user
if [[ $deps_uid -ne $uid ]]; then
    # Ensure that we are able to update dependencies ourselves later when
    # using the `olympia` user by default.
    chown -R olympia:olympia /deps/
fi

echo "Starting with user: 'olympia' uid: $(id -u olympia)"

# Add call to gosu to drop from root user to olympia user
# when running original entrypoint
set -- gosu olympia "$@"

# replace the current pid 1 with original entrypoint
exec "$@"
