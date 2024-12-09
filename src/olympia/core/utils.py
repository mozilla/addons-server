import json
import os
import sys
from functools import cache

import django


# Keys exempt from inspection in local images as they must be set.
EXEMPT_REQUIRED_KEYS = ['target', 'version', 'source']

# Keys required to be set in the version.json file.
REQUIRED_VERSION_KEYS = [*EXEMPT_REQUIRED_KEYS, 'commit', 'build']

root = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', '..')
pkg_json_path = os.path.join(root, 'package.json')


@cache
def get_version_json(
    build_info_path=os.environ['BUILD_INFO'],
    pkg_json_path=pkg_json_path,
):
    contents = {'source': 'https://github.com/mozilla/addons-server'}

    # Read the build info from the docker image.
    # This is static read only data that cannot
    # be overridden at runtime.
    with open(build_info_path) as f:
        for line in f:
            key, value = line.strip().split('=', 1)
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            contents[key] = value

    # Ensure all the expected keys are present.
    for key in REQUIRED_VERSION_KEYS:
        if key not in contents:
            raise ValueError(f'{key} is not set in the docker image')

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
