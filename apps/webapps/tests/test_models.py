import test_utils
from nose.tools import eq_

import amo
from addons.models import Addon, BlacklistedSlug
from webapps.models import Webapp


class TestWebapp(test_utils.TestCase):

    def test_webapp_type(self):
        webapp = Webapp()
        webapp.save()
        eq_(webapp.type, amo.ADDON_WEBAPP)

    def test_app_slugs_separate_from_addon_slugs(self):
        Addon.objects.create(type=1, slug='slug')
        webapp = Webapp(app_slug='slug')
        webapp.save()
        eq_(webapp.slug, 'app-%s' % webapp.id)
        eq_(webapp.app_slug, 'slug')

    def test_app_slug_collision(self):
        Webapp(app_slug='slug').save()
        w2 = Webapp(app_slug='slug')
        w2.save()
        eq_(w2.app_slug, 'slug-1')

        w3 = Webapp(app_slug='slug')
        w3.save()
        eq_(w3.app_slug, 'slug-2')

    def test_app_slug_blocklist(self):
        BlacklistedSlug.objects.create(name='slug')
        w = Webapp(app_slug='slug')
        w.save()
        eq_(w.app_slug, 'slug~')

    def test_get_url_path(self):
        webapp = Webapp(app_slug='woo')
        eq_(webapp.get_url_path(), '/en-US/apps/woo/')

    def test_get_url_path_more(self):
        webapp = Webapp(app_slug='woo')
        eq_(webapp.get_url_path(more=True), '/en-US/apps/woo/more')

    def test_get_origin(self):
        webapp = Webapp(manifest_url='http://www.xx.com:4000/randompath/manifest.webapp')
        eq_(webapp.origin, 'http://www.xx.com:4000')
