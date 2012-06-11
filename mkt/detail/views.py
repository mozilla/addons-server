from django import http
from django.shortcuts import redirect

import jingo
from session_csrf import anonymous_csrf_exempt
from tower import ugettext as _
import waffle

from abuse.models import send_abuse_report
from access import acl
from addons.decorators import addon_view_factory
import amo
import amo.log
from amo.decorators import json_view, post_required, write
from amo.forms import AbuseForm
from amo.urlresolvers import reverse
from amo.utils import memoize_get
from lib.metrics import send_request
from lib.crypto.receipt import SigningError
from lib.cef_loggers import receipt_cef

from mkt.site import messages
from mkt.webapps.models import create_receipt, Installed, Webapp

addon_view = addon_view_factory(qs=Webapp.objects.valid)
addon_all_view = addon_view_factory(qs=Webapp.objects.all)


@addon_all_view
def detail(request, addon):
    """Product details page."""
    ctx = {
        'product': addon
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


def _record(request, addon):
    logged = request.user.is_authenticated()
    premium = addon.is_premium()
    allow_anon_install = waffle.switch_is_active('anonymous-free-installs')

    # Require login for premium.
    if not logged and (premium or not allow_anon_install):
        return redirect(reverse('users.login'))

    ctx = {'addon': addon.pk}

    # Don't generate receipts if we're allowing logged-out install.
    if logged or not allow_anon_install:
        is_dev = request.check_ownership(addon, require_owner=False,
                                     ignore_disabled=True)
        is_reviewer = acl.check_reviewer(request)
        if (not addon.is_webapp() or not addon.is_public() and
            not (is_reviewer or is_dev)):
            raise http.Http404

        if (premium and
            not addon.has_purchased(request.amo_user) and
            not is_reviewer and not is_dev):
            return http.HttpResponseForbidden()

        installed, c = Installed.objects.safer_get_or_create(addon=addon,
            user=request.amo_user)
        # Look up to see if its in the receipt cache and log if we have
        # to recreate it.
        receipt = memoize_get('create-receipt', installed.pk)
        error = ''
        receipt_cef.log(request, addon, 'request', 'Receipt requested')
        if not receipt:
            receipt_cef.log(request, addon, 'sign', 'Receipt signing')
            try:
                receipt = create_receipt(installed.pk)
            except SigningError:
                error = _('There was a problem installing the app.')

        ctx.update(receipt=receipt, error=error)
    else:
        if not addon.is_public() or not addon.is_webapp():
            raise http.Http404

    amo.log(amo.LOG.INSTALL_ADDON, addon)
    send_request('install', request, {
        'app-domain': addon.domain_from_url(addon.origin),
        'app-id': addon.pk
    })

    return ctx


@anonymous_csrf_exempt
@json_view
@addon_all_view
@post_required
@write
def record_anon(request, addon):
    return _record(request, addon)


@json_view
@addon_all_view
@post_required
@write
def record(request, addon):
    return _record(request, addon)
