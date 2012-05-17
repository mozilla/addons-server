import jingo
from tower import ugettext as _

from django import http

from access import acl
from addons.decorators import addon_view_factory
from amo.decorators import json_view, login_required, post_required, write
from amo.utils import memoize_get
from lib.metrics import send_request
from lib.crypto.receipt import cef, SigningError

from mkt.ratings.models import Rating
from mkt.webapps.models import create_receipt, Installed, Webapp

addon_view = addon_view_factory(qs=Webapp.objects.valid)
addon_all_view = addon_view_factory(qs=Webapp.objects.all)


@addon_all_view
def detail(request, addon):
    """Product details page."""
    ratings = Rating.objects.latest().filter(addon=addon).order_by('-created')
    positive_ratings = ratings.filter(score=1)[:5]
    negative_ratings = ratings.filter(score=-1)[:5]
    return jingo.render(request, 'detail/app.html', {
        'product': addon,
        'ratings': ratings,
        'positive_ratings': positive_ratings,
        'negative_ratings': negative_ratings,
    })


@addon_all_view
def privacy(request, addon):
    is_dev = request.check_ownership(addon, require_owner=False,
                                     ignore_disabled=True)
    if not (addon.is_public() or acl.check_reviewer(request) or is_dev):
        raise http.Http404
    if not addon.privacy_policy:
        return http.HttpResponseRedirect(addon.get_url_path())
    return jingo.render(request, 'detail/privacy.html', {'product': addon})


@json_view
@addon_all_view
@login_required
@post_required
@write
def record(request, addon):
    is_dev = request.check_ownership(addon, require_owner=False,
                                     ignore_disabled=True)
    if not (addon.is_public() or acl.check_reviewer(request) or is_dev):
        raise http.Http404
    if addon.is_webapp():
        installed, c = Installed.objects.safer_get_or_create(addon=addon,
            user=request.amo_user)
        send_request('install', request, {
                        'app-domain': addon.domain_from_url(addon.origin),
                        'app-id': addon.pk})

        # Look up to see if its in the receipt cache and log if we have
        # to recreate it.
        receipt = memoize_get('create-receipt', installed.pk)
        error = ''
        cef(request, addon, 'request', 'Receipt requested')
        if not receipt:
            cef(request, addon, 'sign', 'Receipt signing')
            try:
                receipt = create_receipt(installed.pk)
            except SigningError:
                error = _('There was a problem installing the app.')

        return {'addon': addon.pk, 'receipt': receipt, 'error': error}
