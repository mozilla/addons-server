from django.conf import settings

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
        self.assertRedirects(r, '/developers/', 301)

    def test_tutorials_default(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/landing.html')


class TestDevHub(amo.tests.TestCase):

    def test_developers(self):
        r = self.client.get(reverse('ecosystem.developers'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/developers.html')

    def test_building_blocks(self):
        r = self.client.get(reverse('ecosystem.building_blocks'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r,
            'ecosystem/mdn_documentation/building_blocks.html')

    def test_partners(self):
        r = self.client.get(reverse('ecosystem.partners'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/partners.html')

    def test_support(self):
        r = self.client.get(reverse('ecosystem.support'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/support.html')


class TestDeveloperBuilding(amo.tests.TestCase):

    def test_xtag_list(self):
        r = self.client.get(reverse('ecosystem.building_xtag', args=['list']))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/design/xtag_list.html')


class TestMdnDocumentation(amo.tests.TestCase):
    fixtures = ['ecosystem/mdncache-item']

    def setUp(self):
        self.url = reverse('ecosystem.documentation')

    def test_mdn_content_default(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/mdn_documentation/index.html')

    def test_mdn_content_design(self):
        r = self.client.get(reverse('ecosystem.documentation',
                            args=['design_principles']))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/mdn_documentation/design.html')

    def test_mdn_content_explicit(self):
        r = self.client.get(self.url + 'old')
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/mdn_documentation/index.html')

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
