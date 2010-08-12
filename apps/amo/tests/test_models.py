from test_utils import TestCase

from nose.tools import eq_

from amo.models import manual_order
from addons.models import Addon


class ManualOrderTest(TestCase):
    fixtures = ('base/apps', 'base/addon_3615', 'base/addon_5299_gcal',
                'base/addon_40')

    def test_ordering(self):
        """Given a specific set of primary keys, assure that we return addons
        in that order."""

        semi_arbitrary_order = [40, 5299, 3615]
        addons = manual_order(Addon.objects.all(), semi_arbitrary_order)
        eq_(semi_arbitrary_order, [addon.id for addon in addons])
