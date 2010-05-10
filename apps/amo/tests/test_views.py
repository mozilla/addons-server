from datetime import datetime
import urllib

from django import http, test
from django.conf import settings
from django.core.cache import cache, parse_backend_uri

from mock import patch, Mock
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

from amo.urlresolvers import reverse
from amo.pyquery_wrapper import PyQuery
from stats.models import SubscriptionEvent


URL_ENCODED = 'application/x-www-form-urlencoded'


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
    fixtures = ['base/fixtures', 'base/global-stats', 'base/configs']

    def test_data_anonymous(self):
        def check(expected):
            response = self.client.get('/', follow=True)
            anon = PyQuery(response.content)('body').attr('data-anonymous')
            eq_(anon, expected)

        check('true')
        self.client.login(username='admin@mozilla.com', password='password')
        check('false')

    def test_my_account_menu(self):
        def check(expected):
            response = self.client.get('/', follow=True)
            account = PyQuery(response.content)('ul.account')
            tools = PyQuery(response.content)('ul.tools')
            eq_(account.size(), expected)
            eq_(tools.size(), expected)

        check(0)
        self.client.login(username='admin@mozilla.com', password='password')
        check(1)

    def test_heading(self):
        def title_eq(url, expected):
            response = self.client.get(url, follow=True)
            actual = PyQuery(response.content)('#title').text()
            eq_(expected, actual)

        title_eq('/firefox', 'Add-ons for Firefox')
        title_eq('/thunderbird', 'Add-ons for Thunderbird')
        title_eq('/mobile', 'Mobile Add-ons for Firefox')

    def test_xenophobia(self):
        def box_is_checked(locale='en-US', cookie_val=None):
            if cookie_val is not None:
                self.client.cookies['locale-only'] = cookie_val
            elif 'locale-only' in self.client.cookies:
                del self.client.cookies['locale-only']

            response = self.client.get("/%s/firefox/" % locale)
            doc = PyQuery(response.content)
            return doc("#locale-only").attr('checked')

        def cookie_box(xeno, locale='en-US'):
            if 'locale-only' in self.client.cookies:
                del self.client.cookies['locale-only']

            xeno = 'locale-only=1&' if xeno else ''

            response = self.client.get("/%s/firefox/?%slang=%s&next=/" % (
                    locale, xeno, locale), follow=True)
            box = PyQuery(response.content)('#locale-only').attr('checked')
            cookie = self.client.cookies.get("locale-only")

            if cookie:
                cookie = int(cookie.value)
            return (box, cookie)

        assert box_is_checked(cookie_val=1), ("True cookie does not show "
                "checked box for /en-US/.")
        assert box_is_checked('ja', cookie_val=1), ("True cookie does not "
                "show checked box for /ja/.")
        assert not box_is_checked(cookie_val=0), ("False cookie does show "
                "checked box for /en-US/.")
        assert not box_is_checked('ja', cookie_val=0), ("False cookie does "
                "show checked box for /ja/.")
        assert not box_is_checked(), "Empty cookie does is checked for en-US."
        assert box_is_checked('ja'), "Empty cookie is not checked for ja."

        eq_(('checked', 1), cookie_box(True))
        eq_((None, 0), cookie_box(False))
        eq_(('checked', 1), cookie_box(True, 'ja'))
        eq_((None, 0), cookie_box(False, 'ja'))

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

    def urlopener(self, status):
        m = Mock()
        m.readline.return_value = status
        return m

    @patch('amo.views.urllib2.urlopen')
    def test_not_verified(self, urlopen):
        urlopen.return_value = self.urlopener('xxx')
        response = self.client.post(self.url)
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
        scheme, servers, _ = parse_backend_uri(settings.CACHE_BACKEND)
        if 'dummy' in scheme:
            raise SkipTest()
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
        response = self.client.post(self.url, {})
        eq_(response.status_code, 500)
        eq_(response.content, 'Unknown error.')


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
    # This just failed because you dropped the remora url.
    link = doc('#categoriesdropdown a[href$="type:3"]')
    eq_(link.text(), 'Dictionaries & Language Packs')
