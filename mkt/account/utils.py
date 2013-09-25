from django import http

from tower import ugettext_lazy as _lazy

from addons.views import BaseFilter
import amo
from amo.models import manual_order
from amo.utils import paginate
from mkt.constants import apps
from mkt.webapps.models import Webapp
from stats.models import Contribution
from translations.query import order_by_translation


class PurchasesFilter(BaseFilter):
    opts = (('purchased', _lazy(u'Purchase Date')),
            ('price', _lazy(u'Price')),
            ('name', _lazy(u'Name')))

    def __init__(self, *args, **kwargs):
        self.ids = kwargs.pop('ids')
        self.uids = kwargs.pop('uids')
        super(PurchasesFilter, self).__init__(*args, **kwargs)

    def filter(self, field):
        qs = self.base_queryset
        if field == 'purchased':
            # Id's are in created order, so let's invert them for this query.
            # According to my testing we don't actually need to dedupe this.
            ids = list(reversed(self.ids[0])) + self.ids[1]
            return manual_order(qs.filter(id__in=ids), ids)
        elif field == 'price':
            return (qs.filter(id__in=self.uids)
                      .order_by('addonpremium__price__price', 'id'))
        elif field == 'name':
            return order_by_translation(qs.filter(id__in=self.uids), 'name')


def purchase_list(request, user, product_id):
    cs = (Contribution.objects
          .filter(user=user,
                  type__in=[amo.CONTRIB_PURCHASE, amo.CONTRIB_REFUND,
                            amo.CONTRIB_CHARGEBACK])
          .order_by('created'))
    if product_id:
        cs = cs.filter(addon__guid=product_id)

    ids = list(cs.values_list('addon_id', flat=True))
    product_ids = []
    # If you are asking for a receipt for just one item, show only that.
    # Otherwise, we'll show all apps that have a contribution or are free.
    if not product_id:
        product_ids = list(user.installed_set
                           .filter(install_type__in=
                               [apps.INSTALL_TYPE_USER,
                                apps.INSTALL_TYPE_DEVELOPER])
                           .exclude(addon__in=ids)
                           .values_list('addon_id', flat=True))

    contributions = {}
    for c in cs:
        contributions.setdefault(c.addon_id, []).append(c)

    unique_ids = set(ids + product_ids)
    listing = PurchasesFilter(request, Webapp.objects.all(),
                              key='sort', default='purchased',
                              ids=[ids, product_ids],
                              uids=unique_ids)

    if product_id and not listing.qs.exists():
        # User has requested a receipt for an app he ain't got.
        raise http.Http404

    products = paginate(request, listing.qs, count=len(unique_ids))
    return products, contributions, listing
