import calendar
import time
from urllib import urlencode

from django.conf import settings

import jwt
from nose.tools import nottest

from access import acl
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from lib.crypto.receipt import sign


def create_receipt(installed, flavour=None):
    assert flavour in [None, 'developer', 'reviewer'], (
           'Invalid flavour: %s' % flavour)

    webapp = installed.addon
    time_ = calendar.timegm(time.gmtime())
    typ = 'purchase-receipt'

    product = {'storedata': urlencode({'id': int(webapp.pk)}),
               # Trunion needs to see https:// URLs.
               'url': settings.SITE_URL
                      if webapp.is_packaged else webapp.origin}

    # Generate different receipts for reviewers or developers.
    expiry = time_ + settings.WEBAPPS_RECEIPT_EXPIRY_SECONDS
    if flavour:
        if not (acl.action_allowed_user(installed.user, 'Apps', 'Review') or
                webapp.has_author(installed.user)):
            raise ValueError('User %s is not a reviewer or developer' %
                             installed.user.pk)

        # Developer and reviewer receipts should expire after 24 hours.
        expiry = time_ + (60 * 60 * 24)
        typ = flavour + '-receipt'
        verify = absolutify(reverse('receipt.verify', args=[webapp.guid]))
    else:
        verify = settings.WEBAPPS_RECEIPT_URL

    reissue = absolutify(reverse('receipt.reissue'))
    receipt = dict(exp=expiry, iat=time_,
                   iss=settings.SITE_URL, nbf=time_, product=product,
                   # TODO: This is temporary until detail pages get added.
                   detail=absolutify(reissue),  # Currently this is a 404.
                   reissue=absolutify(reissue),  # Currently this is a 404.
                   typ=typ,
                   user={'type': 'directed-identifier',
                         'value': installed.uuid},
                   verify=verify)

    if settings.SIGNING_SERVER_ACTIVE:
        # The shiny new code.
        return sign(receipt)
    else:
        # Our old bad code.
        return jwt.encode(receipt, get_key(), u'RS512')


@nottest
def create_test_receipt(root, status):
    time_ = calendar.timegm(time.gmtime())
    detail = absolutify(reverse('receipt.test.details'))
    receipt = {
        'detail': absolutify(detail),
        'exp': time_ + (60 * 60 * 24),
        'iat': time_,
        'iss': settings.SITE_URL,
        'nbf': time_,
        'product': {
            'storedata': urlencode({'id': 0}),
            'url': root,
        },
        'reissue': detail,
        'typ': 'test-receipt',
        'user': {
            'type': 'directed-identifier',
            'value': 'none'
        },
        'verify': absolutify(reverse('receipt.test.verify',
                                     kwargs={'status': status}))

    }
    if settings.SIGNING_SERVER_ACTIVE:
        return sign(receipt)
    else:
        return jwt.encode(receipt, get_key(), u'RS512')


def get_key():
    """Return a key for using with encode."""
    return jwt.rsa_load(settings.WEBAPPS_RECEIPT_KEY)
