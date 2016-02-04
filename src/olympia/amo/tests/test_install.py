from olympia.amo.install import addons
from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams


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

    def test_byidname(self):
        url = reverse('api.install')
        r = self.client.get(urlparams(url, addon_id='prism'))
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

    def test_xss(self):
        url = reverse('api.install')
        url = '{url}?{path}'.format(
            url=url,
            path='addon_id=252539%3C/script%3E%3CBODY%20ONLOAD=alert%28%27XSS'
                 '%27%29%3E&addon_name=F1%20by%20Mozilla%20Labs'
                 '&src=external-f1home')
        r = self.client.get(url)
        assert '<BODY' not in r.content
