#!/usr/bin/env python3

import json
import os
import subprocess
import tarfile


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

def clean_image_tar_path(image_path):
    if os.path.exists(image_path):
        print(f'Removing {image_path}')
        os.remove(image_path)

def download_artifact(artifact_name, timeout=120):
    # This value is automatically set in CI
    # Running locally you need to manually set the value
    # to the action run ID from where you want to download the image
    gh_run_id = get_value('GITHUB_RUN_ID', None)

    print(f'Downloading artifact {artifact_name} from run {gh_run_id}...')

    if not gh_run_id:
        raise ValueError('Missing GITHUB_RUN_ID in environment.')

    # Start the subprocess
    command = ['gh', 'run', 'download', gh_run_id, '-n', artifact_name]
    print(command)
    return subprocess.run(
        command,
        timeout=timeout
    )

def load_image_to_tag(image_path):
    print(f'Loading docker image from {image_path}')

    # load the image to docker image context
    with open(image_path, 'rb') as tar_file:
        command = ['docker', 'load']
        print(command)
        # Pass the file descriptor to subprocess.run
        subprocess.run(
            command,
            stdin=tar_file,
        )

    # Extract the tag from the tar file
    with tarfile.open(image_path, 'r') as tar:
        # Extract the 'index.json' file from the tar file
        index_json_file = tar.extractfile('index.json')
        index_json_content = index_json_file.read()
        index_json = json.loads(index_json_content)

        docker_tag = index_json['manifests'][0]['annotations'][
            'io.containerd.image.name'
        ]

        return docker_tag

def download_image(artifact_name, image_path):
    print('Downloading image...')
    print(f'artifact: {artifact_name}')
    print(f'image path: {image_path}')

    download_attempt = 0
    # We can try to download the image up to 5 times
    while download_attempt + 1 < 5:
        # Remove any image.tar before downloading
        clean_image_tar_path(image_path)

        result = download_artifact(artifact_name)

        if result.returncode == 0:
            break
        else:
            print(result.stderr)

    return load_image_to_tag(image_path)

def build_image(tag):
    command = ['make', 'build_docker_image', f'DOCKER_TAG={tag}']
    print(command)
    result = subprocess.run(command)

    if result.returncode != 0:
        raise Exception(result.stderr)

def pull_image(tag):
    pass

def stringify_tag(registry=None, image=None, version=None, digest=None):
    image_name = f'{registry}/{image}' if registry else image
    return f'{image_name}@{digest}' if digest else f'{image_name}:{version}'

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

default_tag = stringify_tag(image='mozilla/addons-server', version='local')
previous_tag = get_value('DOCKER_TAG', None)

current_tag = previous_tag or default_tag

print('current', current_tag)

registry, image, version, digest = parse_tag(current_tag)

artifact_name = get_value('DOCKER_ARTIFACT', None)

# image.tar is where the image will be when downloaded
root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
image_tar_path = os.path.abspath(os.path.join(root, 'image.tar'))

print('Registry: ', registry)
print('Image: ', image)
print('Version: ', version)
print('Digest: ', digest)
print('Tag: ', current_tag)
print('Artifact: ', artifact_name)

# # If docker artifact name is provided we need to load the image
# # And replace the docker tag
# if artifact_name:
#     docker_tag = download_image(artifact_name, image_tar_path)

# Scenarios
# 1. artifact - download
# 3. Tag with digest - pull?
# 2. Tag with version that is not :local - pull?
# 1. *: build

# DOCKER_TAG should be the only way to input to this script no more version/digest etc.
# 1. then we can simplify the action scripts to pass the full tag and the registry
# 2. We should TRY pushing without the registry in the image then we can remove the concept entirely
# 3. we should still add logic for parsing the tag so we can extract the digest/version to know what to do

set_env_file(
    {
        'COMPOSE_FILE': get_value('COMPOSE_FILE', ('docker-compose.yml')),
        'DOCKER_TAG': '',
        'HOST_UID': get_value('HOST_UID', os.getuid()),
    }
)
