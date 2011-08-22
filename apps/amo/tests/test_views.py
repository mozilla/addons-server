from datetime import datetime
import urllib

from django import http, test
from django.conf import settings
from django.core.cache import cache
from django.core import mail

import commonware.log
from lxml import etree
from mock import patch, Mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from access import acl
from addons.models import Addon, AddonUser
from amo.urlresolvers import reverse
from amo.pyquery_wrapper import PyQuery
from stats.models import SubscriptionEvent, Contribution
from users.models import UserProfile

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


class TestImpala(amo.tests.TestCase):
    fixtures = ('base/users', 'base/global-stats', 'base/configs',
                'base/addon_3615')

    def test_tools_loggedout(self):
        r = self.client.get(reverse('i_home'), follow=True)
        nav = pq(r.content)('#aux-nav')
        eq_(nav.find('.tools').length, 0)

    def test_tools_regular_user(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('i_home'), follow=True)
        nav = pq(r.content)('#aux-nav')

        request = r.context['request']

        eq_(request.amo_user.is_developer, False)
        eq_(nav.find('.tools a').length, 1)
        eq_(nav.find('.tools a').eq(0).text(), "Developer Hub")
        eq_(nav.find('.tools a').eq(0).attr('href'), reverse('devhub.index'))

    def test_tools_developer(self):
        # Make them a developer
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = Addon.objects.all()[0]
        AddonUser.objects.create(user=user, addon=addon)

        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('i_home'), follow=True)
        nav = pq(r.content)('#aux-nav')

        request = r.context['request']

        eq_(request.amo_user.is_developer, True)

        eq_(nav.find('.tools').length, 1)
        eq_(nav.find('.tools li').length, 3)
        eq_(nav.find('.tools > a').length, 1)
        eq_(nav.find('.tools > a').text(), "Developer")

        item = nav.find('.tools ul li a').eq(0)
        eq_(item.text(), "Manage My Add-ons")
        eq_(item.attr('href'), reverse('devhub.addons'))

        item = nav.find('.tools ul li a').eq(1)
        eq_(item.text(), "Submit a New Add-on")
        eq_(item.attr('href'), reverse('devhub.submit.1'))

        item = nav.find('.tools ul li a').eq(2)
        eq_(item.text(), "Developer Hub")
        eq_(item.attr('href'), reverse('devhub.index'))

    def test_tools_developer_and_editor(self):
        # Make them a developer
        user = UserProfile.objects.get(email='editor@mozilla.com')
        addon = Addon.objects.all()[0]
        AddonUser.objects.create(user=user, addon=addon)

        self.client.login(username='editor@mozilla.com', password='password')
        r = self.client.get(reverse('i_home'), follow=True)
        nav = pq(r.content)('#aux-nav')

        request = r.context['request']

        eq_(request.amo_user.is_developer, True)
        eq_(acl.action_allowed(request, 'Editors', '%'), True)

        eq_(nav.find('li.tools').length, 1)
        eq_(nav.find('li.tools li').length, 4)
        eq_(nav.find('li.tools > a').length, 1)
        eq_(nav.find('li.tools > a').text(), "Tools")

        item = nav.find('.tools ul li a').eq(0)
        eq_(item.text(), "Manage My Add-ons")
        eq_(item.attr('href'), reverse('devhub.addons'))

        item = nav.find('.tools ul li a').eq(1)
        eq_(item.text(), "Submit a New Add-on")
        eq_(item.attr('href'), reverse('devhub.submit.1'))

        item = nav.find('.tools ul li a').eq(2)
        eq_(item.text(), "Developer Hub")
        eq_(item.attr('href'), reverse('devhub.index'))

        item = nav.find('.tools ul li a').eq(3)
        eq_(item.text(), "Editor Tools")
        eq_(item.attr('href'), reverse('editors.home'))

    def test_tools_editor(self):
        self.client.login(username='editor@mozilla.com', password='password')
        r = self.client.get(reverse('i_home'), follow=True)
        nav = pq(r.content)('#aux-nav')

        request = r.context['request']

        eq_(request.amo_user.is_developer, False)
        eq_(acl.action_allowed(request, 'Editors', '%'), True)

        eq_(nav.find('li.tools').length, 1)
        eq_(nav.find('li.tools li').length, 2)
        eq_(nav.find('li.tools > a').length, 1)
        eq_(nav.find('li.tools > a').text(), "Tools")

        item = nav.find('.tools ul li a').eq(0)
        eq_(item.text(), "Developer Hub")
        eq_(item.attr('href'), reverse('devhub.index'))

        item = nav.find('.tools ul li a').eq(1)
        eq_(item.text(), "Editor Tools")
        eq_(item.attr('href'), reverse('editors.home'))


class TestStuff(amo.tests.TestCase):
    fixtures = ('base/users', 'base/global-stats', 'base/configs',
                'base/addon_3615')

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
        eq_(doc('#aux-nav .account.anonymous').length, 1)
        eq_(doc('#aux-nav .tools').length, 0)

        # Logged in, regular user = one tools link
        self.client.login(username='regular@mozilla.com', password='password')
        doc = get_homepage()
        eq_(doc('#aux-nav .account').length, 1)
        eq_(doc('#aux-nav li.tools.nomenu').length, 1)

        # Logged in, admin = multiple links
        self.client.login(username='admin@mozilla.com', password='password')
        doc = get_homepage()
        eq_(doc('#aux-nav .account').length, 1)
        eq_(doc('#aux-nav li.tools').length, 1)

    def test_heading(self):
        def title_eq(url, alt, text):
            response = self.client.get(url, follow=True)
            doc = PyQuery(response.content)
            eq_(alt, doc('.site-title img').attr('alt'))
            eq_(text, doc('.site-title').text())

        title_eq('/firefox', 'Firefox', 'Add-ons')
        title_eq('/thunderbird', 'Thunderbird', 'Add-ons')
        title_eq('/mobile', 'Mobile', 'Mobile Add-ons')

    def test_tools_loggedout(self):
        r = self.client.get(reverse('home'), follow=True)
        nav = pq(r.content)('#aux-nav')
        eq_(nav.find('.tools').length, 0)

    def test_tools_regular_user(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('home'), follow=True)
        nav = pq(r.content)('#aux-nav')

        request = r.context['request']

        eq_(request.amo_user.is_developer, False)
        eq_(nav.find('.tools a').length, 1)
        eq_(nav.find('.tools a').eq(0).text(), "Developer Hub")
        eq_(nav.find('.tools a').eq(0).attr('href'), reverse('devhub.index'))

    def test_tools_developer(self):
        # Make them a developer
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = Addon.objects.all()[0]
        AddonUser.objects.create(user=user, addon=addon)

        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('home'), follow=True)
        nav = pq(r.content)('#aux-nav')

        request = r.context['request']

        eq_(request.amo_user.is_developer, True)

        eq_(nav.find('li.tools').length, 1)
        eq_(nav.find('li.tools > a').text(), "Developer")
        eq_(nav.find('li.tools li').length, 3)

        item = nav.find('li.tools ul li a').eq(0)
        eq_(item.text(), "Manage My Add-ons")
        eq_(item.attr('href'), reverse('devhub.addons'))

        item = nav.find('li.tools ul li a').eq(1)
        eq_(item.text(), "Submit a New Add-on")
        eq_(item.attr('href'), reverse('devhub.submit.1'))

        item = nav.find('li.tools ul li a').eq(2)
        eq_(item.text(), "Developer Hub")
        eq_(item.attr('href'), reverse('devhub.index'))

    def test_tools_developer_and_editor(self):
        # Make them a developer
        user = UserProfile.objects.get(email='editor@mozilla.com')
        addon = Addon.objects.all()[0]
        AddonUser.objects.create(user=user, addon=addon)

        self.client.login(username='editor@mozilla.com', password='password')
        r = self.client.get(reverse('home'), follow=True)
        nav = pq(r.content)('#aux-nav')

        request = r.context['request']

        eq_(request.amo_user.is_developer, True)
        eq_(acl.action_allowed(request, 'Editors', '%'), True)

        eq_(nav.find('li.tools').length, 1)
        eq_(nav.find('li.tools li').length, 4)

        item = nav.find('li.tools ul li a').eq(0)
        eq_(item.text(), "Manage My Add-ons")
        eq_(item.attr('href'), reverse('devhub.addons'))

        item = nav.find('li.tools ul li a').eq(1)
        eq_(item.text(), "Submit a New Add-on")
        eq_(item.attr('href'), reverse('devhub.submit.1'))

        item = nav.find('li.tools ul li a').eq(2)
        eq_(item.text(), "Developer Hub")
        eq_(item.attr('href'), reverse('devhub.index'))

        item = nav.find('li.tools ul li a').eq(3)
        eq_(item.text(), "Editor Tools")
        eq_(item.attr('href'), reverse('editors.home'))

    def test_tools_editor(self):
        self.client.login(username='editor@mozilla.com', password='password')
        r = self.client.get(reverse('home'), follow=True)
        nav = pq(r.content)('#aux-nav')

        request = r.context['request']

        eq_(request.amo_user.is_developer, False)
        eq_(acl.action_allowed(request, 'Editors', '%'), True)

        eq_(nav.find('li.tools').length, 1)
        eq_(nav.find('li.tools > a').text(), 'Tools')

        item = nav.find('li.tools ul li a').eq(0)
        eq_(item.text(), "Developer Hub")
        eq_(item.attr('href'), reverse('devhub.index'))

        item = nav.find('li.tools ul li a').eq(1)
        eq_(item.text(), "Editor Tools")
        eq_(item.attr('href'), reverse('editors.home'))

    def test_xenophobia(self):
        r = self.client.get(reverse('home'), follow=True)
        self.assertNotContains(r, 'show only English (US) add-ons')

    def test_login_link(self):
        r = self.client.get(reverse('home'), follow=True)
        doc = PyQuery(r.content)
        next = urllib.urlencode({'to': '/en-US/firefox/'})
        eq_('/en-US/firefox/users/login?%s' % next,
            doc('.account.anonymous a')[1].attrib['href'])


class TestPaypal(amo.tests.TestCase):

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

    @patch('amo.views.urllib2.urlopen')
    def test_mail(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        add = Addon.objects.create(enable_thankyou=True,
                                   support_email='a@a.com',
                                   type=amo.ADDON_EXTENSION)
        Contribution.objects.create(addon_id=add.pk,
                                    uuid='123')
        response = self.client.post(self.url, {u'action_type': u'PAY',
                                               u'sender_email': u'a@a.com',
                                               u'status': u'COMPLETED',
                                               u'tracking_id': u'123'})
        eq_(response.status_code, 200)
        eq_(len(mail.outbox), 1)

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


class TestEmbeddedPaymentsPaypal(amo.tests.TestCase):
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


class TestOtherStuff(amo.tests.TestCase):
    # Tests that don't need fixtures but do need redis mocked.

    def test_language_selector(self):
        doc = pq(test.Client().get('/en-US/firefox/').content)
        eq_(doc('form.languages option[selected]').attr('value'), 'en-us')

    @patch.object(settings, 'KNOWN_PROXIES', ['127.0.0.1'])
    def test_remote_addr(self):
        """Make sure we're setting REMOTE_ADDR from X_FORWARDED_FOR."""
        client = test.Client()
        # Send X-Forwarded-For as it shows up in a wsgi request.
        client.get('/en-US/firefox/', follow=True,
                   HTTP_X_FORWARDED_FOR='1.1.1.1')
        eq_(commonware.log.get_remote_addr(), '1.1.1.1')

    def test_jsi18n_caching(self):
        # The jsi18n catalog should be cached for a long time.
        # Get the url from a real page so it includes the build id.
        client = test.Client()
        doc = pq(client.get('/', follow=True).content)
        js_url = reverse('jsi18n')
        url_with_build = doc('script[src^="%s"]' % js_url).attr('src')

        response = client.get(url_with_build, follow=True)
        fmt = '%a, %d %b %Y %H:%M:%S GMT'
        expires = datetime.strptime(response['Expires'], fmt)
        assert (expires - datetime.now()).days >= 365

    def test_dictionaries_link(self):
        doc = pq(test.Client().get('/', follow=True).content)
        link = doc('#site-nav #more a[href*="language-tools"]')
        eq_(link.text(), 'Dictionaries & Language Packs')

    def test_opensearch(self):
        client = test.Client()
        page = client.get('/en-US/firefox/opensearch.xml')

        wanted = ('Content-Type', 'text/xml')
        eq_(page._headers['content-type'], wanted)

        doc = etree.fromstring(page.content)
        e = doc.find("{http://a9.com/-/spec/opensearch/1.1/}ShortName")
        eq_(e.text, "Firefox Add-ons")

    def test_login_link(self):
        # Test that the login link encodes parameters correctly.
        r = test.Client().get('/?your=mom', follow=True)
        doc = pq(r.content)
        assert doc('.account.anonymous a')[1].attrib['href'].endswith(
                '?to=%2Fen-US%2Ffirefox%2F%3Fyour%3Dmom'), ("Got %s" %
                doc('.account.anonymous a')[1].attrib['href'])

        r = test.Client().get('/ar/firefox/?q=%B8+%EB%B2%88%EC%97%A')
        doc = pq(r.content)
        link = doc('.account.anonymous a')[1].attrib['href']
        assert link.endswith('?to=%2Far%2Ffirefox%2F%3Fq%3D%25EF%25BF%25BD%2B'
                             '%25EB%25B2%2588%25EF%25BF%25BDA'), link
    test_login_link.py27unicode = True
