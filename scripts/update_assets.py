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


def build_pinguino(environment):
    # Pinguino DevHub is (for now) a separate npm project with its own deps, built into
    # static/pinguino/ (see its vite.config.ts) so that collectstatic picks it.
    # vite.config.ts uses STATIC_URL_PREFIX, which is in `environment`.
    home = Path(os.environ['HOME'])
    pinguino_dir = home / 'src' / 'pinguino' / 'devhub'

    # Force the shared npm cache via an absolute path - .npmrc sets `cache` relative to
    # the cwd, and we want all the deps in one place.
    environment = {
        **environment,
        'npm_config_cache': str(home / 'deps' / 'cache' / 'npm'),
    }

    subprocess.run(
        ['npm', 'ci', '--no-audit', '--no-fund'],
        check=True,
        cwd=pinguino_dir,
        env=environment,
    )
    subprocess.run(
        ['npm', 'run', 'build'],
        check=True,
        cwd=pinguino_dir,
        env=environment,
    )


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
    build_pinguino(environment)
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
