import calendar
import time

from django.conf import settings
from django.db import transaction

import commonware.log
import jingo
import jwt
from tower import ugettext as _

from amo.decorators import json_view, post_required, write

from mkt.constants import regions
from mkt.developers.decorators import dev_required
from mkt.developers.models import AddonBlueViaConfig, BlueViaConfig

from . import forms

bluevia_log = commonware.log.getLogger('z.bluevia')


@json_view
@post_required
@transaction.commit_on_success
@dev_required(owner_for_post=True, webapp=True)
def bluevia_callback(request, addon_id, addon, webapp):
    developer_id = request.POST.get('developerId')
    status = request.POST.get('status')
    if status in ['registered', 'loggedin']:
        bluevia = BlueViaConfig.objects.create(user=request.amo_user,
                                               developer_id=developer_id)
        try:
            (AddonBlueViaConfig.objects.get(addon=addon)
             .update(bluevia_config=bluevia))
        except AddonBlueViaConfig.DoesNotExist:
            AddonBlueViaConfig.objects.create(addon=addon,
                                              bluevia_config=bluevia)
        bluevia_log.info('BlueVia account, %s, paired with %s app'
                         % (developer_id, addon_id))
    return {'error': False,
            'message': [_('You have successfully paired your BlueVia '
                          'account with the Marketplace.')],
            'html': jingo.render(
                request, 'developers/payments/includes/bluevia.html',
                dict(addon=addon, bluevia=bluevia)).content}


@json_view
@post_required
@transaction.commit_on_success
@dev_required(owner_for_post=True, webapp=True)
def bluevia_remove(request, addon_id, addon, webapp):
    """
    Unregisters BlueVia account from app.
    """
    try:
        bv = AddonBlueViaConfig.objects.get(addon=addon)
        developer_id = bv.bluevia_config.developer_id
        bv.delete()
        bluevia_log.info('BlueVia account, %s, removed from %s app'
                         % (developer_id, addon_id))
    except AddonBlueViaConfig.DoesNotExist as e:
        return {'error': True, 'message': [str(e)]}
    return {'error': False, 'message': []}


@json_view
@dev_required(webapp=True)
def get_bluevia_url(request, addon_id, addon, webapp):
    """
    Email choices:
        registered_data@user.com
        registered_no_data@user.com
    """
    data = {
        'email': request.GET.get('email', request.user.email),
        'locale': request.LANG,
        'country': getattr(request, 'REGION', regions.US).mcc
    }
    if addon.paypal_id:
        data['paypal'] = addon.paypal_id
    issued_at = calendar.timegm(time.gmtime())
    # JWT-specific fields.
    data.update({
        'aud': addon.id,  # app ID
        'typ': 'dev-registration',
        'iat': issued_at,
        'exp': issued_at + 3600,  # expires in 1 hour
        'iss': settings.SITE_URL,  # expires in 1 hour
    })
    signed_data = jwt.encode(data, settings.BLUEVIA_SECRET, algorithm='HS256')
    return {'error': False, 'message': [],
            'bluevia_origin': settings.BLUEVIA_ORIGIN,
            'bluevia_url': settings.BLUEVIA_URL + signed_data}
