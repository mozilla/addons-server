#!/usr/bin/env python3

import json
import os
import subprocess


def git_config(key, default):
    try:
        return subprocess.check_output(['git', 'config', key]).decode().strip()
    except subprocess.CalledProcessError:
        return default


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


def clean_docker_version(docker_version):
    # For DOCKER_VERSION, we support defining a version tag or a digest.
    # Digest allows us to guarantee an image from a specific build is used in ci.

    # first check if the value in DOCKER_VERSION starts with : or @
    # if so, remove it, so we can re-evaluate the version.
    if docker_version[0] in [':', '@']:
        docker_version = docker_version[1:]

    # if the new value starts with sha256, it is a digest, otherwise a tag
    if docker_version.startswith('sha256'):
        # add a @ at the beginning of DOCKER_VERSION
        docker_version = '@' + docker_version
    else:
        # add a : at the beginning of DOCKER_VERSION
        docker_version = ':' + docker_version

    return docker_version


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

# Some variables have special formatting applied, such as DOCKER_VERSION
# this can be defined in an optional third argument to this function, as a function.
docker_version = clean_docker_version(get_value('DOCKER_VERSION', 'local'))

set_env_file(
    {
        'DOCKER_VERSION': docker_version,
        'HOST_UID': get_value('HOST_UID', os.getuid()),
        'SUPERUSER_EMAIL': get_value(
            'SUPERUSER_EMAIL', git_config('user.email', 'admin@mozilla.com')
        ),
        'SUPERUSER_USERNAME': get_value(
            'SUPERUSER_USERNAME', git_config('user.name', 'admin')
        ),
    }
)

build = get_value('VERSION_BUILD_URL', 'build')

with open('version.json', 'w') as f:
    data = {
        'commit': git_ref(),
        'version': docker_version[1:],
        'build': build,
        'source': 'https://github.com/mozilla/addons-server',
    }
    print('Version:')
    print(json.dumps(data, indent=2))
    json.dump(
        data,
        f,
    )
