from test_utils import TestCase

from nose.tools import eq_

from amo.models import manual_order
from amo import models as context
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


def test_skip_cache():
    eq_(getattr(context._locals, 'skip_cache', False), False)
    with context.skip_cache():
        eq_(context._locals.skip_cache, True)
        with context.skip_cache():
            eq_(context._locals.skip_cache, True)
        eq_(context._locals.skip_cache, True)
    eq_(context._locals.skip_cache, False)


def test_use_master():
    local = context.multidb.pinning._locals
    eq_(getattr(local, 'pinned', False), False)
    with context.use_master():
        eq_(local.pinned, True)
        with context.use_master():
            eq_(local.pinned, True)
        eq_(local.pinned, True)
    eq_(local.pinned, False)
