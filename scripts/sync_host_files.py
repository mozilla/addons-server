#!/usr/bin/env python3

import json
import os
import subprocess
from pathlib import Path


def sync_host_files():
    BUILD_INFO = os.environ.get('BUILD_INFO')
    HOME = os.environ.get('HOME')
    DEPS_DIR = os.environ.get('DEPS_DIR')
    NPM_DEPS_DIR = os.environ.get('NPM_DEPS_DIR')

    if None in [DEPS_DIR, NPM_DEPS_DIR]:
        raise ValueError('DEPS_DIR or NPM_DEPS_DIR is not set')


    with open(BUILD_INFO, 'r') as f:
        build_info = json.load(f)

    # If we are installing production dependencies or on a non local image
    # we always remove existing deps as we don't know what was previously
    # installed or in the host ./deps or ./node_modules directory
    # before running this script
    is_local = 'local' in build_info.get('tag')
    is_production = build_info.get('target') == 'production'

    if not is_local or is_production:
        print('Removing existing deps')
        subprocess.run(
            ['make', '-f', 'Makefile-docker', 'clean_directory', f"ARGS='{DEPS_DIR} --filter cache/**'"],
            check=True,
        )
        subprocess.run(
            ['make', '-f', 'Makefile-docker', 'clean_directory', f"ARGS='{NPM_DEPS_DIR}'"], check=True
        )
    else:
        print('Updating existing deps')


    subprocess.run(['make', 'update_deps'], check=True)

    if build_info.get('target') == 'production':
        subprocess.run(['make', 'compile_locales'], check=True)
        subprocess.run(['make', 'update_assets'], check=True)
    else:
        for path in ['static-build', 'site-static']:
            path = Path(HOME) / path
            subprocess.run(['make', 'clean_directory', f"ARGS='{path}'"], check=True)


if __name__ == '__main__':
    sync_host_files()
