from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse
from mkt.ecosystem.models import MdnCache


class TutorialsHome(amo.tests.TestCase):
    fixtures = ['ecosystem/mdncache-item']

    def setUp(self):
        self.url = reverse('ecosystem.tutorial')

    def test_tutorials_default(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/tutorial.html')

    def test_tutorials_expicit(self):
        r = self.client.get(self.url + 'old')
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/tutorial.html')

    def test_tutorials_unknown(self):
        r = self.client.get(self.url + 'pizza')
        eq_(r.status_code, 404)
        self.assertTemplateUsed(r, 'site/404.html')

    def test_display_of_content(self):
        a = MdnCache.objects.filter(name='apps', locale='en')[0]
        a.content = '<strong>pizza</strong>'
        a.save()

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#content strong').text(), 'pizza')

    def test_display_of_toc(self):
        a = MdnCache.objects.filter(name='apps', locale='en')[0]
        a.toc = '<strong>pizza</strong>'
        a.save()

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#nav strong').text(), 'pizza')


class LandingTests(amo.tests.TestCase):

    def setUp(self):
        self.url = reverse('ecosystem.landing')

    def test_tutorials_default(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/landing.html')
