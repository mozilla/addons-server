from django import http

import amo
from amo.decorators import json_view, login_required
from addons.decorators import addon_view

from statsd import statsd


@login_required
@addon_view
@json_view
def verify_receipt(request, addon):
    """Returns the status for that addon."""
    with statsd.timer('marketplace.verification'):
        #TODO(andym): not sure what to do about refunded yet.
        if addon.type != amo.ADDON_WEBAPP:
            return http.HttpResponse(status=400)
        # If wanted we can use the watermark hash, however it's assumed the
        # users will be logged into AMO.
        if addon.is_premium():
            exists = addon.has_purchased(request.amo_user)
        else:
            exists = addon.installed.filter(user=request.amo_user).exists()
        return {'status': 'ok' if exists else 'invalid'}
