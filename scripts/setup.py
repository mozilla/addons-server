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


env = get_env_file()


def get_value(key, default_value):
    if key in os.environ:
        return os.environ[key]

    if key in env:
        return env[key]

    return default_value


def get_docker_tag():
    image_name = 'mozilla/addons-server'
    version = os.environ.get('DOCKER_VERSION')
    digest = os.environ.get('DOCKER_DIGEST')

    tag = f'{image_name}:local'

    if digest:
        tag = f'{image_name}@{digest}'
    elif version:
        tag = f'{image_name}:{version}'
    else:
        tag = get_value('DOCKER_TAG', tag)
        # extract version or digest from existing tag
        if '@' in tag:
            digest = tag.split('@')[1]
        elif ':' in tag:
            version = tag.split(':')[1]

    print('Docker tag: ', tag)
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

docker_tag, docker_version, docker_digest = get_docker_tag()

docker_target = get_value('DOCKER_TARGET', 'development')
compose_file = get_value(
    'COMPOSE_FILE', ('docker-compose.yml:docker-compose.development.yml')
)

set_env_file(
    {
        'COMPOSE_FILE': compose_file,
        'DOCKER_TAG': docker_tag,
        'DOCKER_TARGET': docker_target,
        'HOST_UID': get_value('HOST_UID', os.getuid()),
    }
)
