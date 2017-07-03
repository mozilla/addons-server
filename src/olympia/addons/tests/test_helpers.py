from mock import Mock
from pyquery import PyQuery

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.templatetags.jinja_helpers import (
    statusflags, flag, contribution)
from olympia.addons.models import Addon


class TestHelpers(TestCase):
    fixtures = ['base/addon_3615', 'base/users',
                'addons/featured', 'base/collections',
                'base/featured', 'bandwagon/featured_collections']

    def test_statusflags(self):
        ctx = {'APP': amo.FIREFOX, 'LANG': 'en-US'}

        # unreviewed
        a = Addon(status=amo.STATUS_NOMINATED)
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
        a = Addon(status=amo.STATUS_NOMINATED)
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
