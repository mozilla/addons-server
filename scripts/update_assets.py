#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
from pathlib import Path


def clean_static_dirs(verbose: bool = False):
    HOME = os.environ.get('HOME')
    STATIC_DIRS = ['static-build', 'site-static']

    for directory in STATIC_DIRS:
        path = Path(HOME) / directory
        path.mkdir(parents=True, exist_ok=True)
        for entry in path.iterdir():
            entry_path = entry.as_posix()
            if verbose:
                print(f'Removing {entry_path}')
            if entry.is_dir():
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)


def update_assets(verbose: bool = False):
    clean_static_dirs(verbose)

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
        script_prefix + ['generate_jsi18n_files'],
        check=True,
        env=environment,
    )
    subprocess.run(
        script_prefix + ['generate_js_swagger_files'],
        check=True,
        env=environment,
    )
    subprocess.run(
        script_prefix + ['collectstatic', '--noinput', '--clear'],
        check=True,
        env=environment,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    update_assets(args.verbose)
