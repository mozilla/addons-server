from amo.install import addons
from amo.tests import TestCase
from amo.urlresolvers import reverse
from amo.utils import urlparams


class InstallTests(TestCase):

    def test_generic(self):
        url = reverse('api.install')
        r = self.client.get(urlparams(url,
                                      addon_id='1',
                                      addon_name='Status Watch'))
        assert 'prompted to install Status Watch' in r.content

    def test_byid(self):
        url = reverse('api.install')
        r = self.client.get(urlparams(url, addon_id='318202'))
        assert 'prompted to install Twitter Address Search Bar' in r.content

    def test_byname(self):
        url = reverse('api.install')
        r = self.client.get(urlparams(url, addon_key='prism'))
        assert 'prompted to install Prism for Firefox' in r.content

    def test_redirect(self):
        url = reverse('api.install')
        r = self.client.get(urlparams(url, addon_id=424))
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r['Location'], addons[424]['link'])

    def test_bad_id(self):
        url = reverse('api.install')
        r = self.client.get(urlparams(url, addon_id='eleventy-one'))
        self.assertEqual(r.status_code, 404)

    def test_bad_key(self):
        url = reverse('api.install')
        r = self.client.get(urlparams(url, addon_key='unicorns'))
        self.assertEqual(r.status_code, 404)
