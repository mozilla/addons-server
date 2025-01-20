#!/usr/bin/env python3

import os
import shutil
import subprocess


def main():
    HOME = os.environ.get('HOME')
    STATIC_DIRS = ['static-build', 'site-static']

    for dir in STATIC_DIRS:
        path = os.path.join(HOME, dir)
        os.makedirs(path, exist_ok=True)
        for file in os.listdir(path):
            file_path = os.path.join(path, file)
            print(f'Removing {file_path}')
            if os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)

    script_prefix = ['python3', 'manage.py']

    environment = os.environ.copy()
    # Always run in production mode without any development settings
    environment['DJANGO_SETTINGS_MODULE'] = 'olympia.lib.settings_base'

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
    main()
