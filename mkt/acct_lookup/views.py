from django.db import connection
from django.shortcuts import get_object_or_404

import jingo

import amo
from amo.decorators import login_required, permission_required, json_view
from amo.urlresolvers import reverse
from market.models import Refund
from users.models import UserProfile


@login_required
@permission_required('AccountLookup', 'View')
def home(request):
    return jingo.render(request, 'acct_lookup/home.html', {})


@login_required
@permission_required('AccountLookup', 'View')
def summary(request, user_id):
    user = get_object_or_404(UserProfile, pk=user_id)
    app_summary = _app_summary(user.pk)
    # All refunds that this user has requested (probably as a consumer).
    req = Refund.objects.filter(contribution__user=user)
    # All instantly-approved refunds that this user has requested.
    appr = req.filter(status=amo.REFUND_APPROVED_INSTANT)
    refund_summary = {'approved': appr.count(),
                      'requested': req.count()}
    user_addons = user.addons.all().order_by('-created')
    return jingo.render(request, 'acct_lookup/summary.html',
                        {'account': user,
                         'app_summary': app_summary,
                         'refund_summary': refund_summary,
                         'user_addons': user_addons})


@login_required
@permission_required('AccountLookup', 'View')
@json_view
def search(request):
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
        user['url'] = reverse('acct_lookup.summary', args=[user['id']])
        results.append(user)
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
