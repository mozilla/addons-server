from django.conf import settings

from nose.tools import eq_
import test_utils
from pyquery import PyQuery as pq

import amo
from amo.urlresolvers import reverse
from addons.models import Addon


class TestHomepage(test_utils.TestCase):
    fixtures = ['base/addons', 'base/global-stats', 'base/featured']

    def setUp(self):
        super(TestHomepage, self).setUp()
        self.base_url = reverse('home')

    def test_default_feature(self):
        response = self.client.get(self.base_url, follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['filter'].field, 'featured')

    def test_featured(self):
        response = self.client.get(self.base_url + '?browse=featured',
                                   follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['filter'].field, 'featured')
        featured = response.context['addon_sets']['featured']
        ids = [a.id for a in featured]
        eq_(set(ids), set([2464, 7661]))
        for addon in featured:
            assert addon.is_featured(amo.FIREFOX, settings.LANGUAGE_CODE)

    def _test_invalid_feature(self):
        response = self.client.get(self.base_url + '?browse=xxx')
        self.assertRedirects(response, '/en-US/firefox/', status_code=301)

    def test_no_experimental(self):
        response = self.client.get(self.base_url)
        for addons in response.context['addon_sets'].values():
            for addon in addons:
                assert addon.status != amo.STATUS_SANDBOX

    def test_filter_opts(self):
        response = self.client.get(self.base_url)
        opts = [k[0] for k in response.context['filter'].opts]
        eq_(opts, 'featured popular new updated'.split())


class TestDetailPage(test_utils.TestCase):
    fixtures = ['base/addons', 'addons/listed']

    def test_anonymous_user(self):
        """Does the page work for an anonymous user?"""
        response = self.client.get(reverse('addons.detail', args=[3615]),
                                   follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['addon'].id, 3615)

    def test_inactive_addon(self):
        """Do not display disabled add-ons."""
        myaddon = Addon.objects.get(id=3615)
        myaddon.inactive = True
        myaddon.save()
        response = self.client.get(reverse('addons.detail', args=[myaddon.id]),
                                   follow=True)
        eq_(response.status_code, 404)

    def test_listed(self):
        """Show certain things for hosted but not listed add-ons."""
        hosted_resp = self.client.get(reverse('addons.detail', args=[3615]),
                                      follow=True)
        hosted = pq(hosted_resp.content)

        listed_resp = self.client.get(reverse('addons.detail', args=[3723]),
                                      follow=True)
        listed = pq(listed_resp.content)

        eq_(hosted('#releasenotes').length, 1)
        eq_(listed('#releasenotes').length, 0)
