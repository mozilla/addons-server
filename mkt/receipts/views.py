from django import http
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt

import commonware.log
import jingo
from session_csrf import anonymous_csrf_exempt
from tower import ugettext as _
import waffle

from access import acl
from addons.decorators import addon_view_factory
import amo
import amo.log
from amo.decorators import login_required
from amo.decorators import json_view, post_required, write
from amo.urlresolvers import reverse
from amo.utils import memoize_get
from devhub.models import AppLog
from editors.views import reviewer_required
from lib.metrics import send_request
from lib.crypto.receipt import SigningError
from lib.cef_loggers import receipt_cef
from mkt.webapps.models import Installed, Webapp
from services.verify import Verify
from users.models import UserProfile

from .utils import create_receipt


log = commonware.log.getLogger('z.receipts')
addon_view = addon_view_factory(qs=Webapp.objects.valid)
addon_all_view = addon_view_factory(qs=Webapp.objects.all)


@login_required
@addon_view
def reissue(request, addon):
    reissue = not addon.is_premium()
    if addon.is_premium() and addon.has_purchased(request.amo_user):
        reissue = True
    return jingo.render(request, 'receipts/reissue.html',
                        {'reissue': reissue, 'app': addon})


def _record(request, addon):
    # TODO(andym): simplify this.
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
            user=request.amo_user, source=request.GET.get('src', ''),
            device_type=request.POST.get('device_type', ''),
            is_chromeless=request.POST.get('chromeless', False),
            user_agent=request.POST.get('user_agent', ''))
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


@csrf_exempt
@addon_all_view
@post_required
def verify(request, addon):
    receipt = request.raw_post_data
    verify = Verify(addon.pk, receipt, request)
    output = verify(check_purchase=False)

    # Only reviewers or the developers can use this which is different
    # from the standard receipt verification. The user is contained in the
    # receipt.
    if verify.user_id:
        try:
            user = UserProfile.objects.get(pk=verify.user_id)
        except UserProfile.DoesNotExist:
            user = None

        if user and (acl.action_allowed_user(user, 'Apps', 'Review')
            or addon.has_author(user)):
            amo.log(amo.LOG.RECEIPT_CHECKED, addon, user=user)
            return http.HttpResponse(output, verify.get_headers(len(output)))

    return http.HttpResponse(verify.invalid(),
                             verify.get_headers(verify.invalid()))


@addon_all_view
@json_view
@post_required
def issue(request, addon):
    user = request.amo_user
    review = acl.action_allowed_user(user, 'Apps', 'Review') if user else None
    developer = addon.has_author(user)
    if not (review or developer):
        return http.HttpResponseForbidden()

    installed, c = Installed.objects.safer_get_or_create(addon=addon,
                                                         user=request.amo_user)
    error = ''
    flavour = 'reviewer' if review else 'developer'
    receipt_cef.log(request, addon, 'sign', 'Receipt signing for %s' % flavour)
    try:
        receipt = create_receipt(installed.pk, flavour=flavour)
    except SigningError:
        error = _('There was a problem installing the app.')

    return {'addon': addon.pk, 'receipt': receipt, 'error': error}


@addon_all_view
@json_view
@reviewer_required
def check(request, addon):
    qs = (AppLog.objects.order_by('-created')
                .filter(addon=addon,
                        activity_log__action=amo.LOG.RECEIPT_CHECKED.id))
    return {'status': qs.exists()}
