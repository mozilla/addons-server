#!/usr/bin/env python3

import os


def set_env_file(values):
    with open('.env', 'w') as f:
        print('Environment:')
        for key, value in values.items():
            f.write(f'{key}="{value}"\n')
            print(f'{key}={value}')


def get_env_file():
    env = {}

    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                key, value = line.strip().split('=', 1)
                env[key] = value.strip('"')
    return env


def get_value(key, default_value):
    if key in os.environ:
        return os.environ[key]

    from_file = get_env_file()

    if key in from_file:
        return from_file[key]

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


def get_olympia_mount(docker_target):
    """
    When running on production targets, the user can specify the olympia mount
    to one of the valid values: development or production. In development, we
    hard code the values to ensure we have necessary files and permissions.
    """
    dev_source = './'
    prod_source = 'data_olympia_'
    olympia_mount = docker_target
    olympia_mount_source = dev_source if docker_target == 'development' else prod_source

    if (
        docker_target == 'production'
        and os.environ.get('OLYMPIA_MOUNT') == 'development'
    ):
        olympia_mount = 'development'
        olympia_mount_source = dev_source

    return olympia_mount, olympia_mount_source


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

    is_local = docker_version == 'local'

    # The default target should be inferred from the version
    # but can be freely overridden by the user.
    # E.g running local image in production mode
    docker_target = get_value(
        'DOCKER_TARGET', ('development' if is_local else 'production')
    )

    is_production = docker_target == 'production'

    olympia_uid = os.getuid()
    olympia_mount, olympia_mount_source = get_olympia_mount(docker_target)

    # These variables are special, as we should allow the user to override them
    # but we should not set a default to the previously set value but instead
    # use a value derived from other stable values.
    debug = os.environ.get('DEBUG', str(False if is_production else True))
    olympia_deps = os.environ.get('OLYMPIA_DEPS', docker_target)

    set_env_file(
        {
            'DOCKER_TAG': docker_tag,
            'DOCKER_TARGET': docker_target,
            # We save olympia_* values as host_* values to ensure that
            # inputs can be recieved via environment variables, but that
            # docker compose only reads the values explicitly set in the .env file.
            # These values are mapped back to the olympia_* values in the environment
            # of the container so everywhere they can be referenced as the user expects.
            'HOST_UID': olympia_uid,
            'HOST_MOUNT': olympia_mount,
            # Save the docker compose volume name
            # to use as the source of the /data/olympia volume
            'HOST_MOUNT_SOURCE': olympia_mount_source,
            'DEBUG': debug,
            'OLYMPIA_DEPS': olympia_deps,
        }
    )


if __name__ == '__main__':
    main()
