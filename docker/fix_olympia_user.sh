# Alter the uid/gid of the olympia user/group to match the host
usermod -u ${UID} olympia
groupmod -g ${GID} olympia
