#!/usr/bin/env python3

import os
import shutil
import subprocess


def main():
    """
    Update the static assets served by addons-server for production.
    """
    HOME = os.environ.get('HOME')

    for dir in ['static-build', 'site-static']:
        path = os.path.join(HOME, dir)
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)
        open(os.path.join(path, '.gitkeep'), 'w').close()

    script_prefix = ['python3', 'manage.py']

    environment = os.environ.copy()
    environment['DJANGO_SETTINGS_MODULE'] = 'olympia.lib.settings_base'

    subprocess.run(
        script_prefix + ['compress_assets'],
        check=True,
        env=environment,
        capture_output=False,
    )
    subprocess.run(
        script_prefix + ['generate_jsi18n_files'],
        check=True,
        env=environment,
        capture_output=False,
    )
    subprocess.run(
        script_prefix + ['collectstatic', '--noinput'],
        check=True,
        env=environment,
        capture_output=False,
    )


if __name__ == '__main__':
    main()
