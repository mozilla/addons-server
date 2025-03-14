#!/usr/bin/env python3

import os


root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

env_path = os.path.join(root, '.env')


def set_env_file(values):
    with open(env_path, 'w') as f:
        print('Environment:')
        for key, value in values.items():
            f.write(f'{key}="{value}"\n')
            print(f'{key}={value}')


def get_env_file():
    env = {}

    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
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


def get_docker_image_meta():
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

    # Docker target can be set on local images, but should be inferred from the image
    # on remote images. Remote images are always built for production.
    target = (
        get_value('DOCKER_TARGET', 'development')
        if version == 'local'
        else 'production'
    )

    print('tag: ', tag)
    print('target: ', target)
    print('version: ', version)
    print('digest: ', digest)

    return tag, target, version, digest


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
    docker_tag, docker_target, _, _ = get_docker_image_meta()

    olympia_uid = os.getuid()

    # These variables are special, as we should allow the user to override them
    # but we should not set a default to the previously set value but instead
    # use a value derived from other stable values.
    debug = os.environ.get('DEBUG', str(docker_target != 'production'))
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
            'DEBUG': debug,
            'OLYMPIA_DEPS': olympia_deps,
        }
    )

    # Create the directories that are expected to exist in the container.
    for dir in ['deps', 'site-static', 'static-build', 'storage']:
        os.makedirs(os.path.join(root, dir), exist_ok=True)


if __name__ == '__main__':
    main()
