#!/bin/sh
# The current directory is a mounted volume, and is owned by the
# user running Docker on the host machine.
#
# We don't want to trample all over the contents of this directory
# with files owned by root. So create a new user with the same UID,
# and drop privileges before running any commands.

# Get the numeric user ID of the current directory.
uid=$(ls -nd . | awk '{ print $3 }')

# Create an `olympia` user with that ID, and the current directory
# as its home directory.
useradd -Md $(pwd) -u $uid olympia

# Switch to that user and execute our actual command.
exec su olympia -c 'exec "$@"' sh -- "$@"
