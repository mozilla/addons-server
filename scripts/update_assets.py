#!/usr/bin/env python3

import argparse
import os
import subprocess
from pathlib import Path


def update_assets(verbose: bool = False):
    HOME = os.environ.get('HOME')
    STATIC_DIRS = ['static-build', 'site-static']

    for directory in STATIC_DIRS:
        path = Path(HOME) / directory
        verbose_arg = '--verbose' if verbose else ''
        subprocess.run(
            [
                'make',
                '-f',
                'Makefile-docker',
                'clean_directory',
                f"ARGS='{path} {verbose_arg}'",
            ],
            check=True,
        )

    script_prefix = ['python3', 'manage.py']

    environment = os.environ.copy()
    # Always run in production mode without any development settings
    environment['DJANGO_SETTINGS_MODULE'] = 'olympia.lib.settings_base'

    subprocess.run(
        ['npm', 'run', 'build'],
        check=True,
        env=environment,
    )
    subprocess.run(
        script_prefix + ['compress_assets'],
        check=True,
        env=environment,
    )
    subprocess.run(
        script_prefix + ['generate_jsi18n_files'],
        check=True,
        env=environment,
    )
    subprocess.run(
        script_prefix + ['collectstatic', '--noinput'],
        check=True,
        env=environment,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    update_assets(args.verbose)
