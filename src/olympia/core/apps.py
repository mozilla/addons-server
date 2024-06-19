import logging
import subprocess
import warnings

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Tags, register
from django.utils.translation import gettext_lazy as _

from olympia.core.utils import get_version_json


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
    """Check the version.json file exists and has the correct keys."""
    required_keys = ['version', 'build', 'commit', 'source']

    version = get_version_json()

    if not version:
        return [
            Error(
                'version.json is missing',
                id='setup.E002',
            )
        ]

    missing_keys = [key for key in required_keys if key not in version]

    if missing_keys:
        return [
            Error(
                f'{", ".join(missing_keys)} is missing from version.json',
                id='setup.E002',
            )
        ]

    return []


class CoreConfig(AppConfig):
    name = 'olympia.core'
    verbose_name = _('Core')

    def ready(self):
        super().ready()

        # Ignore Python warnings unless we're running in debug mode.
        if not settings.DEBUG:
            warnings.simplefilter('ignore')
