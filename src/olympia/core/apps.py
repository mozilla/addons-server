import logging
import subprocess
import warnings

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Tags, register
from django.utils.translation import gettext_lazy as _


log = logging.getLogger('z.startup')


class CustomTags(Tags):
    custom_setup = 'setup'


@register(CustomTags.custom_setup)
def uwsgi_check(app_configs, **kwargs):
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


class CoreConfig(AppConfig):
    name = 'olympia.core'
    verbose_name = _('Core')

    def ready(self):
        super().ready()

        # Ignore Python warnings unless we're running in debug mode.
        if not settings.DEBUG:
            warnings.simplefilter('ignore')

        self.enable_post_request_task()

    def enable_post_request_task(self):
        """Import post_request_task so that it can listen to `request_started`
        signal before the first request is handled."""
        import post_request_task.task  # noqa
