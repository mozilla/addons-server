import json

from django.conf import settings
from django.utils.html import strip_tags

import mock
from nose.plugins.skip import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
from tower import strip_whitespace

import amo
import amo.tests
from addons.models import AddonCategory, Category
from users.models import UserProfile
from mkt.webapps.models import Webapp


def get_clean(selection):
    return strip_whitespace(str(selection))


class TestDetail(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Webapp.objects.get(id=337141)
        self.url = self.webapp.get_detail_url()

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_categories(self):
        cat = Category.objects.create(name='Lifestyle', slug='lifestyle',
                                      type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=self.webapp, category=cat)
        r = self.client.get(self.url)
        links = pq(r.content)('.categories a')
        eq_(links.length, 1)
        eq_(links.attr('href'), cat.get_url_path())
        eq_(links.text(), cat.name)


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestInstall(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.addon = amo.tests.app_factory(manifest_url='http://cbc.ca/man')
        self.url = self.addon.get_detail_url('record')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        assert self.client.login(username=self.user.email, password='password')

    def test_not_record_addon(self):
        self.addon.update(type=amo.ADDON_EXTENSION)
        self.client.post(self.url)
        eq_(self.user.installed_set.count(), 0)

    def test_record_logged_out(self):
        self.client.logout()
        res = self.client.post(self.url)
        eq_(res.status_code, 302)

    def test_record_install(self):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)

    def test_record_multiple_installs(self):
        self.client.post(self.url)
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)

    @mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                       amo.tests.AMOPaths.sample_key())
    def test_record_receipt(self):
        res = self.client.post(self.url)
        content = json.loads(res.content)
        assert content.get('receipt'), content


class TestPrivacy(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Webapp.objects.get(id=337141)
        self.url = self.webapp.get_detail_url('privacy')

    def test_app_statuses(self):
        eq_(self.webapp.status, amo.STATUS_PUBLIC)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

        # Incomplete or pending apps should 404.
        for status in (amo.STATUS_NULL, amo.STATUS_PENDING):
            self.webapp.update(status=status)
            r = self.client.get(self.url)
            eq_(r.status_code, 404)

        # Public-yet-disabled apps should 404.
        self.webapp.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        eq_(self.client.get(self.url).status_code, 404)

    def test_policy(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.policy-statement').text(),
            strip_tags(get_clean(self.webapp.privacy_policy)))

    def test_policy_html(self):
        self.webapp.privacy_policy = """
            <strong> what the koberger..</strong>
            <ul>
                <li>papparapara</li>
                <li>todotodotodo</li>
            </ul>
            <ol>
                <a href="irc://irc.mozilla.org/firefox">firefox</a>

                Introduce yourself to the community, if you like!
                This text will appear publicly on your user info page.
                <li>papparapara2</li>
                <li>todotodotodo2</li>
            </ol>
            """
        self.webapp.save()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('.policy-statement')
        eq_(get_clean(doc('strong')), '<strong> what the koberger..</strong>')
        eq_(get_clean(doc('ul')),
            '<ul><li>papparapara</li> <li>todotodotodo</li> </ul>')
        eq_(get_clean(doc('ol a').text()), 'firefox')
        eq_(get_clean(doc('ol li:first')), '<li>papparapara2</li>')


class TestReportAbuse(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Webapp.objects.get(id=337141)
        self.url = self.webapp.get_detail_url('abuse')

    def test_get(self):
        # TODO: Uncomment Report Abuse gets ported to mkt.
        raise SkipTest
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_submit(self):
        # TODO: Uncomment Report Abuse gets ported to mkt.
        raise SkipTest
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.post(self.url, {'text': 'this is some rauncy ish'})
        self.assertRedirects(r, self.webapp.get_detail_url())
