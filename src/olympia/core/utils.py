import json
import os
import sys

import django


# Keys required to be set in the version.json file.
REQUIRED_VERSION_KEYS = ['target', 'version', 'source', 'commit', 'build']

root = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', '..')
pkg_json_path = os.path.join(root, 'package.json')


def get_version_json(
    build_info_path=os.environ['BUILD_INFO'],
    pkg_json_path=pkg_json_path,
):
    contents = {key: '' for key in REQUIRED_VERSION_KEYS}

    # Read the build info from the docker image.
    # This is static read only data that cannot
    # be overridden at runtime.
    if os.path.exists(build_info_path):
        with open(build_info_path) as f:
            contents.update(json.loads(f.read()))

    py_info = sys.version_info
    contents['python'] = '{major}.{minor}'.format(
        major=py_info.major, minor=py_info.minor
    )
    contents['django'] = '{major}.{minor}'.format(
        major=django.VERSION[0], minor=django.VERSION[1]
    )

    if os.path.exists(pkg_json_path):
        with open(pkg_json_path) as f:
            data = json.loads(f.read())
            dependencies = data.get('dependencies', {})
            contents['addons-linter'] = dependencies.get('addons-linter', '')
    else:
        contents['addons-linter'] = ''

    return contents
