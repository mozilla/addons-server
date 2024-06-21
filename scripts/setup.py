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


def get_value(key, default_value):
    if key in os.environ:
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

# set pull_policy of web/worker containers based on the specified tag
# for digest or non `local` versions, we should avoid building and pull aggressively
docker_pull_policy = 'always' if docker_digest or docker_version != 'local' else 'build'

set_env_file(
    {
        'COMPOSE_FILE': get_value('COMPOSE_FILE', ('docker-compose.yml')),
        'DOCKER_TAG': docker_tag,
        'DOCKER_TARGET': get_value('DOCKER_TARGET', 'development'),
        'DOCKER_PULL_POLICY': docker_pull_policy,
    }
)

build = get_value('VERSION_BUILD_URL', 'build')

with open('version.json', 'w') as f:
    data = {
        'commit': git_ref(),
        'version': docker_version,
        'digest': docker_digest,
        'build': build,
        'source': 'https://github.com/mozilla/addons-server',
    }
    print('Version:')
    print(json.dumps(data, indent=2))
    json.dump(
        data,
        f,
    )
