#!/usr/bin/env python3

import json
import os
import subprocess


def main():
    BUILD_INFO = os.environ.get('BUILD_INFO')

    subprocess.run(['make', 'update_deps'], check=True)

    with open(BUILD_INFO, 'r') as f:
        build_info = json.load(f)

    if build_info.get('target') == 'production':
        subprocess.run(['make', 'compile_locales'], check=True)
        subprocess.run(['make', 'update_assets'], check=True)


if __name__ == '__main__':
    main()
