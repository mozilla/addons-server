
#!/bin/bash

set -e

echo "Updating olympia user to host defined UID/GID..."
echo "UID: $UID"
echo "GID: $GID"

# Alter the uid/gid of the olympia user/group to match the host
usermod -u ${UID} olympia
groupmod -g ${GID} olympia
