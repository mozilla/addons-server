import logging
import warnings

from django.apps import AppConfig
from django.conf import settings
from django.utils.translation import ugettext_lazy as _


log = logging.getLogger('z.startup')


class CoreConfig(AppConfig):
    name = 'olympia.core'
    verbose_name = _('Core')

    def ready(self):
        super(CoreConfig, self).ready()

        # Ignore Python warnings unless we're running in debug mode.
        if not settings.DEBUG:
            warnings.simplefilter('ignore')

        self.enable_post_request_task()

    def enable_post_request_task(self):
        """Import post_request_task so that it can listen to `request_started`
        signal before the first request is handled."""
        import post_request_task.task  # noqa
