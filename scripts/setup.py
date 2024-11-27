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

    # The default value for which compose files to use is based on the target
    # but can be freely overridden by the user.
    # E.g running a production image in development mode with source code changes
    compose_file = get_value('COMPOSE_FILE', 'docker-compose.yml')

    # DEBUG is special, as we should allow the user to override it
    # but we should not set a default to the previously set value but instead
    # to the most sensible default.
    debug = os.environ.get('DEBUG', str(False if is_production else True))

    set_env_file(
        {
            'COMPOSE_FILE': compose_file,
            'DOCKER_TAG': docker_tag,
            'DOCKER_TARGET': docker_target,
            'HOST_UID': get_value('HOST_UID', os.getuid()),
            'DEBUG': debug,
        }
    )


if __name__ == '__main__':
    main()
