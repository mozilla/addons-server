
# This script is run during a docker build, with the goal of ensuring that given the UID/GID of the `host` user running the containr, the `olympia` user inside the container has the same UID/GID. This is necessary to ensure that the files created by the `olympia` user inside the container are owned by the `host` user running the container.

echo "gid: $GID"
echo "uid: $UID"

function error() { echo "Error: $1"; exit 1; }

# Verify GID and UID are set in the environment.
if [ -z "$GID" ]; then error "GID not set."; fi
if [ -z "$UID" ]; then error "UID not set."; fi

# There are several scenarios to consider.
# Is there a group with matching GID? If so, is the group name "olympia"?
# Is there a user with matching UID? If so, is the username "olympia"?
# Is the user olympia a member of the group olympia?

# Check if there is a group with the name olympia
if getent group olympia >/dev/null; then
    # Change the GID of the group to the desired GID
    groupmod -g ${GID} olympia
else
    # Create a group with name olympia and GID as the id
    groupadd -g ${GID} olympia
fi

# Check if there is a user with UID as the id
if getent passwd ${UID} >/dev/null; then
    # Check if the username is not olympia
    if [ "$(getent passwd ${UID} | cut -d: -f1)" != "olympia" ]; then
        # Change the username to olympia
        usermod -l olympia $(getent passwd ${UID} | cut -d: -f1)
    fi
else
    if getent psswd olympia >/dev/null; then
        # We should not change the UID of an existing user,
        # But a user exists with our name olympia.
        error "User with name `olympia` already exists in the container. This should not happen"
    else
    # Create a user with name olympia and UID as the id, and add it to the olympia group
    useradd -u ${UID} -g olympia olympia
fi

# Check if user olympia is not a member of the group olympia
if ! getent group olympia | grep -q "\bolympia\b"; then
    # Add user olympia to the group olympia
    usermod -a -G olympia olympia
fi
