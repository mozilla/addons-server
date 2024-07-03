#!/usr/bin/env python3

import json
import os
import subprocess


def set_env_file(values):
    with open('.env', 'w') as f:
        print('Environment:')
        for key, value in values.items():
            f.write(f'{key}={value}\n')
            print(f'{key}={value}')


def get_env_file():
    env = {}

    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                key, value = line.strip().split('=', 1)
                env[key] = value
    return env


env = get_env_file()


def get_value(key, default_value=None):
    value = os.environ.get(key)
    if value is not None:
        return os.environ[key]

    if key in env:
        return env[key]

    return default_value


def git_ref():
    try:
        git_ref = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
    except subprocess.CalledProcessError:
        git_ref = 'commit'

    return get_value('DOCKER_COMMIT', git_ref)


def split(input_string, separator):
    parts = input_string.split(separator, 1)
    return parts if len(parts) > 1 else (parts[0], None)


known_registries = ['docker.io', 'ghcr.io']


def parse_tag(input):
    registry = None
    image = None
    version = None
    digest = None

    if input:
        input, digest = split(input, '@')
        input, version = split(input, ':')

        for reg in known_registries:
            if input.startswith(f'{reg}/'):
                registry, image = split(input, '/')
                break
        else:
            image = input

    if image is None:
        raise ValueError(f'Cannot parse image from {input}')

    if version is None and digest is None:
        raise ValueError(
            f'Cannot parse version: {version} or digest: {digest} from {input}'
        )

    return registry, image, version, digest


def get_default_tag_parts():
    # Check for full DOCKER_TAG environment variable first
    tag = get_value('DOCKER_TAG', '')
    if tag != '':
        return parse_tag(tag)

    return 'docker.io', 'mozilla/addons-server', 'local', None


registry, image, version, digest = get_default_tag_parts()

registry = os.environ.get('DOCKER_REGISTRY', registry)
image = os.environ.get('DOCKER_IMAGE', image)
version = os.environ.get('DOCKER_VERSION', version)
digest = os.environ.get('DOCKER_DIGEST', digest)

image_name = f'{registry}/{image}' if registry else image
tag = f'{image_name}@{digest}' if digest else f'{image_name}:{version}'

# Output the results for verification
print('Registry: ', registry)
print('Image: ', image)
print('Version: ', version)
print('Digest: ', digest)
print('Tag: ', tag)

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

set_env_file(
    {
        'COMPOSE_FILE': get_value('COMPOSE_FILE', ('docker-compose.yml')),
        'DOCKER_TAG': tag,
        'HOST_UID': get_value('HOST_UID', os.getuid()),
    }
)

# registry:undefined_image:image_version:undefined_digest:diges

build = get_value('VERSION_BUILD_URL', 'build')

with open('version.json', 'w') as f:
    data = {
        'commit': git_ref(),
        'version': version,
        'digest': digest,
        'build': build,
        'source': 'https://github.com/mozilla/addons-server',
    }
    print('Version:')
    print(json.dumps(data, indent=2))
    json.dump(
        data,
        f,
    )
