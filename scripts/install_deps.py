#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys


# Constants
ALLOWED_NPM_TARGETS = set(['prod', 'dev'])


def copy_package_json():
    """Copy package.json files to deps directory if they exist."""
    try:
        shutil.copy('/data/olympia/package.json', '/deps')
        shutil.copy('/data/olympia/package-lock.json', '/deps')
    except (IOError, OSError):
        pass  # Ignore if files don't exist or can't be copied


def main():
    # Get targets from command line arguments
    targets = sys.argv[1:]
    if not targets:
        print('No targets specified')
        sys.exit(1)

    # Copy package.json files
    copy_package_json()

    # Prepare the includes lists
    pip_includes = []
    npm_includes = []

    # PIP_COMMAND is set by the Dockerfile
    pip_command = os.environ.get('PIP_COMMAND', 'pip')
    pip_args = pip_command.split() + [
        'install',
        '--progress-bar=off',
        '--no-deps',
        '--exists-action=w',
    ]

    # NPM_ARGS is set by the Dockerfile
    npm_args_env = os.environ.get('NPM_ARGS', '')
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
        print(f"Installing pip dependencies: {', '.join(pip_includes)} \n")
        subprocess.run(pip_args, check=True)

    if npm_includes:
        # Install npm dependencies
        print(f"Installing npm dependencies: {', '.join(npm_includes)} \n")
        subprocess.run(npm_args, check=True)


if __name__ == '__main__':
    main()
