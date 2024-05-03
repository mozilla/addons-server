import json
import os


def get_version_json():
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', '..')
    version_json = os.path.join(root, 'version.json')
    version = None

    if os.path.exists(version_json):
        try:
            with open(version_json) as fobj:
                contents = fobj.read()
                version = json.loads(contents)
        except (OSError, json.JSONDecodeError) as exc:
            print(f'Error reading {version_json}: {exc}')
            pass

    return version
