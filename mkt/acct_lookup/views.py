from datetime import datetime, timedelta

from django.db import connection
from django.db.models import Sum
from django.shortcuts import get_object_or_404

import jingo

from addons.models import Addon
import amo
from amo.decorators import login_required, permission_required, json_view
from amo.urlresolvers import reverse
from amo.utils import paginate
from apps.access import acl
from apps.bandwagon.models import Collection
from devhub.views import _get_items
from devhub import helpers
from devhub.models import ActivityLog
from market.models import Refund
from mkt.account.utils import purchase_list
from mkt.webapps.models import Installed
from stats.models import DownloadCount
from users.models import UserProfile


@login_required
@permission_required('AccountLookup', 'View')
def home(request):
    return jingo.render(request, 'acct_lookup/home.html', {})


@login_required
@permission_required('AccountLookup', 'View')
def user_summary(request, user_id):
    user = get_object_or_404(UserProfile, pk=user_id)
    is_admin = acl.action_allowed(request, 'Users', 'Edit')
    app_summary = _app_summary(user.pk)
    # All refunds that this user has requested (probably as a consumer).
    req = Refund.objects.filter(contribution__user=user)
    # All instantly-approved refunds that this user has requested.
    appr = req.filter(status=amo.REFUND_APPROVED_INSTANT)
    refund_summary = {'approved': appr.count(),
                      'requested': req.count()}
    # TODO: This should return all `addon` types and not just webapps.
    # -- currently get_details_url() fails on non-webapps so this is a
    # temp fix.
    user_addons = (user.addons.filter(type=amo.ADDON_WEBAPP)
                              .order_by('-created'))
    user_addons = paginate(request, user_addons, per_page=15)
    paypal_ids = (user.addons.exclude(paypal_id='').distinct('paypal_id')
                             .values_list('paypal_id', flat=True))
    payment_data = []
    for ad in user.addons.exclude(payment_data=None):
        payment_data.append(ad.payment_data)
    return jingo.render(request, 'acct_lookup/user_summary.html',
                        {'account': user,
                         'app_summary': app_summary,
                         'is_admin': is_admin,
                         'refund_summary': refund_summary,
                         'user_addons': user_addons,
                         'payment_data': payment_data,
                         'paypal_ids': paypal_ids})


@login_required
@permission_required('AccountLookup', 'View')
def app_summary(request, addon_id):
    app = get_object_or_404(Addon, pk=addon_id)
    authors = (app.authors.filter(addonuser__role__in=(amo.AUTHOR_ROLE_DEV,
                                                       amo.AUTHOR_ROLE_OWNER))
                          .order_by('display_name'))
    if app.premium and app.premium.price:
        price = app.premium.price
    else:
        price = None
    return jingo.render(request, 'acct_lookup/app_summary.html',
                        {'app': app,
                         'price': price,
                         'abuse_reports': app.abuse_reports.count(),
                         'downloads': _app_downloads(app),
                         'authors': authors})


def _app_downloads(app):
    stats = {'last_7_days': 0,
             'last_24_hours': 0,
             'alltime': 0}
    if app.is_webapp():
        Data = Installed
    else:
        Data = DownloadCount
    _7_days_ago = datetime.now() - timedelta(days=7)
    qs = Data.objects.filter(addon=app)
    if app.is_webapp():
        _24_hr_ago = datetime.now() - timedelta(hours=24)
        stats['last_24_hours'] = (qs.filter(created__gte=_24_hr_ago)
                                    .count())
        stats['last_7_days'] = (qs.filter(created__gte=_7_days_ago)
                                  .count())
        stats['alltime'] = qs.count()
    else:
        # Non-app add-ons.

        def sum_(qs):
            return qs.aggregate(total=Sum('count'))['total'] or 0

        yesterday = datetime.now().date() - timedelta(days=1)
        stats['last_24_hours'] = sum_(qs.filter(date__gt=yesterday))
        stats['last_7_days'] = sum_(qs.filter(date__gte=_7_days_ago.date()))
        stats['alltime'] = sum_(qs)
    return stats


@login_required
@permission_required('AccountLookup', 'View')
def user_purchases(request, user_id):
    """Shows the purchase page for another user."""
    user = get_object_or_404(UserProfile, pk=user_id)
    products, contributions, listing = purchase_list(request, user, None)
    return jingo.render(request, 'acct_lookup/user_purchases.html',
                        {'pager': products,
                         'account': user,
                         'listing_filter': listing,
                         'contributions': contributions,
                         'single': bool(None),
                         'show_link': False})


@login_required
@permission_required('AccountLookup', 'View')
def user_activity(request, user_id):
    """Shows the user activity page for another user."""
    user = get_object_or_404(UserProfile, pk=user_id)
    products, contributions, listing = purchase_list(request, user, None)

    collections = Collection.objects.filter(author=user_id)
    user_items = ActivityLog.objects.for_user(user).exclude(
        action__in=amo.LOG_HIDE_DEVELOPER)
    admin_items = ActivityLog.objects.for_user(user).filter(
        action__in=amo.LOG_HIDE_DEVELOPER)
    amo.log(amo.LOG.ADMIN_VIEWED_LOG, request.amo_user, user=user)
    return jingo.render(request, 'acct_lookup/user_activity.html',
                        {'pager': products,
                         'account': user,
                         'listing_filter': listing,
                         'collections': collections,
                         'contributions': contributions,
                         'single': bool(None),
                         'user_items': user_items,
                         'admin_items': admin_items,
                         'show_link': False})


@login_required
@permission_required('AccountLookup', 'View')
@json_view
def user_search(request):
    results = []
    query = request.GET.get('q', '').lower()
    fields = ('username', 'display_name', 'email')
    if query.isnumeric():
        # id is added implictly by the ES filter. Add it explicitly:
        fields = ['id'] + list(fields)
        qs = UserProfile.objects.filter(pk=query).values(*fields)
    else:
        qs = (UserProfile.search()
                         .query(or_=dict(username__startswith=query,
                                         display_name__fuzzy=query,
                                         email__fuzzy=query))
                         .values_dict(*fields))
    for user in qs:
        user['url'] = reverse('acct_lookup.user_summary', args=[user['id']])
        user['name'] = user['username']
        results.append(user)
    return {'results': results}


@login_required
@permission_required('AccountLookup', 'View')
@json_view
def app_search(request):
    results = []
    query = request.GET.get('q', '').lower()
    fields = ['name', 'app_slug']
    non_es_fields = ['id', 'name__localized_string'] + fields
    if query.isnumeric():
        qs = Addon.objects.filter(pk=query).values(*non_es_fields)
    else:
        # Try to load by GUID:
        qs = Addon.objects.filter(guid=query).values(*non_es_fields)
        if not qs.count():
            # Give up on GUID, assume it's a search.
            qs = Addon.search().query(name__fuzzy=query).values_dict(*fields)
    for app in qs:
        app['url'] = reverse('acct_lookup.app_summary', args=[app['id']])
        # ES returns a list of localized names but database queries do not.
        if type(app['name']) != list:
            app['name'] = [app['name__localized_string']]
        for name in app['name']:
            dd = app.copy()
            dd['name'] = name
            results.append(dd)
    return {'results': results}


def _app_summary(user_id):
    sql = """
        select currency,
            sum(case when type=%(purchase)s then 1 else 0 end)
                as app_total,
            sum(case when type=%(purchase)s then amount else 0.0 end)
                as app_amount,
            sum(case when type=%(inapp)s then 1 else 0 end)
                as inapp_total,
            sum(case when type=%(inapp)s then amount else 0.0 end)
                as inapp_amount
        from stats_contributions
        where user_id=%(user_id)s
        group by currency
    """
    cursor = connection.cursor()
    cursor.execute(sql, {'user_id': user_id,
                         'purchase': amo.CONTRIB_PURCHASE,
                         'inapp': amo.CONTRIB_INAPP})
    summary = {'app_total': 0,
               'app_amount': {},
               'inapp_total': 0,
               'inapp_amount': {}}
    cols = [cd[0] for cd in cursor.description]
    while 1:
        row = cursor.fetchone()
        if not row:
            break
        row = dict(zip(cols, row))
        for cn in cols:
            if cn.endswith('total'):
                summary[cn] += row[cn]
            elif cn.endswith('amount'):
                summary[cn][row['currency']] = row[cn]
    return summary
