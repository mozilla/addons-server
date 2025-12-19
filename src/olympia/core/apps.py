import json
import logging
import os
import subprocess
import warnings
from pathlib import Path
from pwd import getpwnam

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Tags, register
from django.db import connection

import requests

from olympia.core.utils import REQUIRED_VERSION_KEYS, get_version_json


log = logging.getLogger('z.startup')


class CustomTags(Tags):
    custom_setup = 'setup'


@register(CustomTags.custom_setup)
def uwsgi_check(app_configs, **kwargs):
    """Custom check triggered when ./manage.py check is ran (should be done
    as part of verifying the docker image in CI)."""
    errors = []
    command = ['uwsgi', '--version']
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        errors.append(
            Error(
                f'{" ".join(command)} returned a non-zero value',
                id='setup.E001',
            )
        )
    return errors


@register(CustomTags.custom_setup)
def host_check(app_configs, **kwargs):
    """Check that the host settings are valid."""
    errors = []

    # In production, we expect settings.HOST_UID to be None and so
    # set the expected uid to 9500, otherwise we expect the uid
    # passed to the environment to be the expected uid.
    expected_uid = 9500 if settings.HOST_UID is None else int(settings.HOST_UID)
    # Get the actual uid from the olympia user
    actual_uid = getpwnam('olympia').pw_uid

    if actual_uid != expected_uid:
        return [
            Error(
                f'Expected user uid to be {expected_uid}, received {actual_uid}',
                id='setup.E002',
            )
        ]

    return errors


@register(CustomTags.custom_setup)
def version_check(app_configs, **kwargs):
    """Check the (virtual) version.json file exists and has the correct keys."""
    version = get_version_json()

    missing_keys = [key for key in REQUIRED_VERSION_KEYS if key not in version]

    if missing_keys:
        return [
            Error(
                f'{", ".join(missing_keys)} is missing from version.json',
                id='setup.E002',
            )
        ]

    return []


@register(CustomTags.custom_setup)
def static_check(app_configs, **kwargs):
    errors = []
    version = get_version_json()

    # We only run this check in production images.
    if version.get('target') != 'production':
        return []

    manifest_path = Path(settings.STATIC_BUILD_MANIFEST_PATH)

    if not manifest_path.exists():
        errors.append(
            Error(
                (
                    'Static build manifest file '
                    f'does not exist: {manifest_path.as_posix()}'
                ),
                id='setup.E003',
            )
        )
    else:
        with open(manifest_path.as_posix(), 'r') as f:
            manifest = json.load(f)

            for name, asset in manifest.items():
                # Assets compiled by vite are in the static root directory
                # after running collectstatic. So we should look there.
                path = Path(settings.STATIC_ROOT) / asset['file']
                if not path.exists():
                    errors.append(
                        Error(
                            (
                                f'Static asset {name} does not exist at '
                                f'expected path: {path.as_posix()}'
                            ),
                            id='setup.E003',
                        )
                    )

    return errors


@register(CustomTags.custom_setup)
def db_charset_check(app_configs, **kwargs):
    errors = []

    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW VARIABLES LIKE 'character_set_database';")
            result = cursor.fetchone()
            if result[1] != settings.DB_CHARSET:
                errors.append(
                    Error(
                        'Database charset invalid. '
                        f'Expected {settings.DB_CHARSET}, '
                        f'recieved {result[1]}',
                        id='setup.E005',
                    )
                )
    except Exception as e:
        errors.append(
            Error(
                f'Failed to connect to database: {e}',
                id='setup.E006',
            )
        )

    return errors


@register(CustomTags.custom_setup)
def nginx_check(app_configs, **kwargs):
    errors = []
    version = get_version_json()

    if version.get('target') == 'production':
        return []

    configs = [
        (settings.MEDIA_ROOT, settings.MEDIA_URL_PREFIX),
        (settings.STATIC_FILES_PATH, settings.STATIC_URL_PREFIX),
        (settings.STATIC_ROOT, settings.STATIC_URL_PREFIX),
    ]

    files_to_remove = []

    for dir, prefix in configs:
        base_url = f'{settings.INTERNAL_SITE_URL}{prefix}'
        file_path = os.path.join(dir, 'test.txt')
        file_url = f'{base_url}test.txt'

        if not os.path.exists(dir):
            errors.append(Error(f'{dir} does not exist', id='setup.E007'))

        try:
            with open(file_path, 'w') as f:
                f.write(dir)

            files_to_remove.append(file_path)
            response = requests.get(file_url)

            expected_config = (
                (response.status_code, 200),
                (response.text, dir),
                (response.headers.get('X-Served-By'), 'nginx'),
            )

            if any(item[0] != item[1] for item in expected_config):
                message = f'Failed to access {file_url}. {expected_config}'
                errors.append(Error(message, id='setup.E008'))

        except Exception as e:
            errors.append(
                Error(
                    f'Unknown error accessing {file_path} via {file_url}: {e}',
                    id='setup.E010',
                )
            )

    # Always remove the files we created.
    for file_path in files_to_remove:
        os.remove(file_path)

    return errors


class CoreConfig(AppConfig):
    name = 'olympia.core'
    verbose_name = 'Core'

    def ready(self):
        super().ready()

        import olympia.schema  # noqa: F401

        # Ignore Python warnings unless we're running in debug mode.
        if not settings.DEBUG:
            warnings.simplefilter('ignore')
