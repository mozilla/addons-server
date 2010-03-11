from django.conf import settings

from nose.tools import eq_
import test_utils

import amo
from amo.urlresolvers import reverse


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
    fixtures = ['base/addons']

    def test_anonymous_user(self):
        """Does the page work for an anonymous user?"""
        response = self.client.get(reverse('addons.detail', args=[3615]),
                                   follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['addon'].id, 3615)
