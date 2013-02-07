from datetime import datetime, timedelta
import hashlib
import uuid

from django.db import connection
from django.db.models import Sum, Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
from babel import numbers
from slumber.exceptions import HttpClientError, HttpServerError
from tower import ugettext as _

import amo
from addons.models import Addon
from amo.decorators import (login_required, permission_required, post_required,
                            json_view)
from amo.urlresolvers import reverse
from amo.utils import paginate
from apps.access import acl
from apps.bandwagon.models import Collection
from devhub.models import ActivityLog
from elasticutils.contrib.django import S
from lib.pay_server import client
from market.models import AddonPaymentData, Refund
from mkt.constants.payments import (COMPLETED, FAILED, PENDING,
                                    REFUND_STATUSES)
from mkt.account.utils import purchase_list
from mkt.lookup.forms import TransactionRefundForm, TransactionSearchForm
from mkt.lookup.tasks import (email_buyer_refund_approved,
                              email_buyer_refund_pending)
from mkt.site import messages
from mkt.webapps.models import Installed
from stats.models import DownloadCount, Contribution
from users.models import UserProfile

log = commonware.log.getLogger('z.lookup')


@login_required
@permission_required('AccountLookup', 'View')
def home(request):
    tx_form = TransactionSearchForm()

    return jingo.render(request, 'lookup/home.html', {'tx_form': tx_form})


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
    paypal_ids = set(user.addons.exclude(paypal_id='')
                                .values_list('paypal_id', flat=True))

    payment_data = (AddonPaymentData.objects.filter(addon__authors=user)
                    .values(*AddonPaymentData.address_fields())
                    .distinct())

    return jingo.render(request, 'lookup/user_summary.html',
                        {'account': user,
                         'app_summary': app_summary,
                         'is_admin': is_admin,
                         'refund_summary': refund_summary,
                         'user_addons': user_addons,
                         'payment_data': payment_data,
                         'paypal_ids': paypal_ids})


@login_required
@permission_required('Transaction', 'View')
def transaction_summary(request, tx_uuid):
    tx_data = _transaction_summary(tx_uuid)
    if not tx_data:
        raise Http404

    tx_form = TransactionSearchForm()
    tx_refund_form = TransactionRefundForm()

    return jingo.render(request, 'lookup/transaction_summary.html',
                        dict({'uuid': tx_uuid, 'tx_form': tx_form,
                              'tx_refund_form': tx_refund_form}.items() +
                             tx_data.items()))


def _transaction_summary(tx_uuid):
    """Get transaction details from Solitude API."""
    contrib = get_object_or_404(Contribution, uuid=tx_uuid)
    refund_contribs = contrib.get_refund_contribs()
    refund_contrib = refund_contribs[0] if refund_contribs.exists() else None

    # Get refund status.
    refund_status = None
    if refund_contrib and refund_contrib.refund.status == amo.REFUND_PENDING:
        try:
            refund_status = REFUND_STATUSES[client.api.bango.refund.status.get(
                data={'uuid': refund_contrib.transaction_id})['status']]
        except HttpServerError:
            refund_status = _('Currently unable to retrieve refund status.')

    return {
        # Solitude data.
        'refund_status': refund_status,

        # Zamboni data.
        'app': contrib.addon,
        'contrib': contrib,
        'related': contrib.related,
        'type': amo.CONTRIB_TYPES.get(contrib.type, _('Incomplete')),
        # Whitelist what is refundable.
        'is_refundable': ((contrib.type == amo.CONTRIB_PURCHASE)
                          and not refund_contrib),
    }


@post_required
@login_required
@permission_required('Transaction', 'Refund')
def transaction_refund(request, tx_uuid):
    contrib = get_object_or_404(Contribution, uuid=tx_uuid,
                                type=amo.CONTRIB_PURCHASE)
    refund_contribs = contrib.get_refund_contribs()
    refund_contrib = refund_contribs[0] if refund_contribs.exists() else None

    if refund_contrib:
        messages.error(request, _('A refund has already been processed.'))
        return redirect(reverse('lookup.transaction_summary', args=[tx_uuid]))

    form = TransactionRefundForm(request.POST)
    if not form.is_valid():
        messages.error(request, str(form.errors))
        return redirect(reverse('lookup.transaction_summary', args=[tx_uuid]))

    try:
        res = client.api.bango.refund.post({'uuid': contrib.transaction_id})
    except (HttpClientError, HttpServerError):
        # Either doing something not supposed to or Solitude had an issue.
        log.exception('Refund error: %s' % tx_uuid)
        messages.error(
            request,
            _('You cannot make a refund request for this transaction.'))
        return redirect(reverse('lookup.transaction_summary', args=[tx_uuid]))

    if res['status'] in [PENDING, COMPLETED]:
        # Create refund Contribution by cloning the payment Contribution.
        refund_contrib = Contribution.objects.get(id=contrib.id)
        refund_contrib.id = None
        refund_contrib.save()
        refund_contrib.update(
            type=amo.CONTRIB_REFUND, related=contrib,
            uuid=hashlib.md5(str(uuid.uuid4())).hexdigest(),
            amount=-refund_contrib.amount if refund_contrib.amount else None,
            transaction_id=client.get(res['transaction'])['uuid'])

    if res['status'] == PENDING:
        # Create pending Refund.
        refund_contrib.enqueue_refund(
            amo.REFUND_PENDING, request.amo_user,
            refund_reason=form.cleaned_data['refund_reason'])
        log.info('Refund pending: %s' % tx_uuid)
        email_buyer_refund_pending(contrib)
        messages.success(
            request, _('Refund for this transaction now pending.'))
    elif res['status'] == COMPLETED:
        # Create approved Refund.
        refund_contrib.enqueue_refund(
            amo.REFUND_APPROVED, request.amo_user,
            refund_reason=form.cleaned_data['refund_reason'])
        log.info('Refund approved: %s' % tx_uuid)
        email_buyer_refund_approved(contrib)
        messages.success(
            request, _('Refund for this transaction successfully approved.'))
    elif res['status'] == FAILED:
        # Bango no like.
        log.error('Refund failed: %s' % tx_uuid)
        messages.error(
            request, _('Refund request for this transaction failed.'))

    return redirect(reverse('lookup.transaction_summary', args=[tx_uuid]))


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

    purchases, refunds = _app_purchases_and_refunds(app)
    return jingo.render(request, 'lookup/app_summary.html',
                        {'abuse_reports': app.abuse_reports.count(),
                         'app': app,
                         'authors': authors,
                         'downloads': _app_downloads(app),
                         'purchases': purchases,
                         'payment_methods': _app_pay_methods(app),
                         'refunds': refunds,
                         'price': price})


@login_required
@permission_required('AccountLookup', 'View')
def user_purchases(request, user_id):
    """Shows the purchase page for another user."""
    user = get_object_or_404(UserProfile, pk=user_id)
    is_admin = acl.action_allowed(request, 'Users', 'Edit')
    products, contributions, listing = purchase_list(request, user, None)
    return jingo.render(request, 'lookup/user_purchases.html',
                        {'pager': products,
                         'account': user,
                         'is_admin': is_admin,
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
    is_admin = acl.action_allowed(request, 'Users', 'Edit')

    collections = Collection.objects.filter(author=user_id)
    user_items = ActivityLog.objects.for_user(user).exclude(
        action__in=amo.LOG_HIDE_DEVELOPER)
    admin_items = ActivityLog.objects.for_user(user).filter(
        action__in=amo.LOG_HIDE_DEVELOPER)
    amo.log(amo.LOG.ADMIN_VIEWED_LOG, request.amo_user, user=user)
    return jingo.render(request, 'lookup/user_activity.html',
                        {'pager': products,
                         'account': user,
                         'is_admin': is_admin,
                         'listing_filter': listing,
                         'collections': collections,
                         'contributions': contributions,
                         'single': bool(None),
                         'user_items': user_items,
                         'admin_items': admin_items,
                         'show_link': False})


def _expand_query(q, fields):
    query = {}
    rules = [
        ('text', {'query': q, 'boost': 4, 'type': 'phrase'}),
        ('text', {'query': q, 'boost': 3, 'analyzer': 'standard'}),
        ('fuzzy', {'value': q, 'boost': 2, 'prefix_length': 4}),
        ('startswith', {'value': q, 'boost': 1.5}),
    ]
    for k, v in rules:
        for field in fields:
            query['%s__%s' % (field, k)] = v
    return query


@login_required
@permission_required('AccountLookup', 'View')
@json_view
def user_search(request):
    results = []
    q = request.GET.get('q', u'').lower().strip()
    fields = ('username', 'display_name', 'email')
    if q.isnumeric():
        # id is added implictly by the ES filter. Add it explicitly:
        fields = ['id'] + list(fields)
        qs = UserProfile.objects.filter(pk=q).values(*fields)
    else:
        qs = (UserProfile.search().query(or_=_expand_query(q, fields))
                                  .values_dict(*fields))[:20]
    for user in qs:
        user['url'] = reverse('lookup.user_summary', args=[user['id']])
        user['name'] = user['username']
        results.append(user)
    return {'results': results}


@login_required
@permission_required('Transaction', 'View')
def transaction_search(request):
    tx_form = TransactionSearchForm(request.GET)
    if tx_form.is_valid():
        return redirect(reverse('lookup.transaction_summary',
                                args=[tx_form.cleaned_data['q']]))
    else:
        return jingo.render(request, 'lookup/home.html', {'tx_form': tx_form})


@login_required
@permission_required('AccountLookup', 'View')
@json_view
def app_search(request):
    results = []
    q = request.GET.get('q', u'').lower().strip()
    addon_type = request.GET.get('type', amo.ADDON_WEBAPP)
    fields = ('name', 'app_slug')
    non_es_fields = ['id', 'name__localized_string'] + list(fields)
    if q.isnumeric():
        qs = (Addon.objects.filter(type=addon_type, pk=q)
                           .values(*non_es_fields))
    else:
        # Try to load by GUID:
        qs = (Addon.objects.filter(type=addon_type, guid=q)
                           .values(*non_es_fields))
        if not qs.count():
            qs = (S(Addon).query(type=addon_type,
                                 or_=_expand_query(q, fields))
                          .values_dict(*fields)[:20])
    for app in qs:
        app['url'] = reverse('lookup.app_summary', args=[app['id']])
        # ES returns a list of localized names but database queries do not.
        if type(app['name']) != list:
            app['name'] = [app['name__localized_string']]
        for name in app['name']:
            dd = app.copy()
            dd['name'] = name
            results.append(dd)
    return {'results': results}


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
        stats['last_7_days'] = app.weekly_downloads
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


def _app_purchases_and_refunds(addon):
    purchases = {}
    now = datetime.now()
    base_qs = (Contribution.objects.values('currency')
                           .annotate(total=Count('id'),
                                     amount=Sum('amount'))
                           .filter(addon=addon)
                           .exclude(type__in=[amo.CONTRIB_REFUND,
                                              amo.CONTRIB_CHARGEBACK,
                                              amo.CONTRIB_PENDING,
                                              amo.CONTRIB_INAPP_PENDING]))
    for typ, start_date in (('last_24_hours', now - timedelta(hours=24)),
                            ('last_7_days', now - timedelta(days=7)),
                            ('alltime', None),):
        qs = base_qs.all()
        if start_date:
            qs = qs.filter(created__gte=start_date)
        sums = list(qs)
        purchases[typ] = {'total': sum(s['total'] for s in sums),
                          'amounts': [numbers.format_currency(s['amount'],
                                                              s['currency'])
                                      for s in sums]}
    refunds = {}
    rejected_q = Q(status=amo.REFUND_DECLINED) | Q(status=amo.REFUND_FAILED)
    qs = Refund.objects.filter(contribution__addon=addon)

    refunds['requested'] = qs.exclude(rejected_q).count()
    percent = 0.0
    total = purchases['alltime']['total']
    if total:
        percent = (refunds['requested'] / float(total)) * 100.0
    refunds['percent_of_purchases'] = '%.1f%%' % percent
    refunds['auto-approved'] = (qs.filter(status=amo.REFUND_APPROVED_INSTANT)
                                .count())
    refunds['approved'] = qs.filter(status=amo.REFUND_APPROVED).count()
    refunds['rejected'] = qs.filter(rejected_q).count()

    return purchases, refunds


def _app_pay_methods(addon):
    """
    Get a breakdown of payment methods used in commerce for this add-on.

    Currently we only support one payment method, PayPal, so consider this
    a placeholder for when we support more, which requires a model change.
    """
    qs = Contribution.objects.filter(addon=addon,
                                     type__in=(amo.CONTRIB_PURCHASE,
                                               amo.CONTRIB_INAPP))
    # TODO(Kumar) adjust this when our db model supports multiple
    # payment methods.
    other = qs.filter(paykey=None).count()
    paypal = qs.exclude(paykey=None).count()
    amt_per_method = [(other, _('Other')),
                      (paypal, 'PayPal')]
    total = float(sum(amt for amt, typ in amt_per_method))
    summary = []
    for amt, typ in amt_per_method:
        if amt == 0:
            continue
        percent = '%.1f%%' % (amt / total * 100.0)
        # L10n: first argument is a percentage, second is a payment method.
        summary.append(_(u'{0} of purchases via {1}').format(percent, typ))
    return summary
