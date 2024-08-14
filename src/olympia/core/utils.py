import json
import os
import sys

import django

def get_version_json():
    contents = {}

    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', '..')

    contents['commit'] = os.environ.get('DOCKER_COMMIT', 'commit')
    contents['version'] = os.environ.get('DOCKER_VERSION', 'local')
    contents['source'] = 'https://github.com/mozilla/addons-server'
    contents['build'] = os.environ.get('DOCKER_BUILD', 'build')

    py_info = sys.version_info
    contents['python'] = '{major}.{minor}'.format(
        major=py_info.major, minor=py_info.minor
    )
    contents['django'] = '{major}.{minor}'.format(
        major=django.VERSION[0], minor=django.VERSION[1]
    )

    pkg_json_path = os.path.join(root, 'package.json')

    if os.path.exists(pkg_json_path):
        with open(pkg_json_path) as f:
            data = json.loads(f.read())
            contents['addons-linter'] = data['dependencies']['addons-linter']
    else:
        contents['addons-linter'] = ''

    return contents
