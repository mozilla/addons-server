from django.conf import settings

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse
from mkt.ecosystem.models import MdnCache


class TestLanding(amo.tests.TestCase):

    def setUp(self):
        self.url = reverse('ecosystem.landing')

    def test_legacy_redirect(self):
        self.skip_if_disabled(settings.REGION_STORES)
        r = self.client.get('/ecosystem/')
        self.assert3xx(r, '/developers/', 301)

    @mock.patch.object(settings, 'MIDDLEWARE_CLASSES',
        settings.MIDDLEWARE_CLASSES + type(settings.MIDDLEWARE_CLASSES)([
            'amo.middleware.NoConsumerMiddleware',
            'amo.middleware.LoginRequiredMiddleware'
        ])
    )
    def test_legacy_redirect_with_walled_garden(self):
        r = self.client.get('/ecosystem/')
        self.assert3xx(r, '/developers/', 301)

    def test_tutorials_default(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/landing.html')


class TestDevHub(amo.tests.TestCase):

    def test_partners(self):
        r = self.client.get(reverse('ecosystem.partners'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/partners.html')

    def test_support(self):
        r = self.client.get(reverse('ecosystem.support'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/support.html')


class TestMdnDocumentation(amo.tests.TestCase):
    fixtures = ['ecosystem/mdncache-item']

    def setUp(self):
        self.url = reverse('ecosystem.documentation')

    def test_mdn_content_default(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/documentation.html')

    def test_mdn_content_design(self):
        r = self.client.get(reverse('ecosystem.documentation',
                            args=['principles']))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/documentation.html')

    def test_mdn_content_explicit(self):
        r = self.client.get(self.url + 'old')
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/documentation.html')

    def test_mdn_content_unknown(self):
        r = self.client.get(self.url + 'pizza')
        eq_(r.status_code, 404)
        self.assertTemplateUsed(r, 'site/404.html')

    def test_mdn_content_content(self):
        a = MdnCache.objects.filter(name='html5', locale='en-US')[0]
        a.content = '<strong>pizza</strong>'
        a.save()

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('strong').text(), 'pizza')
