#!/usr/bin/env python3

import os


def set_env_file(values):
    with open('.env', 'w') as f:
        print('Environment:')
        for key, value in values.items():
            f.write(f'{key}="{value}"\n')
            print(f'{key}={value}')


def get_env_file(path='.env'):
    env = {}

    if os.path.exists(path):
        with open(path, 'r') as f:
            for line in f:
                key, value = line.strip().split('=', 1)
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                env[key] = value
    return env


def get_value(key, default_value, from_file=True):
    if key in os.environ:
        value_from_env = os.environ[key]
        if not any(
            [
                value_from_env == '',
                value_from_env is None,
            ]
        ):
            return value_from_env

    # If true, attempt to get the value from the .env file
    # as a fallback before returning the default value
    if from_file:
        value_from_file = get_env_file().get(key)
        if value_from_file is not None:
            return value_from_file

    return default_value


def get_docker_tag():
    image = 'mozilla/addons-server'
    version = 'local'

    # First get the tag from the full tag variable
    tag = get_value('DOCKER_TAG', f'{image}:{version}')
    # extract version or digest from existing tag
    if '@' in tag:
        image, digest = tag.split('@')
        version = None
    elif ':' in tag:
        image, version = tag.split(':')
        digest = None

    # DOCKER_DIGEST or DOCKER_VERSION can override the extracted version or digest
    # Note: it will inherit the image from the provided DOCKER_TAG if also provided
    if bool(os.environ.get('DOCKER_DIGEST', False)):
        digest = os.environ['DOCKER_DIGEST']
        tag = f'{image}@{digest}'
        version = None
    elif bool(os.environ.get('DOCKER_VERSION', False)):
        version = os.environ['DOCKER_VERSION']
        tag = f'{image}:{version}'
        digest = None

    print('tag: ', tag)
    print('version: ', version)
    print('digest: ', digest)

    return tag, version, digest


# Env file should contain values that are referenced in docker-compose*.yml files
# so running docker compose commands produce consistent results in terminal and make.
# These values should not be referenced directly in the make file.

# every variable defined here is covered with tests in test/make/make.spec.js
# to validate it is covered and correctly defined in the .env file
# The order of priorty for defining these values is:
#
# 1. the default value, defined in this script.
# 2. the value defined in the .env file
# 3. the value defined in the environment variable
# 4. the value defined in the make args.


def main():
    docker_tag, docker_version, _ = get_docker_tag()

    # The default target should be inferred from the version
    # but can be freely overridden by the user.
    # E.g running local image in production mode
    docker_target = get_value(
        'DOCKER_TARGET', ('development' if docker_version == 'local' else 'production')
    )
    # On development images, we ignore the user provided OLYMPIA_MOUNT_INPUT
    # and hard code the volume to development. This is because neither
    # the image nor the volume would provide the files needed by the container.
    # That is also why the value saved to .env is different from the input value.
    # This way the docker-compose.yml and the container only read the computed
    # OLYMPIA_MOUNT value and not the OLYMPIA_MOUNT_INPUT.
    data_olympia_mount = (
        docker_target
        if docker_target == 'development'
        else get_value('OLYMPIA_MOUNT_INPUT', docker_target)
    )

    # DEBUG is special, as we should allow the user to override it
    # but we should not set a default to the previously set value but instead
    # to the most sensible default.
    debug = get_value(
        'DEBUG', str(False if docker_target == 'production' else True), from_file=False
    )
    # OLYMPIA_UID should always be set to the current user's UID
    host_uid = os.getuid()

    set_env_file(
        {
            'DOCKER_TAG': docker_tag,
            'DOCKER_TARGET': docker_target,
            'OLYMPIA_UID': host_uid,
            'OLYMPIA_MOUNT': data_olympia_mount,
            'DEBUG': debug,
        }
    )


if __name__ == '__main__':
    main()
