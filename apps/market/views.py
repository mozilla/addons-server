from django import http

import amo
from amo.decorators import json_view, login_required
from addons.decorators import addon_view
from webapps.models import Webapp

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
        exists = addon.has_purchased(request.amo_user)
        return {'status': 'ok' if exists else 'invalid'}


@login_required
@json_view
def get_manifest_urls(request):
    """
    Returns the manifest urls for a series of apps. This will be filtered
    down the apps that the user has purchased.
    """
    ids = [int(i) for i in request.GET.getlist('ids')]
    ids = set(request.amo_user.purchase_ids()).intersection(ids)
    return list(Webapp.objects.filter(id__in=ids)
                              .values('id', 'manifest_url'))
