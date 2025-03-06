import json
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

    # We only run this check in production images.
    if settings.TARGET != 'production':
        return []

    try:
        call_command('compress_assets', dry_run=True, stdout=output)
        stripped_output = output.getvalue().strip()

        if stripped_output:
            file_paths = stripped_output.split('\n')
            for file_path in file_paths:
                if not os.path.exists(file_path):
                    error = f'Compressed asset file does not exist: {file_path}'
                    errors.append(
                        Error(
                            error,
                            id='setup.E003',
                        )
                    )
        else:
            errors.append(
                Error(
                    'No compressed asset files were found.',
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

    if not os.path.exists(settings.STATIC_BUILD_MANIFEST_PATH):
        errors.append(
            Error(
                (
                    'Static build manifest file '
                    f'does not exist: {settings.STATIC_BUILD_MANIFEST_PATH}'
                ),
                id='setup.E003',
            )
        )
    else:
        with open(settings.STATIC_BUILD_MANIFEST_PATH, 'r') as f:
            manifest = json.load(f)

            for name, asset in manifest.items():
                # Assets compiled by vite are in the static root directory
                # after running collectstatic. So we should look there.
                path = os.path.join(settings.STATIC_ROOT, asset['file'])
                if not os.path.exists(path):
                    errors.append(
                        Error(
                            (
                                f'Static asset {name} does not exist at '
                                f'expected path: {path}'
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

    # We only run this check in local environments
    # Becuase that is the only environment where the local
    # nginx server is routing requests.
    if settings.ENV != 'local':
        return []

    nginx_routing_configs = [
        {
            'document_root': settings.MEDIA_ROOT,
            'url_prefix': 'user-media',
            'path': True,
            'served_by': 'nginx',
        },
        {
            'document_root': settings.STATIC_FILES_PATH,
            'url_prefix': 'static',
            'path': 'admin/js/core.js',
            # In production images, we expect nginx to have the static file
            # otherwise the request will be redirected to olympia.
            'served_by': 'nginx' if settings.TARGET == 'production' else 'olympia',
        },
        {
            'document_root': settings.STATIC_FILES_PATH,
            'url_prefix': 'static',
            'path': True,
            # In production images, olympia will strictly serve files from STATIC_ROOT
            # so we expect the request to pass only on non production images.
            'served_by': None if settings.TARGET == 'production' else 'olympia',
        },
        {
            'document_root': settings.STATIC_ROOT,
            'url_prefix': 'static',
            'path': True,
            # STATIC_ROOT will be available over nginx in all local environments.
            # We rely on make up to clean the STATIC_ROOT directory on no production
            # images to ensure we serve development files.
            'served_by': 'nginx',
        },
    ]

    def process_request(url_prefix, path, served_by=None):
        url = f'http://nginx/{url_prefix}/{path}'
        response = requests.get(url)

        status_code = 404 if served_by is None else 200

        if response.status_code != status_code:
            errors.append(
                Error(
                    (
                        f'Expected {status_code} for {url}, '
                        f'received {response.status_code}'
                    ),
                    id='setup.E007',
                )
            )
        elif served_by is not None:
            if response.headers.get('X-Served-By') != served_by:
                errors.append(
                    Error(
                        (
                            f'Expected {url} to be served by {served_by}, '
                            f'received {response.headers.get("X-Served-By")}'
                        ),
                        id='setup.E007',
                    )
                )

    for config in nginx_routing_configs:
        # If the path is a string, we expect the file to already exist
        if type(config['path']) == str:
            process_request(config['url_prefix'], config['path'], config['served_by'])
        else:
            file_name = 'test.txt'
            file_path = os.path.join(config['document_root'], file_name)
            # First expect the request to fail while the path does not exist
            process_request(config['url_prefix'], file_name, None)
            # Then create the file and expect the request to succeed
            with open(file_path, 'w') as f:
                f.write('test')
            try:
                process_request(config['url_prefix'], file_name, config['served_by'])
            finally:
                os.remove(file_path)

    return errors


class CoreConfig(AppConfig):
    name = 'olympia.core'
    verbose_name = _('Core')

    def ready(self):
        super().ready()

        # Ignore Python warnings unless we're running in debug mode.
        if not settings.DEBUG:
            warnings.simplefilter('ignore')
