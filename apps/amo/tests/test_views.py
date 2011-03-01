from datetime import datetime
import urllib

from django import http, test
from django.conf import settings
from django.core.cache import cache, parse_backend_uri

import commonware.log
from lxml import etree
from mock import patch, Mock
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

from addons.models import Addon
from amo.urlresolvers import reverse
from amo.pyquery_wrapper import PyQuery
from stats.models import SubscriptionEvent, Contribution

URL_ENCODED = 'application/x-www-form-urlencoded'


def test_login_link():
    "Test that the login link encodes parameters correctly."
    r = test.Client().get('/?your=mom', follow=True)
    doc = pq(r.content)
    assert doc('.context a')[1].attrib['href'].endswith(
            '?to=%2Fen-US%2Ffirefox%2F%3Fyour%3Dmom'), ("Got %s" %
            doc('.context a')[1].attrib['href'])

    r = test.Client().get('/en-US/firefox/search/?q=%B8+%EB%B2%88%EC%97%A')
    doc = pq(r.content)
    link = doc('.context a')[1].attrib['href']
    assert link.endswith('?to=%2Fen-US%2Ffirefox%2Fsearch%2F%3Fq%3D%25EF'
            '%25BF%25BD%2B%25EB%25B2%2588%25EF%25BF%25BDA'), "Got %s" % link


class Client(test.Client):
    """Test client that uses form-urlencoded (like browsers)."""

    def post(self, url, data={}, **kw):
        if hasattr(data, 'items'):
            data = urllib.urlencode(data)
            kw['content_type'] = URL_ENCODED
        return super(Client, self).post(url, data, **kw)


def test_404_no_app():
    """Make sure a 404 without an app doesn't turn into a 500."""
    # That could happen if helpers or templates expect APP to be defined.
    url = reverse('amo.monitor')
    response = test.Client().get(url + 'nonsense')
    eq_(response.status_code, 404)


def test_404_app_links():
    response = test.Client().get('/en-US/thunderbird/xxxxxxx')
    eq_(response.status_code, 404)
    links = pq(response.content)('[role=main] ul li a:not([href^=mailto])')
    eq_(len(links), 4)
    for link in links:
        href = link.attrib['href']
        assert href.startswith('/en-US/thunderbird'), href


class TestStuff(test_utils.TestCase):
    fixtures = ('base/users', 'base/global-stats', 'base/configs',)

    def test_hide_stats_link(self):
        r = self.client.get('/', follow=True)
        doc = pq(r.content)
        assert doc('.stats')
        assert not doc('.stats a')

    def test_data_anonymous(self):
        def check(expected):
            response = self.client.get('/', follow=True)
            anon = PyQuery(response.content)('body').attr('data-anonymous')
            eq_(anon, expected)

        check('true')
        self.client.login(username='admin@mozilla.com', password='password')
        check('false')

    def test_my_account_menu(self):
        def get_homepage():
            response = self.client.get('/', follow=True)
            return PyQuery(response.content)

        # Logged out
        doc = get_homepage()
        eq_(doc('#aux-nav .account').length, 0)
        eq_(doc('#aux-nav .tools').length, 0)

        # Logged in, regular user = one tools link
        self.client.login(username='regular@mozilla.com', password='password')
        doc = get_homepage()
        eq_(doc('#aux-nav .account').length, 1)
        eq_(doc('#aux-nav ul.tools').length, 0)
        eq_(doc('#aux-nav p.tools').length, 1)

        # Logged in, admin = multiple links
        self.client.login(username='admin@mozilla.com', password='password')
        doc = get_homepage()
        eq_(doc('#aux-nav .account').length, 1)
        eq_(doc('#aux-nav ul.tools').length, 1)
        eq_(doc('#aux-nav p.tools').length, 0)

    def test_heading(self):
        def title_eq(url, alt, text):
            response = self.client.get(url, follow=True)
            doc = PyQuery(response.content)
            eq_(alt, doc('.site-title img').attr('alt'))
            eq_(text, doc('.site-title').text())

        title_eq('/firefox', 'Firefox', 'Add-ons')
        title_eq('/thunderbird', 'Thunderbird', 'Add-ons')
        title_eq('/mobile', 'Firefox', 'Mobile Add-ons')

    def test_xenophobia(self):
        r = self.client.get(reverse('home'), follow=True)
        self.assertNotContains(r, 'show only English (US) add-ons')

    def test_login_link(self):
        r = self.client.get(reverse('home'), follow=True)
        doc = PyQuery(r.content)
        next = urllib.urlencode({'to': '/en-US/firefox/'})
        eq_('/en-US/firefox/users/login?%s' % next,
            doc('#aux-nav p a')[1].attrib['href'])


class TestPaypal(test_utils.TestCase):

    def setUp(self):
        self.url = reverse('amo.paypal')
        self.item = 1234567890
        self.client = Client()
        settings.PAYPAL_USE_EMBEDDED = True

    def urlopener(self, status):
        m = Mock()
        m.readline.return_value = status
        return m

    @patch('amo.views.urllib2.urlopen')
    def test_not_verified(self, urlopen):
        urlopen.return_value = self.urlopener('xxx')
        response = self.client.post(self.url, {'foo': 'bar'})
        assert isinstance(response, http.HttpResponseForbidden)

    @patch('amo.views.urllib2.urlopen')
    def test_no_payment_status(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url)
        eq_(response.status_code, 200)

    @patch('amo.views.urllib2.urlopen')
    def test_subscription_event(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url, {'txn_type': 'subscr_xxx'})
        eq_(response.status_code, 200)
        eq_(SubscriptionEvent.objects.count(), 1)

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        assert isinstance(response, http.HttpResponseNotAllowed)

    @patch('amo.views.urllib2.urlopen')
    def test_mysterious_contribution(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')

        key = "%s%s:%s" % (settings.CACHE_PREFIX, 'contrib', self.item)

        data = {'txn_id': 100,
                'payer_email': 'jbalogh@wherever.com',
                'receiver_email': 'clouserw@gmail.com',
                'mc_gross': '99.99',
                'item_number': self.item,
                'payment_status': 'Completed'}
        response = self.client.post(self.url, data)
        assert isinstance(response, http.HttpResponseServerError)
        eq_(cache.get(key), 1)

        cache.set(key, 10, 1209600)
        response = self.client.post(self.url, data)
        assert isinstance(response, http.HttpResponse)
        eq_(cache.get(key), None)

    @patch('amo.views.urllib2.urlopen')
    def test_query_string_order(self, urlopen):
        urlopen.return_value = self.urlopener('HEY MISTER')
        query = 'x=x&a=a&y=y'
        response = self.client.post(self.url, data=query,
                                    content_type=URL_ENCODED)
        eq_(response.status_code, 403)
        _, path, _ = urlopen.call_args[0]
        eq_(path, 'cmd=_notify-validate&%s' % query)

    @patch('amo.views.urllib2.urlopen')
    def test_any_exception(self, urlopen):
        urlopen.side_effect = Exception()
        response = self.client.post(self.url)
        eq_(response.status_code, 500)
        eq_(response.content, 'Unknown error.')


class TestEmbeddedPaymentsPaypal(test_utils.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.url = reverse('amo.paypal')
        self.addon = Addon.objects.get(pk=3615)

    def urlopener(self, status):
        m = Mock()
        m.readline.return_value = status
        return m

    @patch('amo.views.urllib2.urlopen')
    def test_success(self, urlopen):
        uuid = 'e76059abcf747f5b4e838bf47822e6b2'
        Contribution.objects.create(uuid=uuid, addon=self.addon)
        data = {'tracking_id': uuid, 'payment_status': 'Completed'}
        urlopen.return_value = self.urlopener('VERIFIED')

        response = self.client.post(self.url, data)
        eq_(response.content, 'Success!')

    @patch('amo.views.urllib2.urlopen')
    def test_wrong_uuid(self, urlopen):
        uuid = 'e76059abcf747f5b4e838bf47822e6b2'
        Contribution.objects.create(uuid=uuid, addon=self.addon)
        data = {'tracking_id': 'sdf', 'payment_status': 'Completed'}
        urlopen.return_value = self.urlopener('VERIFIED')

        response = self.client.post(self.url, data)
        eq_(response.content, 'Contribution not found')


def test_jsi18n_caching():
    """The jsi18n catalog should be cached for a long time."""
    # Get the url from a real page so it includes the build id.
    client = test.Client()
    doc = pq(client.get('/', follow=True).content)
    js_url = reverse('jsi18n')
    url_with_build = doc('script[src^="%s"]' % js_url).attr('src')

    response = client.get(url_with_build, follow=True)
    fmt = '%a, %d %b %Y %H:%M:%S GMT'
    expires = datetime.strptime(response['Expires'], fmt)
    assert (expires - datetime.now()).days >= 365


def test_dictionaries_link():
    doc = pq(test.Client().get('/', follow=True).content)
    link = doc('#categoriesdropdown a[href*="language-tools"]')
    eq_(link.text(), 'Dictionaries & Language Packs')


def test_remote_addr():
    """Make sure we're setting REMOTE_ADDR from X_FORWARDED_FOR."""
    client = test.Client()
    # Send X-Forwarded-For as it shows up in a wsgi request.
    client.get('/en-US/firefox/', follow=True, HTTP_X_FORWARDED_FOR='oh yeah')
    eq_(commonware.log.get_remote_addr(), 'oh yeah')


def test_opensearch():
    client = test.Client()
    page = client.get('/en-US/firefox/opensearch.xml')

    wanted = ('Content-Type', 'text/xml')
    eq_(page._headers['content-type'], wanted)

    doc = etree.fromstring(page.content)
    e = doc.find("{http://a9.com/-/spec/opensearch/1.1/}ShortName")
    eq_(e.text, "Firefox Add-ons")


def test_language_selector():
    doc = pq(test.Client().get('/en-US/firefox/').content)
    eq_(doc('form.languages option[selected]').attr('value'), 'en-us')
