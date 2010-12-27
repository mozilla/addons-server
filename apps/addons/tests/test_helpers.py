import test_utils
from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery

import amo
from addons.helpers import (statusflags, flag, support_addon, contribution,
                            performance_note)
from addons.models import Addon


class TestHelpers(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_4664_twitterbar',
                'addons/featured.json']

    def test_statusflags(self):
        ctx = {'APP': amo.FIREFOX, 'LANG': 'en-US'}

        # unreviewed
        a = Addon(status=amo.STATUS_UNREVIEWED)
        eq_(statusflags(ctx, a), 'unreviewed')

        # recommended
        featured = Addon.objects.get(pk=1003)
        eq_(statusflags(ctx, featured), 'featuredaddon')

        # category featured
        featured = Addon.objects.get(pk=1001)
        eq_(statusflags(ctx, featured), 'featuredaddon')

    def test_flags(self):
        ctx = {'APP': amo.FIREFOX, 'LANG': 'en-US'}

        # unreviewed
        a = Addon(status=amo.STATUS_UNREVIEWED)
        eq_(flag(ctx, a), '<h5 class="flag">Not Reviewed</h5>')

        # recommended
        featured = Addon.objects.get(pk=1003)
        eq_(flag(ctx, featured), '<h5 class="flag">Featured</h5>')

        # category featured
        featured = Addon.objects.get(pk=1001)
        eq_(flag(ctx, featured), '<h5 class="flag">Featured</h5>')

    def test_support_addon(self):
        a = Addon(id=12, type=1)
        eq_(support_addon(a), '')

        a.wants_contributions = a.paypal_id = True
        a.status = amo.STATUS_PUBLIC
        eq_(PyQuery(support_addon(a))('a').text(), 'Support this add-on')

        a.suggested_amount = '12'
        doc = PyQuery(support_addon(a))
        eq_(doc('.contribute').text(),
            'Support this add-on: Contribute $12.00')

    def test_contribution_box(self):
        a = Addon.objects.get(pk=4664)
        a.suggested_amount = '12'

        settings = Mock()
        settings.MAX_CONTRIBUTION = 5

        c = {'LANG': 'en-us', 'APP': amo.FIREFOX, 'settings': settings}

        s = contribution(c, a)
        doc = PyQuery(s)
        # make sure input boxes are rendered correctly (bug 555867)
        assert doc('input[name=onetime-amount]').length == 1
        assert doc('input[name=monthly-amount]').length == 1


class TestPerformanceNote(test_utils.TestCase):
    listing = '<div class="performance-note">'
    not_listing = '<div class="notification performance-note">'

    def setUp(self):
        request_mock = Mock()
        request_mock.APP = amo.FIREFOX
        self.ctx = {'request': request_mock, 'amo': amo}

    def test_show_listing(self):
        r = performance_note(self.ctx, 30, listing=True)
        assert self.listing in r, r

    def test_show_not_listing(self):
        r = performance_note(self.ctx, 30)
        assert self.not_listing in r, r

    def test_only_fx(self):
        self.ctx['request'].APP = amo.THUNDERBIRD
        r = performance_note(self.ctx, 30)
        eq_(r.strip(), '')
