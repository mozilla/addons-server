from django import test

from nose.tools import eq_

import amo
from addons.helpers import statusflags, flag
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

    def test_flags(self):
        ctx = {'APP': amo.FIREFOX, 'LANG': 'en-US'}

        # experimental
        a = Addon(status=amo.STATUS_SANDBOX)
        eq_(flag(ctx, a), '<h5 class="flag">Experimental</h5>')

        # recommended
        featured = Addon.objects.get(pk=1003)
        eq_(flag(ctx, featured), '<h5 class="flag">Recommended</h5>')

        # category featured
        featured = Addon.objects.get(pk=1001)
        eq_(flag(ctx, featured), '<h5 class="flag">Recommended</h5>')
