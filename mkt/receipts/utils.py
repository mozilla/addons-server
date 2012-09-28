import calendar
import time
from urllib import urlencode

from django.conf import settings

import jwt

from access import acl
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import memoize
from lib.crypto.receipt import sign
from mkt.webapps.models import Installed


@memoize(prefix='create-receipt', time=60 * 10)
def create_receipt(installed_pk, flavour=None):
    assert flavour in [None, 'developer', 'reviewer'], (
           'Invalid flavour: %s' % flavour)

    installed = Installed.objects.get(pk=installed_pk)
    webapp = installed.addon
    origin = (settings.SITE_URL if webapp.is_packaged else webapp.origin)
    time_ = calendar.timegm(time.gmtime())

    product = {'url': origin, 'storedata': urlencode({'id': int(webapp.pk)})}

    # Generate different receipts for reviewers or developers.
    expiry = time_ + settings.WEBAPPS_RECEIPT_EXPIRY_SECONDS
    if flavour:
        if not (acl.action_allowed_user(installed.user, 'Apps', 'Review') or
                webapp.has_author(installed.user)):
            raise ValueError('User %s is not a reviewer or developer' %
                             installed.user.pk)

        if flavour == 'reviewer':
            expiry = time_ + (60 * 60 * 24)
        product['type'] = flavour
        verify = absolutify(reverse('receipt.verify', args=[webapp.app_slug]))
    else:
        verify = settings.WEBAPPS_RECEIPT_URL

    detail = reverse('account.purchases.receipt', args=[webapp.pk])
    reissue = webapp.get_purchase_url('reissue')
    receipt = dict(detail=absolutify(detail), exp=expiry, iat=time_,
                   iss=settings.SITE_URL, nbf=time_, product=product,
                   reissue=absolutify(reissue), typ='purchase-receipt',
                   user={'type': 'directed-identifier',
                         'value': installed.uuid},
                   verify=verify)

    if settings.SIGNING_SERVER_ACTIVE:
        # The shiny new code.
        return sign(receipt)
    else:
        # Our old bad code.
        return jwt.encode(receipt, get_key(), u'RS512')


def get_key():
    """Return a key for using with encode."""
    return jwt.rsa_load(settings.WEBAPPS_RECEIPT_KEY)
