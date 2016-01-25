from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery

import amo
import amo.tests
from addons.helpers import (statusflags, flag, contribution,
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
        assert statusflags(ctx, a) == 'unreviewed'

        # featured
        featured = Addon.objects.get(pk=1003)
        assert statusflags(ctx, featured) == 'featuredaddon'

        # category featured
        featured = Addon.objects.get(pk=1001)
        assert statusflags(ctx, featured) == 'featuredaddon'

    def test_flags(self):
        ctx = {'APP': amo.FIREFOX, 'LANG': 'en-US'}

        # unreviewed
        a = Addon(status=amo.STATUS_UNREVIEWED)
        assert flag(ctx, a) == '<h5 class="flag">Not Reviewed</h5>'

        # featured
        featured = Addon.objects.get(pk=1003)
        assert flag(ctx, featured) == '<h5 class="flag">Featured</h5>'

        # category featured
        featured = Addon.objects.get(pk=1001)
        assert flag(ctx, featured) == '<h5 class="flag">Featured</h5>'

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
        assert doc('input[name=source]').attr('value') == 'browse'

    def test_mobile_persona_preview(self):
        ctx = {'APP': amo.FIREFOX, 'LANG': 'en-US'}
        persona = Addon.objects.get(pk=15679).persona
        s = mobile_persona_preview(ctx, persona)
        doc = PyQuery(s)
        bt = doc('.persona-preview div[data-browsertheme]')
        assert bt
        assert persona.preview_url in bt.attr('style')
        assert persona.json_data == bt.attr('data-browsertheme')
        assert bt.find('p')

    def _test_mobile_persona_ctx(self):
        request = Mock()
        request.APP = amo.FIREFOX
        request.GET = {}
        request.user.is_authenticated.return_value = False
        request.user.mobile_addons = []
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
        assert more.attr('href') == persona.addon.get_url_path()
