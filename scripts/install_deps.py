#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys


def clean_dir(dir_path, filter):
    if not os.path.exists(dir_path):
        return

    for item in os.listdir(dir_path):
        item_path = os.path.join(dir_path, item)
        if os.path.isdir(item_path) and item not in filter:
            shutil.rmtree(item_path)


def main(targets):
    # Constants
    ALLOWED_NPM_TARGETS = set(['prod', 'dev'])
    DOCKER_TAG = os.environ.get('DOCKER_TAG', 'local')
    OLYMPIA_DEPS = os.environ.get('OLYMPIA_DEPS', '')
    DEPS_DIR = os.environ.get('DEPS_DIR')
    NPM_DEPS_DIR = os.environ.get('NPM_DEPS_DIR')

    if not targets:
        raise ValueError('No targets specified')

    print(
        'Updating deps... \n',
        f'targets: {", ".join(targets)} \n',
        f'DOCKER_TAG: {DOCKER_TAG} \n',
        f'OLYMPIA_DEPS: {OLYMPIA_DEPS} \n',
        f'DEPS_DIR: {DEPS_DIR} \n',
        f'NPM_DEPS_DIR: {NPM_DEPS_DIR} \n',
    )

    # If we are installing production dependencies or on a non local image
    # we always remove existing deps as we don't know what was previously
    # installed or in the host ./deps or ./node_modules directory
    # before running this script
    if 'local' not in DOCKER_TAG or OLYMPIA_DEPS == 'production':
        print('Removing existing deps')
        clean_dir(DEPS_DIR, ['cache'])
        clean_dir(NPM_DEPS_DIR, [])
    else:
        print('Updating existing deps')

    # Prepare the includes lists
    pip_includes = []
    npm_includes = []

    # PIP_COMMAND is set by the Dockerfile
    pip_command = os.environ['PIP_COMMAND']
    pip_args = pip_command.split() + [
        'install',
        '--progress-bar=off',
        '--no-deps',
        '--exists-action=w',
    ]

    # NPM_ARGS is set by the Dockerfile
    npm_args_env = os.environ['NPM_ARGS']
    npm_args = [
        'npm',
        'install',
        '--no-save',
        '--no-audit',
        '--no-fund',
    ] + npm_args_env.split()

    # Add the relevant targets to the includes lists
    for target in targets:
        pip_includes.append(target)
        pip_args.extend(['-r', f'requirements/{target}.txt'])
        if target in ALLOWED_NPM_TARGETS:
            npm_includes.append(target)
            npm_args.extend(['--include', target])

    if pip_includes:
        # Install pip dependencies
        print(f'Installing pip dependencies: {", ".join(pip_includes)} \n')
        subprocess.run(pip_args, check=True)

    if npm_includes:
        # Install npm dependencies
        print(f'Installing npm dependencies: {", ".join(npm_includes)} \n')
        subprocess.run(npm_args, check=True)


if __name__ == '__main__':
    main(sys.argv[1:])
