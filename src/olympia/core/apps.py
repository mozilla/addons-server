import os
import sys
import logging
import warnings

import jingo
import jingo.monkey
import session_csrf
from django.apps import AppConfig
from django.core.management import call_command
from django.conf import settings
from django.utils import translation
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

        jingo.monkey.patch()

        jingo_env = jingo.get_env()
        jingo_env.install_gettext_translations(translation, newstyle=True)

        session_csrf.monkeypatch()

        self.configure_logging()
        self.load_product_details()
        self.set_recursion_limit()

    def configure_logging(self):
        """Configure the `logging` module to route logging based on settings
        in our various settings modules and defaults in
        `lib.log_settings_base`."""
        from olympia.lib.log_settings_base import log_configure

        log_configure()

    def load_product_details(self):
        """Fetch product details, if we don't already have them."""
        from product_details import product_details

        if not product_details.last_update:
            log.info('Product details missing, downloading...')
            call_command('update_product_details')
            product_details.__init__()  # reload the product details

    def set_recursion_limit(self):
        """Set explicit recursion limit if set in the environment.

        This is set here to make sure we're setting it always
        when we initialize Django, also when we're loading celery (which
        is calling django.setup too).

        This is only being used for the amo-validator so initializing this late
        should be fine.
        """
        if 'RECURSION_LIMIT' in os.environ:
            try:
                limit = int(os.environ['RECURSION_LIMIT'])
            except TypeError:
                log.warning('Unable to parse RECURSION_LIMIT "{}"'.format(
                    os.environ['RECURSION_LIMIT']))
            else:
                sys.setrecursionlimit(limit)
                log.info('Set RECURSION_LIMIT to {}'.format(limit))
