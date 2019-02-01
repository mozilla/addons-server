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

        self.enable_urllib_certificate_checking()

    def enable_urllib_certificate_checking(self):
        # From requests's packages/urllib3/contrib/pyopenssl.py
        import urllib3.contrib.pyopenssl
        urllib3.contrib.pyopenssl.inject_into_urllib3()
