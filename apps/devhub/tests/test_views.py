from django.utils import encoding, translation

import jingo
from mock import Mock
from nose.tools import eq_, assert_not_equal
from pyquery import PyQuery as pq
import test_utils

import amo
import amo.test_utils
from amo.tests.test_helpers import render
from amo.urlresolvers import reverse
from addons.models import Addon, AddonUser
from users.models import UserProfile


class HubTest(amo.test_utils.ExtraSetup, test_utils.TestCase):
    fixtures = ('browse/nameless-addon', 'base/users')

    def setUp(self):
        translation.activate('en-US')
        self.url = reverse('devhub.index')
        self.login_as_developer()
        eq_(self.client.get(self.url).status_code, 200)
        self.user_profile = UserProfile.objects.get(id=999)

    def login_as_developer(self):
        self.client.login(username='regular@mozilla.com', password='password')

    def clone_addon(self, num_copies, addon_id=57132):
        for i in xrange(num_copies):
            addon = Addon.objects.get(id=addon_id)
            addon.id = addon.guid = None
            addon.save()
            AddonUser.objects.create(user=self.user_profile, addon=addon)

            new_addon = Addon.objects.get(id=addon.id)
            new_addon.name = 'addon-%s' % i
            new_addon.save()
        return addon.id


class TestNav(HubTest):

    def test_navbar(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#navbar').length, 1)

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert_not_equal(doc('#navbar ul li.top a').eq(0).text(),
            'My Add-ons',
            'My Add-ons menu should not be visible if user has no add-ons.')

    def test_my_addons(self):
        """Check that the correct items are listed for the My Add-ons menu."""
        # Assign this add-on to the current user profile.
        addon = Addon.objects.get(id=57132)
        AddonUser.objects.create(user=self.user_profile, addon=addon)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # Check the anchor for the 'My Add-ons' menu item.
        eq_(doc('#navbar ul li.top a').eq(0).text(), 'My Add-ons')

        # Check the anchor for the single add-on.
        edit_url = reverse('devhub.addons.edit', args=[57132])
        eq_(doc('#navbar ul li.top li a').eq(0).attr('href'), edit_url)

        # Create 6 add-ons.
        self.clone_addon(6)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # There should be 8 items in this menu.
        eq_(doc('#navbar ul li.top:first-child ul li').length, 8)

        # This should be the 8th anchor, after the 7 addons.
        eq_(doc('#navbar ul li.top:first-child li a').eq(7).text(),
            'Submit a New Add-on')

        addon = Addon.objects.get(id=57132)
        addon.id = addon.guid = None
        addon.save()
        AddonUser.objects.create(user=self.user_profile, addon=addon)

        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#navbar ul li.top:first-child li a').eq(7).text(),
            'more add-ons...')


class TestDashboard(HubTest):

    def setUp(self):
        super(TestDashboard, self).setUp()
        self.url = reverse('devhub.addons')
        eq_(self.client.get(self.url).status_code, 200)

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('.item item').length, 0)

    def test_addons_items(self):
        """Check that the correct info. is displayed for each add-on:
        namely, that add-ons are paginated at 10 items per page, and that
        when there is more than one page, the 'Sort by' header and pagination
        footer appear.

        """
        # Create 10 add-ons.
        self.clone_addon(10)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # Check the titles of the new add-ons.
        eq_(doc('.item h4 a').text().split(),
            ['addon-%s' % i for i in xrange(10)])

        # There should be 10 add-on listing items.
        eq_(len(doc('.item .item-info')), 10)

        # There should be neither a listing header nor a pagination footer.
        eq_(doc('#addon-list-options').length, 0)
        eq_(doc('.listing-footer .pagination').length, 0)

        # Create 5 add-ons.
        self.clone_addon(5)

        r = self.client.get(self.url + '?page=2')
        doc = pq(r.content)

        # There should be 10 add-on listing items.
        eq_(len(doc('.item .item-info')), 5)

        # There should be a listing header and pagination footer.
        eq_(doc('#addon-list-options').length, 1)
        eq_(doc('.listing-footer .pagination').length, 1)
