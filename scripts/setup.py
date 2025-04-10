#!/usr/bin/env python3

import argparse
import json
import os
import shutil
from pathlib import Path

from scripts.utils import Env, parse_docker_tag


# Paths should be removed before mounting .:/data/olympia
REMOVE_PATHS = [
    'src/olympia.egg-info',
    'supervisord.pid',
    'version.json',
    'logs',
    'buildx-bake-metadata.json',
]

# Paths should be created before mounting .:/data/olympia
CREATE_PATHS = [
    'deps',
    'site-static',
    'static-build',
    'storage',
]


def get_docker_image_meta(env: Env, is_build=False):
    for key in ['DOCKER_VERSION', 'DOCKER_DIGEST']:
        if env.get(key, from_file=False):
            raise ValueError(
                f'{key} is not allowed to be set in the environment'
                ' but is derived from the DOCKER_TAG variable.'
            )

    original_tag = env.get('DOCKER_TAG', 'mozilla/addons-server:local', type=str)
    tag, _, version, digest = parse_docker_tag(original_tag)
    is_local = version == 'local' and digest is None
    is_latest = version == 'latest' and digest is None
    docker_target = env.get(
        'DOCKER_TARGET',
        'production' if (is_build or not is_local) else 'development',
        type=str,
        from_file=False,
    )
    docker_commit = env.get('DOCKER_COMMIT', from_file=False)
    docker_build = env.get('DOCKER_BUILD', from_file=False)
    is_production = docker_target == 'production'

    def not_none(key, value):
        if value is None:
            return f'{key} is required'

    def valid_digest(key, value):
        defined = bool(value)
        if is_build:
            if defined:
                return (
                    f'{key} must not be set when building, '
                    'the digest is derived from the build metadata.'
                )
        elif not (is_local or is_latest) and not defined:
            return f'{key} is required for non-local images other than "latest"'

    def valid_docker_target(key, value):
        if not is_production:
            if is_build:
                return f'{key} must be set to "production" when building'
            if not is_local:
                return f'{key} must be set to "production" on non-local images'

    def valid_build_commit(key, value):
        defined = bool(value)

        if is_build and not defined:
            return f'{key} is required when building'
        if not is_build and defined:
            return f'Cannot set {key} outside of a build. read from /build-info.json.'

    data = {
        # These values are derived from the docker tag parser.
        # they cannot be invalid so are simply required here.
        'DOCKER_TAG': (tag, not_none),
        'DOCKER_VERSION': (version, not_none),
        # A digest is only required for non local/latest images.
        'DOCKER_DIGEST': (digest, valid_digest),
        # The next values have custom validation logic.
        'DOCKER_TARGET': (docker_target, valid_docker_target),
        'DOCKER_COMMIT': (docker_commit, valid_build_commit),
        'DOCKER_BUILD': (docker_build, valid_build_commit),
    }

    errors = {}
    meta = {}

    for key, (value, validator) in data.items():
        # Add defined values to meta
        if value:
            meta[key] = value
        # Add invalid values to errors
        if error := validator(key, value):
            errors[key] = error

    if len(errors.keys()):
        raise ValueError(
            f'\n{json.dumps(meta, indent=2)}\n'
            f'Invalid items: check setup.py for validations (build={is_build})'
            '\n• ' + '\n• '.join(errors.values())
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


def main(root: Path, env_file: str, is_build: bool, dry_run: bool):
    env = Env(root / env_file)
    image_meta = get_docker_image_meta(env, is_build)
    docker_target = image_meta['DOCKER_TARGET']

    # These variables are special, as we should allow the user to override them
    # but we should not set a default to the previously set value but instead
    # use a value derived from other stable values.
    debug = env.get(
        'DEBUG', bool(docker_target != 'production'), from_file=False, type=bool
    )
    olympia_deps = env.get('OLYMPIA_DEPS', docker_target, from_file=False, type=str)
    # These variables are not set by the user, but are derived from the environment only
    olympia_uid = os.getuid()

    result = {
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

    if dry_run:
        return result

    for path in REMOVE_PATHS:
        remove_path = root / path

        if remove_path.exists():
            if remove_path.is_dir():
                shutil.rmtree(remove_path)
            else:
                remove_path.unlink()

    env.write_env_file(result)

    # Create the directories that are expected to exist in the container.
    for dir in CREATE_PATHS:
        (root / dir).mkdir(parents=True, exist_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--root', type=Path, default=Path(__file__).parent.parent)
    parser.add_argument('--env-file', type=str, default='.env')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = main(args.root, args.env_file, args.build, args.dry_run)

    if args.dry_run:
        print(json.dumps(result, indent=2))
