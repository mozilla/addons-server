#!/bin/bash

set -ue
whoami

echo "Updating olympia user to host defined UID/GID..."
echo "UID: $(id -u olympia) -> $UID"
echo "GID: $(id -g olympia) -> $GID"

# Alter the uid/gid of the olympia user/group to match the host
usermod -u ${UID} olympia
groupmod -g ${GID} olympia

# Ensure the `new` olympia user has access to the deps directory
chown -R olympia:olympia /deps

su -s /bin/bash olympia <<EOF
whoami
set -xue
$@
EOF
