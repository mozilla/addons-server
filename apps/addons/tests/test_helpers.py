from django import test

import jingo
from nose.tools import eq_
from pyquery import PyQuery

import amo
from addons.helpers import statusflags, flag, support_addon, contribution
from addons.models import Addon


class TestHelpers(test.TestCase):
    fixtures = ['base/addons.json', 'addons/featured.json']

    def setUp(self):
        jingo.load_helpers()

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

    def test_support_addon(self):
        a = Addon(id=12)
        eq_(support_addon(a), '')

        # TODO(jbalogh): check the url when using reverse
        a.wants_contributions = a.paypal_id = True
        eq_(PyQuery(support_addon(a))('a').text(), 'Support this add-on')

        a.suggested_amount = '12'
        doc = PyQuery(support_addon(a))
        eq_(doc('.contribute').text(),
            'Support this add-on: Contribute $12.00')

    def test_contribution_box(self):
        a = Addon.objects.get(pk=1003)
        a.suggested_amount = '12'
        doc = PyQuery(contribution(a))
        # make sure input boxes are rendered correctly (bug 555867)
        assert doc('input[name=onetime-amount]').length == 1
        assert doc('input[name=monthly-amount]').length == 1
