from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.templatetags.jinja_helpers import flag, statusflags
from olympia.amo.tests import TestCase


class TestHelpers(TestCase):
    fixtures = [
        'base/addon_3615',
        'base/users',
        'addons/featured',
        'base/collections',
        'base/featured',
        'bandwagon/featured_collections',
    ]

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
