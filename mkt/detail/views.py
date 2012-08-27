from django import http
from django.shortcuts import redirect

import jingo
from session_csrf import anonymous_csrf_exempt
from tower import ugettext as _

from abuse.models import send_abuse_report
from access import acl
from addons.decorators import addon_view_factory
import amo
from amo.decorators import login_required, permission_required
from amo.forms import AbuseForm
from amo.utils import paginate
from devhub.models import ActivityLog
from reviews.models import GroupedRating, Review
from reviews.views import get_flags

from mkt.site import messages
from mkt.webapps.models import Webapp

addon_view = addon_view_factory(qs=Webapp.objects.valid)
addon_all_view = addon_view_factory(qs=Webapp.objects.all)


@addon_all_view
def detail(request, addon):
    """Product details page."""
    reviews = Review.objects.latest().filter(addon=addon)
    ctx = {
        'product': addon,
        'reviews': reviews[:2],
        'flags': get_flags(request, reviews),
        'has_review': request.user.is_authenticated() and
                      reviews.filter(user=request.user.id).exists(),
        'grouped_ratings': GroupedRating.get(addon.id),
        'details_page': True
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


@login_required
@permission_required('AccountLookup', 'View')
@addon_all_view
def app_activity(request, addon):
    """Shows the app activity age for single app."""

    user_items = ActivityLog.objects.for_apps([addon]).exclude(
        action__in=amo.LOG_HIDE_DEVELOPER)
    admin_items = ActivityLog.objects.for_apps([addon]).filter(
        action__in=amo.LOG_HIDE_DEVELOPER)

    user_items = paginate(request, user_items, per_page=20)
    admin_items = paginate(request, admin_items, per_page=20)

    return jingo.render(request, 'detail/app_activity.html',
                        {'admin_items': admin_items,
                         'product': addon,
                         'user_items': user_items})
