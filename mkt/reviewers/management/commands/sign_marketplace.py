import os

from django.conf import settings
from django.core.management.base import BaseCommand

import commonware.log

from mkt.site.views import get_package_path
from lib.crypto.packaged import sign_app

log = commonware.log.getLogger('z.crypto')


def sign_marketplace(src=None):
    # Note: not using storage because I think this all happens locally.
    src = src or get_package_path(signed=False)
    dest = get_package_path(signed=True)

    if os.path.exists(dest):
        log.info('File already exists: %s' % dest)
        raise OSError('File already exists: %s' % dest)

    log.info('Signing %s' % src)
    sign_app(src, dest)


class Command(BaseCommand):
    """Sign the marketplace packaged app."""

    def handle(self, *args, **options):
        sign_marketplace()
