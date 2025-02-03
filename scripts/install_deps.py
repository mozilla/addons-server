#!/usr/bin/env python3

import json
import os
import subprocess
import sys


def main(targets):
    # Constants
    ALLOWED_NPM_TARGETS = set(['prod', 'dev'])
    BUILD_INFO = os.environ.get('BUILD_INFO')

    if not targets:
        raise ValueError('No targets specified')

    with open(BUILD_INFO, 'r') as f:
        build_info = json.load(f)

    print(
        'Updating deps... \n',
        f'targets: {", ".join(targets)} \n',
        f'build_info: {build_info} \n',
    )

    # Prepare the includes lists
    pip_includes = []
    npm_includes = []

    pip_args = [
        'python3',
        '-m',
        'pip',
        'install',
        '--progress-bar=off',
        '--no-deps',
        '--exists-action=w',
    ]

    npm_args = [
        'npm',
        'install',
    ]

    # Don't save package-lock.json on production images
    if build_info.get('target') == 'production':
        npm_args.append('--no-save')

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
