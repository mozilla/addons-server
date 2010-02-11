from django import test

from nose.tools import eq_

import amo
from addons.helpers import statusflags
from addons.models import Addon


class TestHelpers(test.TestCase):
    fixtures = ['base/addons.json', 'addons/featured.json']

    def test_statusflags(self):
        ctx = {'APP': amo.FIREFOX, 'LANG': 'en-US'}

        # experimental
        a = Addon(status=amo.STATUS_SANDBOX)
        eq_(statusflags(ctx, a), 'experimental')

        # recommended
        featured = Addon.objects.get(pk=1003)
        eq_(statusflags(ctx, featured), 'recommended')

        # category featured
        featured = Addon.objects.get(pk=1001)
        eq_(statusflags(ctx, featured), 'recommended')
