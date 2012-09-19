from datetime import date

import json

from django.conf import settings
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.utils import urlparams
from amo.urlresolvers import reverse

from addons.models import Addon, AddonCategory, Category
from users.models import UserProfile

from mkt.webapps.models import Webapp
from mkt.zadmin.models import FeaturedApp, FeaturedAppRegion


class TestEcosystem(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.url = reverse('mkt.zadmin.ecosystem')

    def test_staff_access(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'AdminTools:View')
        self.client.login(username='regular@mozilla.com', password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)


class TestGenerateError(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        metlog = settings.METLOG
        METLOG_CONF = {
            'logger': 'zamboni',
            'plugins': {'cef': ('metlog_cef.cef_plugin:config_plugin', 
                                {'override': True})},
            'sender': {'class': 'metlog.senders.DebugCaptureSender'},
        }
        from metlog.config import client_from_dict_config
        self.metlog = client_from_dict_config(METLOG_CONF, metlog)
        self.metlog.sender.msgs.clear()

    def test_metlog_statsd(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'metlog_statsd'})

        eq_(len(self.metlog.sender.msgs), 1)
        msg = json.loads(self.metlog.sender.msgs[0])

        eq_(msg['severity'], 6)
        eq_(msg['logger'], 'zamboni')
        eq_(msg['payload'], '1')
        eq_(msg['type'], 'counter')
        eq_(msg['fields']['rate'], 1.0)
        eq_(msg['fields']['name'], 'z.zadmin')

    def test_metlog_json(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'metlog_json'})

        eq_(len(self.metlog.sender.msgs), 1)
        msg = json.loads(self.metlog.sender.msgs[0])

        eq_(msg['type'], 'metlog_json')
        eq_(msg['logger'], 'zamboni')
        eq_(msg['fields']['foo'], 'bar')
        eq_(msg['fields']['secret'], 42)

    def test_metlog_cef(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'metlog_cef'})

        eq_(len(self.metlog.sender.msgs), 1)
        msg = json.loads(self.metlog.sender.msgs[0])

        eq_(msg['type'], 'cef')
        eq_(msg['logger'], 'zamboni')

    def test_metlog_sentry(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'metlog_sentry'})

        msgs = [json.loads(m) for m in self.metlog.sender.msgs]
        eq_(len(msgs), 1)
        msg = msgs[0]

        eq_(msg['type'], 'sentry')


class TestFeaturedApps(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.c1 = Category.objects.create(name='awesome',
                                     type=amo.ADDON_WEBAPP)
        self.c2 = Category.objects.create(name='groovy',
                                     type=amo.ADDON_WEBAPP)

        self.a1 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                        name='awesome app 1',
                                        type=amo.ADDON_WEBAPP)
        self.a2 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                        name='awesome app 2',
                                        type=amo.ADDON_WEBAPP)
        self.g1 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                        name='groovy app 1',
                                        type=amo.ADDON_WEBAPP)
        self.s1 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                        name='splendid app 1',
                                        type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(category=self.c1, addon=self.a1)
        AddonCategory.objects.create(category=self.c1, addon=self.a2)

        AddonCategory.objects.create(category=self.c2, addon=self.g1)

        AddonCategory.objects.create(category=self.c1, addon=self.s1)
        AddonCategory.objects.create(category=self.c2, addon=self.s1)

        self.client.login(username='admin@mozilla.com', password='password')
        self.url = reverse('zadmin.featured_apps_ajax')

    def test_staff_access(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'AdminTools:View')
        self.client.login(username='regular@mozilla.com', password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

    def test_get_featured_apps(self):
        r = self.client.get(urlparams(self.url, category=self.c1.id))
        assert not r.content

        FeaturedApp.objects.create(app=self.a1, category=self.c1)
        FeaturedApp.objects.create(app=self.s1, category=self.c2,
                                   is_sponsor=True)
        r = self.client.get(urlparams(self.url, category=self.c1.id))
        doc = pq(r.content)
        eq_(len(doc), 1)
        eq_(doc('table td').eq(1).text(), 'awesome app 1')
        eq_(doc('table td').eq(4).text(), 'Not sponsored')

        r = self.client.get(urlparams(self.url, category=self.c2.id))
        doc = pq(r.content)
        eq_(len(doc), 1)
        eq_(doc('table td').eq(1).text(), 'splendid app 1')
        eq_(doc('table td').eq(4).text(), 'Sponsored')

    def test_get_categories(self):
        url = reverse('zadmin.featured_categories_ajax')
        FeaturedApp.objects.create(app=self.a1, category=self.c1)
        FeaturedApp.objects.create(app=self.a2, category=self.c1)
        FeaturedApp.objects.create(app=self.a2, category=None)
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(set(pq(x).text() for x in doc[0]),
            set(['Home Page (1)', 'groovy (0)', 'awesome (2)']))

    def test_add_featured_app(self):
        self.client.post(self.url,
                         {'category': '',
                          'add': self.a1.id})
        assert FeaturedApp.objects.filter(app=self.a1.id,
                                          category=None).exists()

        self.client.post(self.url,
                         {'category': self.c1.id,
                          'add': self.a1.id})
        assert FeaturedApp.objects.filter(app=self.a1,
                                          category=self.c1).exists()

    def test_delete_featured_app(self):
        FeaturedApp.objects.create(app=self.a1, category=None)
        FeaturedApp.objects.create(app=self.a1, category=self.c1)
        self.client.post(self.url,
                         {'category': '',
                          'delete': self.a1.id})
        assert not FeaturedApp.objects.filter(app=self.a1,
                                              category=None).exists()
        assert FeaturedApp.objects.filter(app=self.a1,
                                          category=self.c1).exists()
        FeaturedApp.objects.create(app=self.a1, category=None)
        self.client.post(self.url,
                         {'category': self.c1.id,
                          'delete': self.a1.id})
        assert not FeaturedApp.objects.filter(app=self.a1,
                                              category=self.c1).exists()

    def test_set_region(self):
        f = FeaturedApp.objects.create(app=self.a1, category=None)
        FeaturedAppRegion.objects.create(featured_app=f, region=1)
        r = self.client.post(reverse('zadmin.set_attrs_ajax'),
                             data={'app': f.pk, 'region[]': (3, 2)})
        eq_(r.status_code, 200)
        eq_(list(FeaturedApp.objects.get(pk=f.pk).regions.values_list(
                    'region', flat=True)),
            [2, 3])

    def test_set_startdate(self):
        f = FeaturedApp.objects.create(app=self.a1, category=None)
        FeaturedAppRegion.objects.create(featured_app=f, region=1)
        r = self.client.post(reverse('zadmin.set_attrs_ajax'),
                             data={'app': f.pk, 'startdate': '2012-08-01'})
        eq_(r.status_code, 200)
        eq_(FeaturedApp.objects.get(pk=f.pk).start_date, date(2012, 8, 1))

    def test_set_enddate(self):
        f = FeaturedApp.objects.create(app=self.a1, category=None)
        FeaturedAppRegion.objects.create(featured_app=f, region=1)
        r = self.client.post(reverse('zadmin.set_attrs_ajax'),
                             data={'app': f.pk, 'enddate': '2012-08-31'})
        eq_(r.status_code, 200)
        eq_(FeaturedApp.objects.get(pk=f.pk).end_date, date(2012, 8, 31))

    def test_remove_startdate(self):
        f = FeaturedApp.objects.create(app=self.a1, category=None)
        f.start_date = date(2012, 8, 1)
        f.save()
        FeaturedAppRegion.objects.create(featured_app=f, region=1)
        r = self.client.post(reverse('zadmin.set_attrs_ajax'),
                             data={'app': f.pk})
        eq_(r.status_code, 200)
        eq_(FeaturedApp.objects.get(pk=f.pk).start_date, None)

    def test_remove_enddate(self):
        f = FeaturedApp.objects.create(app=self.a1, category=None)
        FeaturedAppRegion.objects.create(featured_app=f, region=1)
        f.end_date = date(2012, 8, 1)
        f.save()
        r = self.client.post(reverse('zadmin.set_attrs_ajax'),
                             data={'app': f.pk, 'startdate': '2012-07-01',
                                   'enddate': ''})
        eq_(r.status_code, 200)
        eq_(FeaturedApp.objects.get(pk=f.pk).end_date, None)


class TestAddonSearch(amo.tests.ESTestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube', 'base/addon_3615']

    def setUp(self):
        self.reindex(Addon)
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.url = reverse('zadmin.addon-search')

    def test_lookup_addon(self):
        res = self.client.get(urlparams(self.url, q='delicious'))
        eq_(res.status_code, 200)
        links = pq(res.content)('form + h3 + ul li a')
        eq_(len(links), 0)
        self.assertNotContains(res, 'Steamcube')

    def test_lookup_addon_redirect(self):
        res = self.client.get(urlparams(self.url, q='steamcube'))
        # There's only one result, so it should just forward us to that page.
        eq_(res.status_code, 302)


class TestAddonAdmin(amo.tests.TestCase):
    fixtures = ['base/users', 'base/337141-steamcube', 'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.url = reverse('admin:addons_addon_changelist')

    def test_no_webapps(self):
        res = self.client.get(self.url, follow=True)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        rows = doc('#result_list tbody tr')
        eq_(rows.length, 1)
        eq_(rows.find('a').attr('href'), '337141/')
