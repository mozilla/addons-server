from django import http
from django.db.models import Q

import jingo
from tower import ugettext_lazy as _lazy

from addons.views import BaseFilter
import amo
from amo.decorators import login_required
from amo.utils import paginate
from stats.models import Contribution
from translations.query import order_by_translation
from mkt.webapps.models import Webapp


class PurchasesFilter(BaseFilter):
    opts = (('purchased', _lazy(u'Purchase Date')),
            ('price', _lazy(u'Price')),
            ('name', _lazy(u'Name')))

    def filter(self, field):
        qs = self.base_queryset
        if field == 'purchased':
            return (qs.filter(Q(addonpurchase__user=self.request.amo_user) |
                              Q(addonpurchase__isnull=True))
                    .order_by('-addonpurchase__created', 'id'))
        elif field == 'price':
            return qs.order_by('addonpremium__price__price', 'id')
        elif field == 'name':
            return order_by_translation(qs, 'name')


@login_required
def purchases(request, product_id=None, template=None):
    """A list of purchases that a user has made through the Marketplace."""
    cs = (Contribution.objects
          .filter(user=request.amo_user,
                  type__in=[amo.CONTRIB_PURCHASE, amo.CONTRIB_REFUND,
                            amo.CONTRIB_CHARGEBACK])
          .order_by('created'))
    if product_id:
        cs = cs.filter(addon=product_id)

    ids = list(cs.values_list('addon_id', flat=True))
    # If you are asking for a receipt for just one item, show only that.
    # Otherwise, we'll show all apps that have a contribution or are free.
    if not product_id:
        ids += list(request.amo_user.installed_set
                    .exclude(addon__in=ids)
                    .values_list('addon_id', flat=True))

    contributions = {}
    for c in cs:
        contributions.setdefault(c.addon_id, []).append(c)

    ids = list(set(ids))
    listing = PurchasesFilter(request, Webapp.objects.filter(id__in=ids),
                              key='sort', default='purchased')

    if product_id and not listing.qs:
        # User has requested a receipt for an app he ain't got.
        raise http.Http404

    products = paginate(request, listing.qs, count=len(ids))
    return jingo.render(request, 'account/purchases.html',
                        {'pager': products,
                         'listing_filter': listing,
                         'contributions': contributions,
                         'single': bool(product_id)})
