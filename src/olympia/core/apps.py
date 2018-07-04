import logging
import os
import sys
import warnings

from django.apps import AppConfig
from django.conf import settings
from django.core.management import call_command
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

        self.load_product_details()
        self.set_recursion_limit()
        self.enable_urllib_certificate_checking()

    def enable_urllib_certificate_checking(self):
        # From requests's packages/urllib3/contrib/pyopenssl.py
        import urllib3.contrib.pyopenssl
        urllib3.contrib.pyopenssl.inject_into_urllib3()

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
