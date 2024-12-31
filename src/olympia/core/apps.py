import logging
import os
import subprocess
import warnings
from io import StringIO
from pwd import getpwnam

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils.translation import gettext_lazy as _

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
    output = StringIO()
    version = get_version_json()

    # We only run this check in production images.
    if version.get('target') != 'production':
        return []

    try:
        call_command('compress_assets', dry_run=True, stdout=output)
        file_paths = output.getvalue().strip().split('\n')

        if not file_paths:
            errors.append(
                Error(
                    'No compressed asset files were found.',
                    id='setup.E003',
                )
            )
        else:
            for file_path in file_paths:
                if not os.path.exists(file_path):
                    error = f'Compressed asset file does not exist: {file_path}'
                    errors.append(
                        Error(
                            error,
                            id='setup.E003',
                        )
                    )
    except CommandError as e:
        errors.append(
            Error(
                f'Error running compress_assets command: {str(e)}',
                id='setup.E004',
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
        {
            'dir': settings.MEDIA_ROOT,
            'base_url': 'http://nginx/user-media/',
            'source': 'nginx',
        },
        {
            'dir': settings.STATIC_ROOT,
            'base_url': 'http://nginx/static/',
            'source': 'nginx',
        },
        {
            'dir': settings.STATIC_FILES_PATH,
            'base_url': 'http://nginx/static/',
            'source': 'olympia',
        },
    ]

    for config in configs:
        dir = config['dir']
        base_url = config['base_url']
        source = config['source']

        # Make a test file in the path and check it is accessible via the static url
        test_file_name = 'test.txt'
        test_file_content = 'test'
        test_file_path = os.path.join(dir, test_file_name)

        if not os.path.exists(dir):
            errors.append(
                Error(
                    f'{dir} does not exist',
                    id='setup.E007',
                )
            )

        try:
            with open(test_file_path, 'w') as f:
                f.write(test_file_content)

            test_file_url = f'{base_url}{test_file_name}'
            response = requests.get(test_file_url)

            if response.status_code != 200:
                errors.append(
                    Error(
                        f'Failed to access {test_file_url} '
                        f'with status code {response.status_code}',
                        id='setup.E008',
                    )
                )

            if response.text != test_file_content:
                errors.append(
                    Error(
                        f'Unexpected content in {test_file_url}, "{response.text}"',
                        id='setup.E009',
                    )
                )

            if response.headers.get('X-Served-By') != source:
                errors.append(
                    Error(
                        f'Expected file to be served by {source} '
                        f'recieved {response.headers["X-Served-By"]}',
                        id='setup.E010',
                    )
                )

        except Exception as e:
            errors.append(
                Error(
                    f'Unknown error accessing {config}: {e}',
                    id='setup.E010',
                )
            )
        finally:
            if os.path.exists(test_file_path):
                os.remove(test_file_path)

    return errors


class CoreConfig(AppConfig):
    name = 'olympia.core'
    verbose_name = _('Core')

    def ready(self):
        super().ready()

        # Ignore Python warnings unless we're running in debug mode.
        if not settings.DEBUG:
            warnings.simplefilter('ignore')
