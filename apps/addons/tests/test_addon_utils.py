from nose.tools import eq_

import amo.tests
from addons.models import Addon
from addons.utils import ReverseNameLookup
from addons import cron


class TestReverseNameLookup(amo.tests.TestCase):
    fixtures = ('base/addon_3615',)

    def setUp(self):
        super(TestReverseNameLookup, self).setUp()
        cron.build_reverse_name_lookup()
        self.addon = Addon.objects.get()

    def test_delete_addon(self):
        eq_(ReverseNameLookup().get('Delicious Bookmarks'), 3615)
        self.addon.delete('farewell my sweet amo, it was a good run')
        eq_(ReverseNameLookup().get('Delicious Bookmarks'), None)

    def test_update_addon(self):
        eq_(ReverseNameLookup().get('Delicious Bookmarks'), 3615)
        self.addon.name = 'boo'
        self.addon.save()
        eq_(ReverseNameLookup().get('Delicious Bookmarks'), None)
        eq_(ReverseNameLookup().get('boo'), 3615)

    def test_get_strip(self):
        eq_(ReverseNameLookup().get('Delicious Bookmarks   '), 3615)

    def test_get_case(self):
        eq_(ReverseNameLookup().get('delicious bookmarks'), 3615)

    def test_addon_and_app_namespaces(self):
        eq_(ReverseNameLookup(webapp=False).get('Delicious Bookmarks'), 3615)
        eq_(ReverseNameLookup(webapp=True).get('Delicious Bookmarks'), None)

        # Note: The factory creates the app which calls the ReverseNameLookup
        # in a post_save signal, so no need to call it explicitly here.
        app = amo.tests.addon_factory(type=amo.ADDON_WEBAPP)
        self.assertTrue(app.is_webapp())

        eq_(ReverseNameLookup(webapp=False).get(app.name), None)
        eq_(ReverseNameLookup(webapp=True).get(app.name), app.id)

        # Show we can also create an app with the same name as an addon
        name = 'Delicious Bookmarks'
        app = amo.tests.addon_factory(name=name, type=amo.ADDON_WEBAPP)
        self.assertTrue(app.is_webapp())
        eq_(ReverseNameLookup(webapp=False).get(name), 3615)
        eq_(ReverseNameLookup(webapp=True).get(name), app.id)


