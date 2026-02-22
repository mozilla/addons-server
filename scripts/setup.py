#!/usr/bin/env python3

import argparse
import json
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


def get_docker_image_meta(build=False):
    image = 'mozilla/addons-server'
    version = 'local'
    digest = None

    # First get the tag from the full tag variable
    tag = get_value('DOCKER_TAG', f'{image}:{version}')
    # extract version or digest from existing tag
    if '@' in tag:
        image, digest = tag.split('@')
        version = None
    elif ':' in tag:
        image, version = tag.split(':')

    # DOCKER_DIGEST or DOCKER_VERSION can override the extracted version or digest
    # Note: it will inherit the image from the provided DOCKER_TAG if also provided
    if bool(os.environ.get('DOCKER_DIGEST', False)):
        digest = os.environ['DOCKER_DIGEST']
        tag = f'{image}@{digest}'
        version = None
    elif bool(os.environ.get('DOCKER_VERSION', False)):
        version = os.environ['DOCKER_VERSION']
        tag = f'{image}:{version}'

    is_local = version == 'local' and digest is None
    docker_target = (
        get_value('DOCKER_TARGET', 'development')
        if is_local
        else os.environ.get('DOCKER_TARGET', 'production')
    )
    is_production = docker_target == 'production'
    docker_commit = os.environ.get('DOCKER_COMMIT')
    docker_build = os.environ.get('DOCKER_BUILD')

    valid_version_digest = (version and not digest) or (digest and not version)
    valid_docker_target = is_production or (is_local and not build)

    def valid_build_commit(value):
        # We don't care what the value is in local images
        if is_local:
            return True
        # When building, the value is required
        # to be written to the build-info.json
        elif build:
            return bool(value)
        # When running (on production), the value is forbidden
        # it was defined in the build-info.json
        elif is_production:
            return not bool(value)

    # Define metadata and define if the value is valid
    data = {
        # Docker tag is always required but often derived from other inputs
        'DOCKER_TAG': (tag, tag is not None),
        # Docker version and digest are mutually exclusive
        # exactly and only one should be set
        'DOCKER_VERSION': (version, valid_version_digest),
        'DOCKER_DIGEST': (digest, valid_version_digest),
        # Docker target can be set on local images,
        # but should be production for remote images.
        # Remote images are always built for production.
        'DOCKER_TARGET': (docker_target, valid_docker_target),
        # Docker commit and build are:
        # - optional for non production images
        # - forbidden on remote images (already defined in the build-info.json)
        'DOCKER_COMMIT': (docker_commit, valid_build_commit(docker_commit)),
        'DOCKER_BUILD': (docker_build, valid_build_commit(docker_build)),
    }

    errors = {}
    meta = {}

    for key, (value, valid) in data.items():
        # Add defined values to meta
        if value:
            meta[key] = value
        # Add invalid values to errors
        if not valid:
            errors[key] = value

    if len(errors.keys()):
        raise ValueError(
            f'\n{json.dumps(meta, indent=2)}\n'
            f'Invalid items: check setup.py for validations (build={build})'
            '\n• ' + '\n• '.join(errors.keys())
        )

    return meta


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


def main(build=False):
    image_meta = get_docker_image_meta(build)
    docker_target = image_meta['DOCKER_TARGET']

    # These variables are special, as we should allow the user to override them
    # but we should not set a default to the previously set value but instead
    # use a value derived from other stable values.
    debug = os.environ.get('DEBUG', str(docker_target != 'production'))
    olympia_deps = os.environ.get('OLYMPIA_DEPS', docker_target)
    # These variables are not set by the user, but are derived from the environment only
    olympia_uid = os.environ.get('OLYMPIA_UID', os.getuid())

    set_env_file(
        {
            **image_meta,
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    main(args.build)
