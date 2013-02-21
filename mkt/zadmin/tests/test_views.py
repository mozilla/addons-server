from datetime import date, timedelta

import json

from mock import patch

from django.conf import settings
from nose.tools import eq_
from pyquery import PyQuery as pq

import waffle

import amo
import amo.tests
import mkt
from addons.models import Addon, AddonCategory, AddonDeviceType, Category
from amo.utils import urlparams
from amo.urlresolvers import reverse
from editors.models import RereviewQueue
from users.models import UserProfile

from mkt.webapps.models import AddonExcludedRegion, Webapp
from mkt.zadmin.models import (FeaturedApp, FeaturedAppCarrier,
                               FeaturedAppRegion)


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
        self.c2 = Category.objects.create(name='groovy', type=amo.ADDON_WEBAPP)

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

    def _featured_urls(self):
        # What FeaturedApps:View should have access to.
        return {
            'zadmin.featured_apps': ['GET', 'POST'],
            'zadmin.featured_apps_ajax': ['GET'],
            'zadmin.featured_categories_ajax': ['GET', 'POST'],
            'zadmin.set_attrs_ajax': []
        }

    def test_write_access(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'FeaturedApps:Edit')
        self.client.login(username='regular@mozilla.com', password='password')
        for url, access in self._featured_urls().iteritems():
            eq_(self.client.get(reverse(url)).status_code, 200,
                'Unexpected status code for %s URL' % url)
            eq_(self.client.post(reverse(url), {}).status_code, 200,
                'Unexpected status code for %s URL' % url)

    def test_read_only_access(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'FeaturedApps:View')
        self.client.login(username='regular@mozilla.com', password='password')
        for url, access in self._featured_urls().iteritems():
            eq_(self.client.get(reverse(url)).status_code,
                200 if 'GET' in access else 403,
                'Unexpected status code for %s URL' % url)
            eq_(self.client.post(reverse(url), {}).status_code,
                200 if 'POST' in access else 403,
                'Unexpected status code for %s URL' % url)

    def test_get_featured_apps(self):
        r = self.client.get(urlparams(self.url, category=self.c1.id))
        assert not r.content

        FeaturedApp.objects.create(app=self.a1, category=self.c1)
        FeaturedApp.objects.create(app=self.s1, category=self.c2,
                                   is_sponsor=True)
        r = self.client.get(urlparams(self.url, category=self.c1.id))
        doc = pq(r.content)
        eq_(len(doc), 1)
        eq_(doc('h2').text(), 'awesome app 1')

        r = self.client.get(urlparams(self.url, category=self.c2.id))
        doc = pq(r.content)
        eq_(len(doc), 1)
        eq_(doc('h2').text(), 'splendid app 1')
        eq_(doc('em.sponsored').attr('title'), 'Sponsored')

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
                             data={'app': f.pk, 'region[]': (4, 2)})
        eq_(r.status_code, 200)
        eq_(list(FeaturedApp.objects.get(pk=f.pk).regions.values_list(
            'region', flat=True)), [2, 4])

    def test_no_set_excluded_region(self):
        AddonExcludedRegion.objects.create(addon=self.a1, region=2)
        f = FeaturedApp.objects.create(app=self.a1, category=None)
        FeaturedAppRegion.objects.create(featured_app=f, region=1)
        r = self.client.post(reverse('zadmin.set_attrs_ajax'),
                             data={'app': f.pk, 'region[]': (3, 2)})
        eq_(r.status_code, 200)
        eq_(list(FeaturedApp.objects.get(pk=f.pk).regions.values_list(
            'region', flat=True)),
            [3])

    def test_set_carrier(self):
        f = FeaturedApp.objects.create(app=self.a1, category=None)
        FeaturedAppCarrier.objects.create(featured_app=f,
                                          carrier='telerizon-mobile')
        r = self.client.post(reverse('zadmin.set_attrs_ajax'),
                             data={'app': f.pk,
                                   'carrier[]': 'telerizon-mobile'})
        eq_(r.status_code, 200)
        eq_(list(FeaturedApp.objects.get(pk=f.pk).carriers.values_list(
            'carrier', flat=True)), ['telerizon-mobile'])

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


class TestFeaturedAppQueryset(amo.tests.TestCase):

    def setUp(self):
        self.c1 = Category.objects.create(name='awesome',
                                          type=amo.ADDON_WEBAPP)
        self.c2 = Category.objects.create(name='groovy', type=amo.ADDON_WEBAPP)

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

        yesterday = date.today() - timedelta(days=1)
        tomorrow = date.today() + timedelta(days=1)

        MOBILE = amo.DEVICE_MOBILE.id
        GAIA = amo.DEVICE_GAIA.id
        DESKTOP = amo.DEVICE_DESKTOP.id
        TABLET = amo.DEVICE_TABLET.id

        self.f1 = FeaturedApp.objects.create(app=self.a1, category=self.c1,
                                             start_date=yesterday,
                                             end_date=tomorrow)
        self.f2 = FeaturedApp.objects.create(app=self.a1, category=self.c2)
        self.f3 = FeaturedApp.objects.create(app=self.s1, category=self.c1)
        self.far1 = FeaturedAppRegion.objects.create(featured_app=self.f1,
                                                     region=mkt.regions.US.id)
        self.far2 = FeaturedAppRegion.objects.create(featured_app=self.f1)
        self.far3 = FeaturedAppRegion.objects.create(featured_app=self.f3)
        self.fac1 = FeaturedAppCarrier.objects.create(featured_app=self.f1,
                                                      carrier='telerizon')
        self.fac2 = FeaturedAppCarrier.objects.create(featured_app=self.f2,
                                                      carrier='cingulizon')
        self.aodt1 = AddonDeviceType.objects.create(addon=self.a1,
                                                    device_type=MOBILE)
        self.aodt2 = AddonDeviceType.objects.create(addon=self.a1,
                                                    device_type=GAIA)
        self.aodt3 = AddonDeviceType.objects.create(addon=self.a2,
                                                    device_type=DESKTOP)
        self.aodt3 = AddonDeviceType.objects.create(addon=self.a2,
                                                    device_type=TABLET)

    def _is_overlap(self, x, y):
        """
        Asserts whether there are any items in `y` that do not exist in `x`.
        Useful for testing whether items in y were filtered from x by a
        custom manager mesthod.
        """
        temp = set(y)  # Don't create the set more than once.
        return all(item in temp for item in x)

    def test_queryset_for_category(self):
        self.assertQuerySetEqual(FeaturedApp.objects.for_category(self.c1),
                                 FeaturedApp.objects.filter(category=self.c1))

    def test_queryset_worldwide(self):
        worldwide = mkt.regions.WORLDWIDE.id
        self.assertQuerySetEqual(
            FeaturedApp.objects.worldwide(),
            FeaturedApp.objects.filter(regions__region=worldwide)
        )

    def test_queryset_for_region(self):
        self.assertQuerySetEqual(
            FeaturedApp.objects.for_region(mkt.regions.US),
            FeaturedApp.objects.filter(regions__region=mkt.regions.US.id)
        )

    def test_queryset_for_carrier(self):
        carrier = 'telerizon'
        self.assertQuerySetEqual(
            FeaturedApp.objects.for_carrier(carrier),
            FeaturedApp.objects.filter(carriers__carrier=carrier)
        )

    def test_queryset_mobile(self):
        self.assertQuerySetEqual(
            FeaturedApp.objects.mobile(),
            FeaturedApp.objects.filter(
                app__addondevicetype__device_type=amo.DEVICE_MOBILE.id)
        )

    def test_queryset_gaia(self):
        self.assertQuerySetEqual(
            FeaturedApp.objects.gaia(),
            FeaturedApp.objects.filter(
                app__addondevicetype__device_type=amo.DEVICE_GAIA.id)
        )

    def test_queryset_tablet(self):
        self.assertQuerySetEqual(
            FeaturedApp.objects.tablet(),
            FeaturedApp.objects.filter(
                app__addondevicetype__device_type=amo.DEVICE_TABLET.id)
        )

    def test_queryset_active_date(self):
        now = date.today()
        start_date = (FeaturedApp.objects.filter(start_date__lte=now) |
                      FeaturedApp.objects.filter(start_date__isnull=True))
        end_date = (FeaturedApp.objects.filter(end_date__gte=now) |
                    FeaturedApp.objects.filter(end_date__isnull=True))
        self.assertQuerySetEqual(FeaturedApp.objects.active_date(),
                                 (start_date | end_date))

    def test_queryset_active(self):
        self.assertQuerySetEqual(FeaturedApp.objects.active(),
                                 FeaturedApp.objects.active_date().public())

    def test_queryset_featured(self):
        carrier = 'telerizon'
        either_cat = [self.c1, self.c2]
        assert self._is_overlap(
            FeaturedApp.objects.for_category(self.c1),
            FeaturedApp.objects.featured(cat=self.c1)
        ), 'Unexpected items in category %s' % self.c1
        assert self._is_overlap(
            FeaturedApp.objects.for_carrier(carrier),
            FeaturedApp.objects.featured(cat=either_cat)
        ), 'Unexpected items for carrier %s' % carrier
        assert self._is_overlap(
            FeaturedApp.objects.gaia(),
            FeaturedApp.objects.featured(gaia=True, cat=either_cat)
        ), 'Unexpected items in Gaia'
        assert self._is_overlap(
            FeaturedApp.objects.mobile(),
            FeaturedApp.objects.featured(mobile=True, cat=either_cat)
        ), 'Unexpected items in mobile'
        assert self._is_overlap(
            FeaturedApp.objects.tablet(),
            FeaturedApp.objects.featured(tablet=True, cat=either_cat)
        ), 'Unexpected items in tablet'
        assert self._is_overlap(
            FeaturedApp.objects.active(),
            FeaturedApp.objects.featured(cat=either_cat)
        ), 'Inactive items in featured queryset'

    def test_queryset_featured_limit(self):
        # Does limit appropriately restrict the number of results?
        limited = FeaturedApp.objects.featured(cat=self.c1, limit=1).count()
        eq_(limited, 1, '%s items returned, only 1 expected' % limited)

        # Does limit fill empty spots with worldwide-featured apps if the
        # number of apps for the specified region are less than the limit?
        # Regression test for Bug #842312
        cat_limited = FeaturedApp.objects.featured(region=mkt.regions.US,
                                                   cat=self.c1, limit=2)
        acceptable_regions = [mkt.regions.US.id, mkt.regions.WORLDWIDE.id]
        eq_(cat_limited.count(), 2,
            'Queryset smaller than `limit` when `region` is specified')
        for app in cat_limited:
            app_regions = (r.region for r in app.regions.all())
            acceptable = (r in acceptable_regions for r in app_regions)
            assert any(acceptable), 'App not featured in US or Worldwide'

    @patch.object(waffle, 'switch_is_active', lambda x: True)
    def test_soft_deleted_app(self):
        self.a1.delete()
        eq_(list(FeaturedApp.objects.all()), [self.f3])


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


class TestManifestRevalidation(amo.tests.WebappTestCase):
    fixtures = ['webapps/337141-steamcube', 'base/users']

    def setUp(self):
        self.url = reverse('zadmin.manifest_revalidation')

    def tearDown(self):
        self.client.logout()

    def _test_revalidation(self):
        current_count = RereviewQueue.objects.count()
        response = self.client.post(self.url)
        eq_(response.status_code, 200)
        self.assertTrue('Manifest revalidation queued' in response.content)
        eq_(RereviewQueue.objects.count(), current_count + 1)

    def test_revalidation_by_reviewers(self):
        # Sr Reviewers users should be able to use the feature.
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'ReviewerAdminTools:View')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

        self._test_revalidation()

    def test_revalidation_by_admin(self):
        # Admin users should be able to use the feature.
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self._test_revalidation()

    def test_unpriviliged_user(self):
        # Unprivileged user should not be able to reach the feature.
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        eq_(self.client.post(self.url).status_code, 403)
