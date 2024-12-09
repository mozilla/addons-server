import logging
import os
import subprocess
import warnings
from io import StringIO

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils.translation import gettext_lazy as _

from olympia.core.utils import (
    REQUIRED_VERSION_KEYS,
    get_version_json,
)


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
def version_check(app_configs, **kwargs):
    """Check the (virtual) version.json file exists and has the correct keys."""
    errors = []

    version_json = get_version_json()

    for key in REQUIRED_VERSION_KEYS:
        # All required keys must be present.
        if key not in version_json:
            errors.append(
                Error(
                    f'Expected key: {key} to exist',
                    id='setup.E002',
                )
            )

    return errors


@register(CustomTags.custom_setup)
def host_check(app_configs, **kwargs):
    """Check that the host settings are valid."""
    errors = []

    if (
        settings.OLYMPIA_MOUNT is None or settings.OLYMPIA_MOUNT == 'production'
    ) and os.path.exists('/data/olympia/Makefile-os'):
        errors.append(
            Error(
                'Makefile-os should be excluded by dockerignore',
                id='setup.E003',
            )
        )

    # If we are on a production image, or the OLYMPIA_UID is not defined,
    # then we expect to retain the original uid of 9500.
    if settings.OLYMPIA_UID is None:
        if os.getuid() != 9500:
            return [
                Error(
                    'Expected user uid to be 9500',
                    id='setup.E002',
                )
            ]

    return errors


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

    return errors


class CoreConfig(AppConfig):
    name = 'olympia.core'
    verbose_name = _('Core')

    def ready(self):
        super().ready()

        # Ignore Python warnings unless we're running in debug mode.
        if not settings.DEBUG:
            warnings.simplefilter('ignore')
