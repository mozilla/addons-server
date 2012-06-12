import calendar
import time
import jwt
import time

from django.conf import settings
from amo.helpers import absolutify
from amo.urlresolvers import reverse

from access import acl
from urllib import urlencode
from lib.crypto.receipt import sign

from amo.utils import memoize
from mkt.webapps.models import Installed


@memoize(prefix='create-receipt', time=60 * 10)
def create_receipt(installed_pk, flavour=None):
    assert flavour in [None, 'author', 'reviewer'], (
           'Invalid flavour: %s' % flavour)

    installed = Installed.objects.get(pk=installed_pk)
    addon_pk = installed.addon.pk
    time_ = calendar.timegm(time.gmtime())
    product = {'url': installed.addon.origin,
               'storedata': urlencode({'id': int(addon_pk)})}

    # Generate different receipts for reviewers or authors.
    if flavour in ['author', 'reviewer']:
        if not (acl.action_allowed_user(installed.user, 'Apps', 'Review') or
                installed.addon.has_author(installed.user)):
            raise ValueError('User %s is not a reviewer or author' %
                             installed.user.pk)

        expiry = time_ + (60 * 60 * 24)
        product['type'] = flavour
        verify = absolutify(reverse('receipt.verify',
                                    args=[installed.addon.app_slug]))
    else:
        expiry = time_ + settings.WEBAPPS_RECEIPT_EXPIRY_SECONDS
        verify = '%s%s' % (settings.WEBAPPS_RECEIPT_URL, addon_pk)

    detail = reverse('account.purchases.receipt', args=[addon_pk])
    reissue = installed.addon.get_purchase_url('reissue')
    receipt = dict(detail=absolutify(detail), exp=expiry, iat=time_,
                   iss=settings.SITE_URL, nbf=time_, product=product,
                   reissue=absolutify(reissue), typ='purchase-receipt',
                   user={'type': 'directed-identifier',
                         'value': installed.uuid},
                   verify=absolutify(verify))

    if settings.SIGNING_SERVER_ACTIVE:
        # The shiny new code.
        return sign(receipt)
    else:
        # Our old bad code.
        return jwt.encode(receipt, get_key(), u'RS512')


def get_key():
    """Return a key for using with encode."""
    return jwt.rsa_load(settings.WEBAPPS_RECEIPT_KEY)
