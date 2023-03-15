# Alter the uid/gid of the olympia user/group to match the host
usermod -u ${UID} olympia
groupmod -g ${GID} olympia

# Install sudoers file for olympia user. Keep pip/npm env variables
# so make sudo pip install install where we want it to.
cat << EOF > /etc/sudoers.d/olympia
Defaults env_keep += "PYTHONUSERBASE PIP_USER PIP_BUILD PIP_SRC PIP_CACHE NPM_CONFIG_PREFIX"
%olympia	ALL=(root) NOPASSWD:/usr/bin/npm
%olympia	ALL=(root) NOPASSWD:/usr/local/bin/pip
EOF
