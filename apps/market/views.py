from django import http

import amo
from amo.decorators import json_view, login_required
from addons.decorators import addon_view


@login_required
@addon_view
@json_view
def verify_receipt(request, addon):
    """Returns the status for that addon."""
    #TODO(andym): not sure what to do about refunded yet.
    if addon.type != amo.ADDON_WEBAPP:
        return http.HttpResponse(status=400)
    exists = addon.addonpurchase_set.filter(user=request.amo_user).exists()
    return {'status': 'ok' if exists else 'invalid'}
