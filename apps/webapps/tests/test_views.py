from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests

from webapps.models import Webapp


class WebappTest(amo.tests.TestCase):

    def setUp(self):
        self.webapp = Webapp.objects.create(name='woo', app_slug='yeah')
        self.url = self.webapp.get_url_path()


class TestLayout(WebappTest):

    def test_header(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('h1.site-title').text(), 'Apps')
        eq_(doc('#site-nav.app-nav').length, 1)
        eq_(doc('#search-q').attr('placeholder'), 'search for apps')
        eq_(doc('#id_cat').attr('value'), 'apps')

    def test_footer(self):
        response = self.client.get(self.url)
        eq_(pq(response.content)('#social-footer').length, 0)


class TestDetail(WebappTest):

    def test_title(self):
        response = self.client.get(self.url)
        eq_(pq(response.content)('title').text(), 'woo :: Apps Marketplace')

    def test_more_url(self):
        response = self.client.get(self.url)
        eq_(pq(response.content)('#more-webpage').attr('data-more-url'),
            self.webapp.get_url_path(more=True))

    def test_headings(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('#addon h1').text(), 'woo')
        eq_(doc('h2:first').text(), 'About this App')

    def test_reviews(self):
        response = self.client.get_ajax(self.webapp.get_url_path(more=True))
        eq_(pq(response.content)('#reviews h3').remove('a').text(),
            'This app has not yet been reviewed.')


class TestMobileDetail(amo.tests.MobileTest, WebappTest):

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'addons/mobile/details.html')

    def test_no_release_notes(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('.versions').length, 0)
