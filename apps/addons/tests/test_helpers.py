from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery

import amo
import amo.tests
from addons.helpers import (statusflags, flag, contribution, performance_note,
                            mobile_persona_preview, mobile_persona_confirm)
from addons.models import Addon


class TestHelpers(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users',
                'addons/featured', 'base/collections',
                'base/featured', 'bandwagon/featured_collections']

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

    def test_contribution_box(self):
        a = Addon.objects.get(pk=7661)
        a.suggested_amount = '12'

        settings = Mock()
        settings.MAX_CONTRIBUTION = 5

        request = Mock()
        request.GET = {'src': 'direct'}

        c = {'LANG': 'en-us', 'APP': amo.FIREFOX, 'settings': settings,
             'request': request}

        s = contribution(c, a)
        doc = PyQuery(s)
        # make sure input boxes are rendered correctly (bug 555867)
        assert doc('input[name=onetime-amount]').length == 1

    def test_src_retained(self):
        a = Addon.objects.get(pk=7661)
        a.suggested_amount = '12'

        settings = Mock()
        settings.MAX_CONTRIBUTION = 5

        request = Mock()

        c = {'LANG': 'en-us', 'APP': amo.FIREFOX, 'settings': settings,
             'request': request}

        s = contribution(c, a, contribution_src='browse')
        doc = PyQuery(s)
        eq_(doc('input[name=source]').attr('value'), 'browse')

    def test_mobile_persona_preview(self):
        ctx = {'APP': amo.FIREFOX, 'LANG': 'en-US'}
        persona = Addon.objects.get(pk=15679).persona
        s = mobile_persona_preview(ctx, persona)
        doc = PyQuery(s)
        bt = doc('.persona-preview div[data-browsertheme]')
        assert bt
        assert persona.preview_url in bt.attr('style')
        eq_(persona.json_data, bt.attr('data-browsertheme'))
        assert bt.find('p')

    def _test_mobile_persona_ctx(self):
        request = Mock()
        request.APP = amo.FIREFOX
        request.GET = {}
        request.user.is_authenticated.return_value = False
        request.amo_user.mobile_addons = []
        return {'APP': amo.FIREFOX, 'LANG': 'en-US', 'request': request}

    def test_mobile_persona_confirm_large(self):
        persona = Addon.objects.get(id=15679).persona
        s = mobile_persona_confirm(self._test_mobile_persona_ctx(), persona)
        doc = PyQuery(s)
        assert not doc('.persona-slider')
        assert doc('.preview')
        assert doc('.confirm-buttons .add')
        assert doc('.confirm-buttons .cancel')
        assert not doc('.more')

    def test_mobile_persona_confirm_small(self):
        persona = Addon.objects.get(id=15679).persona
        s = mobile_persona_confirm(self._test_mobile_persona_ctx(), persona,
                                   size='small')
        doc = PyQuery(s)
        assert doc('.persona-slider')
        assert not doc('.persona-slider .preview')
        assert doc('.confirm-buttons .add')
        assert doc('.confirm-buttons .cancel')
        more = doc('.more')
        assert more
        eq_(more.attr('href'), persona.addon.get_url_path())


class TestPerformanceNote(amo.tests.TestCase):
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
