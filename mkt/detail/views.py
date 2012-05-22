from django import http
from django.shortcuts import redirect

import jingo
from session_csrf import anonymous_csrf_exempt
from tower import ugettext as _

from abuse.models import send_abuse_report
from access import acl
from addons.decorators import addon_view_factory
from amo.decorators import json_view, login_required, post_required, write
from amo.forms import AbuseForm
from amo.utils import memoize_get
from lib.metrics import send_request
from lib.crypto.receipt import cef, SigningError

from mkt.ratings.models import Rating
from mkt.site import messages
from mkt.webapps.models import create_receipt, Installed, Webapp

addon_view = addon_view_factory(qs=Webapp.objects.valid)
addon_all_view = addon_view_factory(qs=Webapp.objects.all)


@addon_all_view
def detail(request, addon):
    """Product details page."""
    ratings = Rating.objects.latest().filter(addon=addon).order_by('-created')
    positive_ratings = list(ratings.filter(score=1)[:5])
    negative_ratings = list(ratings.filter(score=-1)[:5])
    sorted_ratings = sorted(positive_ratings + negative_ratings,
                            key=lambda x: x.created, reverse=True)
    ctx = {
        'product': addon,
        'ratings': ratings,
        'ratings': sorted_ratings,
        'review_history': [[2, 12], [50, 2], [3, 0], [4, 1]]
    }
    if addon.is_public():
        ctx['abuse_form'] = AbuseForm(request=request)
    return jingo.render(request, 'detail/app.html', ctx)


@addon_all_view
def privacy(request, addon):
    is_dev = request.check_ownership(addon, require_owner=False,
                                     ignore_disabled=True)
    if not (addon.is_public() or acl.check_reviewer(request) or is_dev):
        raise http.Http404
    if not addon.privacy_policy:
        return http.HttpResponseRedirect(addon.get_url_path())
    return jingo.render(request, 'detail/privacy.html', {'product': addon})


@anonymous_csrf_exempt
@addon_view
def abuse(request, addon):
    form = AbuseForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        send_abuse_report(request, addon, form.cleaned_data['text'])
        messages.success(request, _('Abuse reported.'))
        return redirect(addon.get_url_path())
    else:
        return jingo.render(request, 'detail/abuse.html',
                            {'product': addon, 'abuse_form': form})


@anonymous_csrf_exempt
@addon_view
def abuse_recaptcha(request, addon):
    form = AbuseForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        send_abuse_report(request, addon, form.cleaned_data['text'])
        messages.success(request, _('Abuse reported.'))
        return redirect(addon.get_url_path())
    else:
        return jingo.render(request, 'detail/abuse_recaptcha.html',
                            {'product': addon, 'abuse_form': form})


@json_view
@addon_all_view
@login_required
@post_required
@write
def record(request, addon):
    is_dev = request.check_ownership(addon, require_owner=False,
                                     ignore_disabled=True)
    if (not (addon.is_public() or acl.check_reviewer(request)
        or is_dev or not addon.is_webapp())):
        raise http.Http404

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
