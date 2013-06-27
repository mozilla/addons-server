# -*- coding: utf-8 -*-
import functools
import json
import os
import shutil
import unittest
import uuid
import zipfile
from datetime import datetime, timedelta

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.db.models.signals import post_delete, post_save
from django.utils.translation import ugettext_lazy as _

import mock
import waffle
from nose import SkipTest
from nose.tools import eq_, ok_, raises

import amo
from addons.models import (Addon, AddonCategory, AddonDeviceType,
                           BlacklistedSlug, Category, Preview, version_changed)
from addons.signals import version_changed as version_changed_signal
from amo.helpers import absolutify
from amo.tests import app_factory, version_factory
from amo.urlresolvers import reverse
from constants.applications import DEVICE_TYPES
from editors.models import RereviewQueue
from files.models import File
from files.tests.test_models import UploadTest as BaseUploadTest
from files.utils import WebAppParser
from lib.crypto import packaged
from lib.crypto.tests import mock_sign
from users.models import UserProfile
from versions.models import update_status, Version

import mkt
from mkt.constants import APP_FEATURES, apps
from mkt.site.fixtures import fixture
from mkt.submit.tests.test_views import BasePackagedAppTest, BaseWebAppTest
from mkt.webapps.models import (AddonExcludedRegion, AppFeatures,
                                get_excluded_in, Installed, Webapp,
                                WebappIndexer)


class TestWebapp(amo.tests.TestCase):

    def test_hard_deleted(self):
        # Uncomment when redis gets fixed on ci.mozilla.org.
        raise SkipTest

        w = Webapp.objects.create(status=amo.STATUS_PUBLIC)
        # Until bug 755214 is fixed, `len` that ish.
        eq_(len(Webapp.objects.all()), 1)
        eq_(len(Webapp.with_deleted.all()), 1)

        w.delete('boom shakalakalaka')
        eq_(len(Webapp.objects.all()), 0)
        eq_(len(Webapp.with_deleted.all()), 0)

    def test_delete_reason(self):
        """Test deleting with a reason gives the reason in the mail."""
        reason = u'trêason'
        w = Webapp.objects.create(status=amo.STATUS_PUBLIC)
        w.name = u'é'
        eq_(len(mail.outbox), 0)
        w.delete(msg='bye', reason=reason)
        eq_(len(mail.outbox), 1)
        assert reason in mail.outbox[0].body

    def test_soft_deleted(self):
        # Uncomment when redis gets fixed on ci.mozilla.org.
        raise SkipTest

        waffle.models.Switch.objects.create(name='soft_delete', active=True)

        w = Webapp.objects.create(slug='ballin', app_slug='app-ballin',
                                  app_domain='http://omg.org/yes',
                                  status=amo.STATUS_PENDING)
        eq_(len(Webapp.objects.all()), 1)
        eq_(len(Webapp.with_deleted.all()), 1)

        w.delete('boom shakalakalaka')
        eq_(len(Webapp.objects.all()), 0)
        eq_(len(Webapp.with_deleted.all()), 1)

        # When an app is deleted its slugs and domain should get relinquished.
        post_mortem = Webapp.with_deleted.filter(id=w.id)
        eq_(post_mortem.count(), 1)
        for attr in ('slug', 'app_slug', 'app_domain'):
            eq_(getattr(post_mortem[0], attr), None)

    def test_soft_deleted_valid(self):
        w = Webapp.objects.create(status=amo.STATUS_PUBLIC)
        Webapp.objects.create(status=amo.STATUS_DELETED)
        eq_(list(Webapp.objects.valid()), [w])
        eq_(sorted(Webapp.with_deleted.valid()), [w])

    def test_webapp_type(self):
        webapp = Webapp()
        webapp.save()
        eq_(webapp.type, amo.ADDON_WEBAPP)

    def test_app_slugs_separate_from_addon_slugs(self):
        Addon.objects.create(type=1, slug='slug')
        webapp = Webapp(app_slug='slug')
        webapp.save()
        eq_(webapp.slug, 'app-%s' % webapp.id)
        eq_(webapp.app_slug, 'slug')

    def test_app_slug_collision(self):
        Webapp(app_slug='slug').save()
        w2 = Webapp(app_slug='slug')
        w2.save()
        eq_(w2.app_slug, 'slug-1')

        w3 = Webapp(app_slug='slug')
        w3.save()
        eq_(w3.app_slug, 'slug-2')

    def test_app_slug_blocklist(self):
        BlacklistedSlug.objects.create(name='slug')
        w = Webapp(app_slug='slug')
        w.save()
        eq_(w.app_slug, 'slug~')

    def test_get_url_path(self):
        webapp = Webapp(app_slug='woo')
        eq_(webapp.get_url_path(), '/app/woo/')

    def test_get_api_url(self):
        webapp = Webapp(app_slug='woo', pk=1)
        eq_(webapp.get_api_url(), '/api/v1/apps/app/woo/')

    def test_get_stats_url(self):
        webapp = Webapp(app_slug='woo')

        eq_(webapp.get_stats_url(), '/app/woo/statistics/')

        url = webapp.get_stats_url(action='installs_series',
                                   args=['day', '20120101', '20120201',
                                         'json'])
        eq_(url, '/app/woo/statistics/installs-day-20120101-20120201.json')

    def test_get_inapp_stats_url(self):
        webapp = Webapp.objects.create(app_slug='woo')
        eq_(webapp.get_stats_inapp_url(action='revenue', inapp='duh'),
            '/app/woo/statistics/inapp/duh/sales/')

    def test_get_origin(self):
        url = 'http://www.xx.com:4000/randompath/manifest.webapp'
        webapp = Webapp(manifest_url=url)
        eq_(webapp.origin, 'http://www.xx.com:4000')

    def test_get_packaged_origin(self):
        webapp = Webapp(app_domain='app://foo.com', is_packaged=True,
                        manifest_url='')
        eq_(webapp.origin, 'app://foo.com')

    def test_reviewed(self):
        assert not Webapp().is_unreviewed()

    def test_cannot_be_purchased(self):
        eq_(Webapp(premium_type=True).can_be_purchased(), False)
        eq_(Webapp(premium_type=False).can_be_purchased(), False)

    def test_can_be_purchased(self):
        w = Webapp(status=amo.STATUS_PUBLIC, premium_type=True)
        eq_(w.can_be_purchased(), True)

        w = Webapp(status=amo.STATUS_PUBLIC, premium_type=False)
        eq_(w.can_be_purchased(), False)

    def test_get_previews(self):
        w = Webapp.objects.create()
        eq_(w.get_promo(), None)

        p = Preview.objects.create(addon=w, position=0)
        eq_(list(w.get_previews()), [p])

        p.update(position=-1)
        eq_(list(w.get_previews()), [])

    def test_get_promo(self):
        w = Webapp.objects.create()
        eq_(w.get_promo(), None)

        p = Preview.objects.create(addon=w, position=0)
        eq_(w.get_promo(), None)

        p.update(position=-1)
        eq_(w.get_promo(), p)

    def test_mark_done_pending(self):
        w = Webapp()
        eq_(w.status, amo.STATUS_NULL)
        w.mark_done()
        eq_(w.status, amo.WEBAPPS_UNREVIEWED_STATUS)

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_no_icon_in_manifest(self, get_manifest_json):
        webapp = Webapp()
        get_manifest_json.return_value = {}
        eq_(webapp.has_icon_in_manifest(), False)

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_has_icon_in_manifest(self, get_manifest_json):
        webapp = Webapp()
        get_manifest_json.return_value = {'icons': {}}
        eq_(webapp.has_icon_in_manifest(), True)

    def test_no_version(self):
        webapp = Webapp()
        eq_(webapp.get_manifest_json(), None)
        eq_(webapp.current_version, None)

    def test_has_premium(self):
        webapp = Webapp(premium_type=amo.ADDON_PREMIUM)
        webapp._premium = mock.Mock()
        webapp._premium.price = 1
        eq_(webapp.has_premium(), True)

        webapp._premium.price = 0
        eq_(webapp.has_premium(), True)

    def test_get_price_no_premium(self):
        webapp = Webapp(premium_type=amo.ADDON_PREMIUM)
        eq_(webapp.get_price(), None)
        eq_(webapp.get_price_locale(), None)

    def test_get_price(self):
        webapp = amo.tests.app_factory()
        self.make_premium(webapp)
        eq_(webapp.get_price(region=mkt.regions.US.id), 1)

    def test_get_price_tier(self):
        webapp = amo.tests.app_factory()
        self.make_premium(webapp)
        eq_(str(webapp.get_tier().price), '1.00')
        ok_(webapp.get_tier_name())

    def test_get_price_tier_no_charge(self):
        webapp = amo.tests.app_factory()
        self.make_premium(webapp, '0.00')
        eq_(str(webapp.get_tier().price), '0.00')
        ok_(webapp.get_tier_name())

    def test_has_no_premium(self):
        webapp = Webapp(premium_type=amo.ADDON_PREMIUM)
        webapp._premium = None
        eq_(webapp.has_premium(), False)

    def test_not_premium(self):
        eq_(Webapp().has_premium(), False)

    def test_get_region_ids_no_exclusions(self):
        # This returns IDs for the *included* regions.
        eq_(Webapp().get_region_ids(), mkt.regions.REGION_IDS)

    def test_get_region_ids_with_exclusions(self):
        w1 = Webapp.objects.create()
        w2 = Webapp.objects.create()

        AddonExcludedRegion.objects.create(addon=w1, region=mkt.regions.BR.id)
        AddonExcludedRegion.objects.create(addon=w1, region=mkt.regions.US.id)
        AddonExcludedRegion.objects.create(addon=w2, region=mkt.regions.UK.id)

        w1_regions = list(mkt.regions.REGION_IDS)
        w1_regions.remove(mkt.regions.BR.id)
        w1_regions.remove(mkt.regions.US.id)

        w2_regions = list(mkt.regions.REGION_IDS)
        w2_regions.remove(mkt.regions.UK.id)

        eq_(sorted(Webapp.objects.get(id=w1.id).get_region_ids()),
            sorted(w1_regions))
        eq_(sorted(Webapp.objects.get(id=w2.id).get_region_ids()),
            sorted(w2_regions))

    def test_get_regions_no_exclusions(self):
        # This returns the class definitions for the *included* regions.
        eq_(sorted(Webapp().get_regions()),
            sorted(mkt.regions.REGIONS_CHOICES_ID_DICT.values()))

    def test_get_regions_with_exclusions(self):
        w1 = Webapp.objects.create()
        w2 = Webapp.objects.create()

        AddonExcludedRegion.objects.create(addon=w1, region=mkt.regions.BR.id)
        AddonExcludedRegion.objects.create(addon=w1, region=mkt.regions.US.id)
        AddonExcludedRegion.objects.create(addon=w2, region=mkt.regions.UK.id)

        all_regions = mkt.regions.REGIONS_CHOICES_ID_DICT.values()

        w1_regions = list(all_regions)
        w1_regions.remove(mkt.regions.BR)
        w1_regions.remove(mkt.regions.US)

        w2_regions = list(all_regions)
        w2_regions.remove(mkt.regions.UK)

        eq_(sorted(Webapp.objects.get(id=w1.id).get_regions()),
            sorted(w1_regions))
        eq_(sorted(Webapp.objects.get(id=w2.id).get_regions()),
            sorted(w2_regions))

    def test_package_helpers(self):
        app1 = app_factory()
        eq_(app1.is_packaged, False)
        app2 = app_factory(is_packaged=True)
        eq_(app2.is_packaged, True)

    def test_package_no_version(self):
        webapp = Webapp.objects.create(manifest_url='http://foo.com')
        eq_(webapp.is_packaged, False)

    def test_assign_uuid(self):
        app = Webapp()
        eq_(app.guid, None)
        app.save()
        assert app.guid is not None, (
            'Expected app to have a UUID assigned to guid')

    @mock.patch.object(uuid, 'uuid4')
    def test_assign_uuid_max_tries(self, mock_uuid4):
        guid = 'abcdef12-abcd-abcd-abcd-abcdef123456'
        mock_uuid4.return_value = uuid.UUID(guid)
        # Create another webapp with and set the guid.
        Webapp.objects.create(guid=guid)
        # Now `assign_uuid()` should fail.
        app = Webapp()
        with self.assertRaises(ValueError):
            app.save()

    def test_is_premium_type_upgrade_check(self):
        app = Webapp()
        ALL = set(amo.ADDON_FREES + amo.ADDON_PREMIUMS)
        free_upgrade = ALL - set([amo.ADDON_FREE])
        free_inapp_upgrade = ALL - set([amo.ADDON_FREE, amo.ADDON_FREE_INAPP])

        # Checking ADDON_FREE changes.
        app.premium_type = amo.ADDON_FREE
        for pt in ALL:
            eq_(app.is_premium_type_upgrade(pt), pt in free_upgrade)

        # Checking ADDON_FREE_INAPP changes.
        app.premium_type = amo.ADDON_FREE_INAPP
        for pt in ALL:
            eq_(app.is_premium_type_upgrade(pt), pt in free_inapp_upgrade)

        # All else is false.
        for pt_old in ALL - set([amo.ADDON_FREE, amo.ADDON_FREE_INAPP]):
            app.premium_type = pt_old
            for pt_new in ALL:
                eq_(app.is_premium_type_upgrade(pt_new), False)

    @raises(ValueError)
    def test_parse_domain(self):
        Webapp(is_packaged=True).parsed_app_domain

    def test_featured_creatured(self):
        cat = Category.objects.create(type=amo.ADDON_WEBAPP, slug='cat')
        # Three creatured apps for this category for the US region.
        creatured = []
        for x in xrange(3):
            app = amo.tests.app_factory()
            self.make_featured(app=app, category=cat,
                               region=mkt.regions.US)
            creatured.append(app)
        creatured_ids = [app.id for app in creatured]

        # Check that these apps are featured for this category -
        # and only in US region.
        for abbr, region in mkt.regions.REGIONS_CHOICES:
            self.assertSetEqual(
                [a.id for a in Webapp.featured(cat=cat, region=region)],
                creatured_ids if abbr == 'us' else [])

    def test_featured_no_creatured(self):
        # Three creatured apps for this category for the US region.
        creatured = []
        for x in xrange(3):
            app = amo.tests.app_factory()
            self.make_featured(app=app, category=None,
                               region=mkt.regions.US)
            creatured.append(app)
        creatured_ids = [app.id for app in creatured]

        # Check that these apps are featured for this category -
        # and only in US region.
        for abbr, region in mkt.regions.REGIONS_CHOICES:
            self.assertSetEqual(
                [a.id for a in Webapp.featured(cat=None, region=region)],
                creatured_ids if abbr == 'us' else [])

    def test_featured_fallback_to_worldwide(self):
        usa_app = app_factory()
        self.make_featured(usa_app, category=None,
                           region=mkt.regions.US)

        worldwide_apps = []
        for x in xrange(3):
            app = app_factory()
            self.make_featured(app, category=None,
                               region=mkt.regions.WORLDWIDE)
            worldwide_apps.append(app.id)

        # In US: 1 US-featured app + 3 Worldwide-featured apps.
        # Elsewhere: 3 Worldwide-featured apps.
        for abbr, region in mkt.regions.REGIONS_CHOICES:
            if abbr == 'us':
                expected = [usa_app.id] + worldwide_apps
            else:
                expected = worldwide_apps
            self.assertSetEqual(
                [a.id for a in Webapp.featured(cat=None, region=region)],
                expected)

    def test_app_type_hosted(self):
        eq_(Webapp().app_type, 'hosted')

    def test_app_type_packaged(self):
        eq_(Webapp(is_packaged=True).app_type, 'packaged')

    def test_nomination_new(self):
        app = app_factory()
        app.update(status=amo.STATUS_NULL)
        app.versions.latest().update(nomination=None)
        app.update(status=amo.STATUS_PENDING)
        assert app.versions.latest().nomination

    def test_nomination_rejected(self):
        app = app_factory()
        app.update(status=amo.STATUS_REJECTED)
        app.versions.latest().update(nomination=self.days_ago(1))
        app.update(status=amo.STATUS_PENDING)
        self.assertCloseToNow(app.versions.latest().nomination)

    def test_nomination_pkg_pending_new_version(self):
        # New versions while pending inherit version nomination.
        app = app_factory()
        app.update(status=amo.STATUS_PENDING, is_packaged=True)
        old_ver = app.versions.latest()
        old_ver.update(nomination=self.days_ago(1))
        old_ver.all_files[0].update(status=amo.STATUS_PENDING)
        v = Version.objects.create(addon=app, version='1.9')
        eq_(v.nomination, old_ver.nomination)

    def test_nomination_pkg_public_new_version(self):
        # New versions while public get a new version nomination.
        app = app_factory()
        app.update(is_packaged=True)
        old_ver = app.versions.latest()
        old_ver.update(nomination=self.days_ago(1))
        v = Version.objects.create(addon=app, version='1.9')
        self.assertCloseToNow(v.nomination)

    def test_excluded_in(self):
        app1 = app_factory()
        region = mkt.regions.BR
        AddonExcludedRegion.objects.create(addon=app1, region=region.id)
        eq_(get_excluded_in(region.id), [app1.id])

    def test_supported_locale_property(self):
        app = app_factory()
        app.versions.latest().update(supported_locales='de,fr', _signal=False)
        app.reload()
        eq_(app.supported_locales,
            (u'English (US)', [u'Deutsch', u'Fran\xe7ais']))

    def test_supported_locale_property_empty(self):
        app = app_factory()
        eq_(app.supported_locales, (u'English (US)', []))

    def test_supported_locale_property_bad(self):
        app = app_factory()
        app.versions.latest().update(supported_locales='de,xx', _signal=False)
        app.reload()
        eq_(app.supported_locales, (u'English (US)', [u'Deutsch']))

    def test_supported_locale_app_rejected(self):
        """
        Simulate an app being rejected, which sets the
        app.current_version to None, and verify supported_locales works
        as expected -- which is that if there is no current version we
        can't report supported_locales for it, so we return an empty
        list.
        """
        app = app_factory()
        app.versions.latest().update(supported_locales='de', _signal=False)
        app.update(status=amo.STATUS_REJECTED)
        app.versions.latest().all_files[0].update(status=amo.STATUS_REJECTED)
        app.update_version()
        app.reload()
        eq_(app.supported_locales, (u'English (US)', []))


class TestPackagedAppManifestUpdates(amo.tests.TestCase):
    # Note: More extensive tests for `Addon.update_names` are in the Addon
    # model tests.
    fixtures = ['base/platforms']

    def setUp(self):
        self.webapp = amo.tests.app_factory(is_packaged=True,
                                            default_locale='en-US')
        self.webapp.name = {'en-US': 'Packaged App'}
        self.webapp.save()

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_package_manifest_default_name_change(self, get_manifest_json):
        get_manifest_json.return_value = {'name': 'Yo'}
        self.trans_eq(self.webapp.name, 'en-US', 'Packaged App')
        self.webapp.update_name_from_package_manifest()
        self.webapp = Webapp.objects.get(pk=self.webapp.pk)
        self.trans_eq(self.webapp.name, 'en-US', 'Yo')

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_package_manifest_default_locale_change(self, get_manifest_json):
        get_manifest_json.return_value = {'name': 'Yo', 'default_locale': 'fr'}
        eq_(self.webapp.default_locale, 'en-US')
        self.webapp.update_name_from_package_manifest()
        eq_(self.webapp.default_locale, 'fr')
        self.trans_eq(self.webapp.name, 'en-US', None)
        self.trans_eq(self.webapp.name, 'fr', 'Yo')

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_package_manifest_locales_change(self, get_manifest_json):
        get_manifest_json.return_value = {'name': 'Yo',
                                          'locales': {'es': {'name': 'es'},
                                                      'de': {'name': 'de'}}}
        self.webapp.update_supported_locales()
        eq_(self.webapp.current_version.supported_locales, 'de,es')


class TestWebappVersion(amo.tests.TestCase):
    fixtures = ['base/platforms']

    def test_no_version(self):
        eq_(Webapp().get_latest_file(), None)

    def test_no_file(self):
        webapp = Webapp.objects.create(manifest_url='http://foo.com')
        webapp._current_version = Version.objects.create(addon=webapp)
        eq_(webapp.get_latest_file(), None)

    def test_right_file(self):
        webapp = Webapp.objects.create(manifest_url='http://foo.com')
        version = Version.objects.create(addon=webapp)
        old_file = File.objects.create(version=version, platform_id=1)
        old_file.update(created=datetime.now() - timedelta(days=1))
        new_file = File.objects.create(version=version, platform_id=1)
        webapp._current_version = version
        eq_(webapp.get_latest_file().pk, new_file.pk)


class TestWebappManager(amo.tests.TestCase):

    def setUp(self):
        self.reviewed_eq = (lambda f=[]:
                            eq_(list(Webapp.objects.reviewed()), f))
        self.listed_eq = (lambda f=[]: eq_(list(Webapp.objects.visible()), f))

    def test_reviewed(self):
        for status in amo.REVIEWED_STATUSES:
            w = Webapp.objects.create(status=status)
            self.reviewed_eq([w])
            Webapp.objects.all().delete()

    def test_unreviewed(self):
        for status in amo.UNREVIEWED_STATUSES:
            Webapp.objects.create(status=status)
            self.reviewed_eq()
            Webapp.objects.all().delete()

    def test_listed(self):
        # Public status, non-null current version, non-user-disabled.
        w = app_factory(status=amo.STATUS_PUBLIC)
        self.listed_eq([w])

    def test_unlisted(self):
        # Public, null current version, non-user-disabled.
        w = Webapp.objects.create()
        self.listed_eq()

        # With current version but unreviewed.
        Version.objects.create(addon=w)
        self.listed_eq()

        # And user-disabled.
        w.update(disabled_by_user=True)
        self.listed_eq()

    def test_by_identifier(self):
        w = Webapp.objects.create(app_slug='foo')
        eq_(Webapp.objects.by_identifier(w.id), w)
        eq_(Webapp.objects.by_identifier(str(w.id)), w)
        eq_(Webapp.objects.by_identifier(w.app_slug), w)
        with self.assertRaises(Webapp.DoesNotExist):
            Webapp.objects.by_identifier('fake')


class TestManifest(BaseWebAppTest):

    def test_get_manifest_json(self):
        webapp = self.post_addon()
        assert webapp.current_version
        assert webapp.current_version.has_files
        with open(self.manifest, 'r') as mf:
            manifest_json = json.load(mf)
            eq_(webapp.get_manifest_json(), manifest_json)


class PackagedFilesMixin(amo.tests.AMOPaths):

    def setUp(self):
        self.package = self.packaged_app_path('mozball.zip')

    def setup_files(self, filename='mozball.zip'):
        # This assumes self.file exists.
        if not storage.exists(self.file.file_path):
            try:
                # We don't care if these dirs exist.
                os.makedirs(os.path.dirname(self.file.file_path))
            except OSError:
                pass
            shutil.copyfile(self.packaged_app_path(filename),
                            self.file.file_path)


class TestPackagedModel(amo.tests.TestCase):

    @mock.patch.object(settings, 'SITE_URL', 'http://hy.fr')
    def test_create_blocklisted_version(self):
        app = app_factory(name='Mozillaball ょ', app_slug='test',
                          is_packaged=True, version_kw={'version': '1.0',
                                                        'created': None})
        app.create_blocklisted_version()
        app = app.reload()
        v = app.versions.latest()
        f = v.files.latest()

        eq_(app.status, amo.STATUS_BLOCKED)
        eq_(app.versions.count(), 2)
        eq_(v.version, 'blocklisted-1.0')

        eq_(app._current_version, v)
        assert 'blocklisted-1.0' in f.filename
        eq_(f.status, amo.STATUS_BLOCKED)

        # Check manifest.
        url = app.get_manifest_url()
        res = self.client.get(url)
        eq_(res['Content-type'],
            'application/x-web-app-manifest+json; charset=utf-8')
        assert 'etag' in res._headers
        data = json.loads(res.content)
        eq_(data['name'], 'Blocked by Mozilla')
        eq_(data['version'], 'blocklisted-1.0')
        eq_(data['package_path'], 'http://hy.fr/downloads/file/%s/%s' % (
            f.id, f.filename))


class TestPackagedManifest(BasePackagedAppTest):

    def _get_manifest_json(self):
        zf = zipfile.ZipFile(self.package)
        data = zf.open('manifest.webapp').read()
        zf.close()
        return json.loads(data)

    def test_get_manifest_json(self):
        webapp = self.post_addon()
        eq_(webapp.status, amo.STATUS_NULL)
        assert webapp.current_version
        assert webapp.current_version.has_files
        mf = self._get_manifest_json()
        eq_(webapp.get_manifest_json(), mf)

    def test_get_manifest_json_w_file(self):
        webapp = self.post_addon()
        eq_(webapp.status, amo.STATUS_NULL)
        assert webapp.current_version
        assert webapp.current_version.has_files
        file_ = webapp.current_version.all_files[0]
        mf = self._get_manifest_json()
        eq_(webapp.get_manifest_json(file_), mf)

    def test_get_manifest_json_multiple_versions(self):
        # Post the real app/version, but backfill an older version.
        webapp = self.post_addon()
        webapp.update(status=amo.STATUS_PUBLIC, _current_version=None)
        version = version_factory(addon=webapp, version='0.5',
                                  created=self.days_ago(1))
        version.files.update(created=self.days_ago(1))
        webapp = Webapp.objects.get(pk=webapp.pk)
        webapp.update_version()
        assert webapp.current_version
        assert webapp.current_version.has_files
        mf = self._get_manifest_json()
        eq_(webapp.get_manifest_json(), mf)

    def test_cached_manifest_is_cached(self):
        webapp = self.post_addon()
        # First call does queries and caches results.
        webapp.get_cached_manifest()
        # Subsequent calls are cached.
        with self.assertNumQueries(0):
            webapp.get_cached_manifest()

    def test_cached_manifest_contents(self):
        webapp = self.post_addon(
            data={'packaged': True, 'free_platforms': 'free-firefoxos'})
        version = webapp.current_version
        self.file = version.all_files[0]
        self.setup_files()
        manifest = self._get_manifest_json()

        data = json.loads(webapp.get_cached_manifest())
        eq_(data['name'], webapp.name)
        eq_(data['version'], webapp.current_version.version)
        eq_(data['size'], self.file.size)
        eq_(data['release_notes'], version.releasenotes)
        eq_(data['package_path'], absolutify(
            os.path.join(reverse('downloads.file', args=[self.file.id]),
                         self.file.filename)))
        eq_(data['developer'], manifest['developer'])
        eq_(data['icons'], manifest['icons'])
        eq_(data['locales'], manifest['locales'])

    @mock.patch.object(packaged, 'sign', mock_sign)
    def test_package_path(self):
        webapp = self.post_addon(
            data={'packaged': True, 'free_platforms': 'free-firefoxos'})
        version = webapp.current_version
        file = version.all_files[0]
        res = self.client.get(file.get_url_path('manifest'))
        eq_(res.status_code, 200)
        eq_(res['content-type'], 'application/zip')

    def test_packaged_with_BOM(self):
        # Exercise separate code paths to loading the packaged app manifest.
        self.setup_files('mozBOM.zip')
        assert WebAppParser().parse(self.file.file_path)
        self.assertTrue(self.app.has_icon_in_manifest())


class TestDomainFromURL(unittest.TestCase):

    def test_simple(self):
        eq_(Webapp.domain_from_url('http://mozilla.com/'),
            'http://mozilla.com')

    def test_long_path(self):
        eq_(Webapp.domain_from_url('http://mozilla.com/super/rad.webapp'),
            'http://mozilla.com')

    def test_no_normalize_www(self):
        eq_(Webapp.domain_from_url('http://www.mozilla.com/super/rad.webapp'),
            'http://www.mozilla.com')

    def test_with_port(self):
        eq_(Webapp.domain_from_url('http://mozilla.com:9000/'),
            'http://mozilla.com:9000')

    def test_subdomains(self):
        eq_(Webapp.domain_from_url('http://apps.mozilla.com/'),
            'http://apps.mozilla.com')

    def test_https(self):
        eq_(Webapp.domain_from_url('https://mozilla.com/'),
            'https://mozilla.com')

    def test_normalize_case(self):
        eq_(Webapp.domain_from_url('httP://mOzIllA.com/'),
            'http://mozilla.com')

    @raises(ValueError)
    def test_none(self):
        Webapp.domain_from_url(None)

    @raises(ValueError)
    def test_empty(self):
        Webapp.domain_from_url('')

    def test_empty_or_none(self):
        eq_(Webapp.domain_from_url(None, allow_none=True), None)

    @raises(ValueError)
    def test_no_scheme(self):
        Webapp.domain_from_url('f.c')


class TestTransformer(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.device = DEVICE_TYPES.keys()[0]

    @mock.patch('mkt.webapps.models.Addon.transformer')
    def test_addon_transformer_called(self, transformer):
        transformer.return_value = {}
        list(Webapp.objects.all())
        assert transformer.called

    def test_device_types(self):
        AddonDeviceType.objects.create(addon_id=337141,
                                       device_type=self.device)
        webapps = list(Webapp.objects.filter(id=337141))

        with self.assertNumQueries(0):
            for webapp in webapps:
                assert webapp._device_types
                eq_(webapp.device_types, [DEVICE_TYPES[self.device]])

    def test_device_type_cache(self):
        webapp = Webapp.objects.get(id=337141)
        webapp._device_types = []
        with self.assertNumQueries(0):
            eq_(webapp.device_types, [])


class TestIsComplete(amo.tests.TestCase):

    def setUp(self):
        self.device = DEVICE_TYPES.keys()[0]
        self.cat = Category.objects.create(name='c', type=amo.ADDON_WEBAPP)
        self.webapp = Webapp.objects.create(type=amo.ADDON_WEBAPP,
                                            status=amo.STATUS_NULL)

    def fail(self, value):
        can, reasons = self.webapp.is_complete()
        eq_(can, False)
        assert value in reasons[0], reasons

    def test_fail(self):
        self.fail('email')

        self.webapp.support_email = 'a@a.com'
        self.webapp.save()
        self.fail('name')

        self.webapp.name = 'name'
        self.webapp.save()
        self.fail('device')

        self.webapp.addondevicetype_set.create(device_type=self.device)
        self.webapp.save()
        self.fail('category')

        AddonCategory.objects.create(addon=self.webapp, category=self.cat)
        self.fail('screenshot')

        self.webapp.previews.create()
        eq_(self.webapp.is_complete()[0], True)


class TestAddonExcludedRegion(amo.tests.WebappTestCase):

    def setUp(self):
        super(TestAddonExcludedRegion, self).setUp()
        self.excluded = self.app.addonexcludedregion

        eq_(list(self.excluded.values_list('id', flat=True)), [])
        self.er = self.app.addonexcludedregion.create(region=mkt.regions.UK.id)
        eq_(list(self.excluded.values_list('id', flat=True)), [self.er.id])

    def test_exclude_multiple(self):
        other = AddonExcludedRegion.objects.create(addon=self.app,
                                                   region=mkt.regions.BR.id)
        self.assertSetEqual(self.excluded.values_list('id', flat=True),
                            [self.er.id, other.id])

    def test_remove_excluded(self):
        self.er.delete()
        eq_(list(self.excluded.values_list('id', flat=True)), [])

    def test_get_region(self):
        eq_(self.er.get_region(), mkt.regions.UK)

    def test_unicode(self):
        eq_(unicode(self.er), '%s: %s' % (self.app, mkt.regions.UK.slug))


class TestContentRatingsIn(amo.tests.WebappTestCase):

    def test_not_in_region(self):
        for region in mkt.regions.ALL_REGIONS:
            eq_(self.app.content_ratings_in(region=region), [])

        for region in mkt.regions.ALL_REGIONS:
            AddonExcludedRegion.objects.create(addon=self.app,
                                               region=region.id)
            eq_(self.get_app().content_ratings_in(region=region), [])

    def test_in_for_region_and_category(self):
        cat = Category.objects.create(slug='games', type=amo.ADDON_WEBAPP)
        for region in mkt.regions.ALL_REGIONS:
            eq_(self.app.content_ratings_in(region=region, category='games'),
                [])
            eq_(self.app.content_ratings_in(region=region, category=cat), [])

    def test_in_region_and_category(self):
        self.make_game()
        cat = Category.objects.get(slug='games')
        for region in mkt.regions.ALL_REGIONS:
            eq_(self.app.listed_in(region=region, category='games'), True)
            eq_(self.app.listed_in(region=region, category=cat),
                True)

    def test_in_region_and_not_in_category(self):
        cat = Category.objects.create(slug='games', type=amo.ADDON_WEBAPP)
        for region in mkt.regions.ALL_REGIONS:
            eq_(self.app.content_ratings_in(region=region, category='games'),
                [])
            eq_(self.app.content_ratings_in(region=region, category=cat), [])


class TestQueue(amo.tests.WebappTestCase):

    def test_in_queue(self):
        assert not self.app.in_rereview_queue()
        RereviewQueue.objects.create(addon=self.app)
        assert self.app.in_rereview_queue()


class TestPackagedSigning(amo.tests.WebappTestCase):

    @mock.patch('lib.crypto.packaged.sign')
    def test_not_packaged(self, sign):
        self.app.update(is_packaged=False)
        assert not self.app.sign_if_packaged(self.app.current_version.pk)
        assert not sign.called

    @mock.patch('lib.crypto.packaged.sign')
    def test_packaged(self, sign):
        self.app.update(is_packaged=True)
        assert self.app.sign_if_packaged(self.app.current_version.pk)
        eq_(sign.call_args[0][0], self.app.current_version.pk)

    @mock.patch('lib.crypto.packaged.sign')
    def test_packaged_reviewer(self, sign):
        self.app.update(is_packaged=True)
        assert self.app.sign_if_packaged(self.app.current_version.pk,
                                         reviewer=True)
        eq_(sign.call_args[0][0], self.app.current_version.pk)
        eq_(sign.call_args[1]['reviewer'], True)


class TestUpdateStatus(amo.tests.TestCase):

    def setUp(self):
        # Disabling signals to simplify these tests and because create doesn't
        # call the signals anyway.
        version_changed_signal.disconnect(version_changed,
                                          dispatch_uid='version_changed')
        post_save.disconnect(update_status, sender=Version,
                             dispatch_uid='version_update_status')
        post_delete.disconnect(update_status, sender=Version,
                               dispatch_uid='version_update_status')

    def tearDown(self):
        version_changed_signal.connect(version_changed,
                                       dispatch_uid='version_changed')
        post_save.connect(update_status, sender=Version,
                          dispatch_uid='version_update_status')
        post_delete.connect(update_status, sender=Version,
                            dispatch_uid='version_update_status')

    def test_no_versions(self):
        app = Webapp.objects.create(status=amo.STATUS_PUBLIC)
        app.update_status()
        eq_(app.status, amo.STATUS_NULL)

    def test_version_no_files(self):
        app = Webapp.objects.create(status=amo.STATUS_PUBLIC)
        Version(addon=app).save()
        app.update_status()
        eq_(app.status, amo.STATUS_NULL)

    def test_only_version_deleted(self):
        app = amo.tests.app_factory(status=amo.STATUS_REJECTED)
        app.current_version.delete()
        app.update_status()
        eq_(app.status, amo.STATUS_NULL)

    def test_other_version_deleted(self):
        app = amo.tests.app_factory(status=amo.STATUS_REJECTED)
        amo.tests.version_factory(addon=app)
        app.current_version.delete()
        app.update_status()
        eq_(app.status, amo.STATUS_REJECTED)

    def test_one_version_pending(self):
        app = amo.tests.app_factory(status=amo.STATUS_REJECTED,
                                    file_kw=dict(status=amo.STATUS_DISABLED))
        amo.tests.version_factory(addon=app,
                                  file_kw=dict(status=amo.STATUS_PENDING))
        app.update_status()
        eq_(app.status, amo.STATUS_PENDING)

    def test_one_version_public(self):
        app = amo.tests.app_factory(status=amo.STATUS_PUBLIC)
        amo.tests.version_factory(addon=app,
                                  file_kw=dict(status=amo.STATUS_DISABLED))
        app.update_status()
        eq_(app.status, amo.STATUS_PUBLIC)

    def test_blocklisted(self):
        app = amo.tests.app_factory(status=amo.STATUS_BLOCKED)
        app.current_version.delete()
        app.update_status()
        eq_(app.status, amo.STATUS_BLOCKED)


class TestInstalled(amo.tests.TestCase):

    def setUp(self):
        user = UserProfile.objects.create(email='f@f.com')
        app = Addon.objects.create(type=amo.ADDON_WEBAPP)
        self.m = functools.partial(Installed.objects.safer_get_or_create,
                                   user=user, addon=app)

    def test_install_type(self):
        assert self.m(install_type=apps.INSTALL_TYPE_USER)[1]
        assert not self.m(install_type=apps.INSTALL_TYPE_USER)[1]
        assert self.m(install_type=apps.INSTALL_TYPE_REVIEWER)[1]


class TestAppFeatures(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.app = Addon.objects.get(pk=337141)
        self.flags = ('APPS', 'GEOLOCATION', 'PAY', 'SMS')
        self.expected = [u'App Management API', u'Geolocation', u'Web Payment',
                         u'WebSMS']
        self.create_switch('buchets')

    def _flag(self):
        """Flag app with a handful of feature flags for testing."""
        self.app.current_version.features.update(
            **dict(('has_%s' % f.lower(), True) for f in self.flags))

    def _check(self, obj=None):
        if not obj:
            obj = self.app.current_version.features

        for feature in APP_FEATURES:
            field = 'has_%s' % feature.lower()
            value = feature in self.flags
            if isinstance(obj, dict):
                eq_(obj[field], value,
                    u'Unexpected value for field: %s' % field)
            else:
                eq_(getattr(obj, field), value,
                    u'Unexpected value for field: %s' % field)

    def to_unicode(self, items):
        """
        Force unicode evaluation of lazy items in the passed list, for set
        comparison to a list of already-evaluated unicode strings.
        """
        return [unicode(i) for i in items]

    def test_features(self):
        self._flag()
        self._check()

    def test_no_features(self):
        eq_(self.app.current_version.features.to_list(), [])

    def test_signature_parity(self):
        # Test flags -> signature -> flags works as expected.
        self._flag()
        signature = self.app.current_version.features.to_signature()
        eq_(signature.count('.'), 2, 'Unexpected signature format')

        af = AppFeatures(version=self.app.current_version)
        af.set_flags(signature)
        self._check(af)

    def test_to_dict(self):
        self._flag()
        self._check(self.app.current_version.features.to_dict())

    def test_to_list(self):
        self._flag()
        to_list = self.app.current_version.features.to_list()
        self.assertSetEqual(self.to_unicode(to_list), self.expected)

    @mock.patch.dict('mkt.webapps.models.APP_FEATURES',
                     APPS={'name': _(u'H\xe9llo')})
    def test_to_list_nonascii(self):
        self.expected[0] = u'H\xe9llo'
        self._flag()
        to_list = self.app.current_version.features.to_list()
        self.assertSetEqual(self.to_unicode(to_list), self.expected)

    def test_bad_data(self):
        af = AppFeatures(version=self.app.current_version)
        af.set_flags('foo')
        af.set_flags('<script>')


class TestWebappIndexer(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)

    def test_mapping_type_name(self):
        eq_(WebappIndexer.get_mapping_type_name(), 'webapp')

    def test_index(self):
        with self.settings(ES_INDEXES={'webapp': 'apps'}):
            eq_(WebappIndexer.get_index(), 'apps')

    def test_model(self):
        eq_(WebappIndexer.get_model(), Webapp)

    def test_mapping(self):
        mapping = WebappIndexer.get_mapping()
        eq_(mapping.keys(), ['webapp'])
        eq_(mapping['webapp']['_all'], {'enabled': False})
        eq_(mapping['webapp']['_boost'], {'name': '_boost', 'null_value': 1.0})

    def test_mapping_properties(self):
        # Spot check a few of the key properties.
        mapping = WebappIndexer.get_mapping()
        keys = mapping['webapp']['properties'].keys()
        for k in ('id', 'app_slug', 'category', 'default_locale',
                  'description', 'device', 'features', 'name', 'status'):
            ok_(k in keys, 'Key %s not found in mapping properties' % k)

    def _get_doc(self):
        qs = Webapp.indexing_transformer(
            Webapp.uncached.filter(id__in=[self.app.pk]))
        obj = qs[0]
        return obj, WebappIndexer.extract_document(obj.pk, obj)

    def test_extract(self):
        obj, doc = self._get_doc()
        eq_(doc['id'], obj.id)
        eq_(doc['app_slug'], obj.app_slug)
        eq_(doc['category'], [])
        eq_(doc['default_locale'], obj.default_locale)
        eq_(doc['description'], list(
            set(s for _, s in obj.translations[obj.description_id])))
        eq_(doc['device'], [])
        eq_(doc['name'], list(
            set(s for _, s in obj.translations[obj.name_id])))
        eq_(doc['status'], obj.status)

    def test_extract_category(self):
        cat = Category.objects.create(name='c', type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=self.app, category=cat)

        obj, doc = self._get_doc()
        eq_(doc['category'], [cat.id])

    def test_extract_device(self):
        device = DEVICE_TYPES.keys()[0]
        AddonDeviceType.objects.create(addon=self.app, device_type=device)

        obj, doc = self._get_doc()
        eq_(doc['device'], [device])

    def test_extract_features(self):
        enabled = ('has_apps', 'has_sms', 'has_geolocation')
        self.app.current_version.features.update(
            **dict((k, True) for k in enabled))
        obj, doc = self._get_doc()
        for k, v in doc['features'].iteritems():
            eq_(v, k in enabled)

    def test_extract_regions(self):
        self.app.addonexcludedregion.create(region=mkt.regions.BR.id)
        self.app.addonexcludedregion.create(region=mkt.regions.UK.id)
        obj, doc = self._get_doc()
        self.assertSetEqual(doc['region_exclusions'],
                            set([mkt.regions.BR.id, mkt.regions.UK.id]))

    def test_extract_supported_locales(self):
        locales = 'en-US,es,pt-BR'
        self.app.current_version.update(supported_locales=locales)
        obj, doc = self._get_doc()
        self.assertSetEqual(doc['supported_locales'], set(locales.split(',')))


class TestManifestUpload(BaseUploadTest, amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    @mock.patch('mkt.webapps.models.parse_addon')
    def test_manifest_updated_developer_name(self, parse_addon):
        parse_addon.return_value = {
            'version': '4.0',
            'developer_name': u'Méâ'
        }
        # Note: we need a valid FileUpload instance, but in the end we are not
        # using its contents since we are mocking parse_addon().
        path = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                               'addons', 'mozball.webapp')
        upload = self.get_upload(abspath=path, is_webapp=True)
        app = Addon.objects.get(pk=337141)
        app.manifest_updated('', upload)
        version = app.current_version.reload()
        eq_(version.version, '4.0')
        eq_(version.developer_name, u'Méâ')

    @mock.patch('mkt.webapps.models.parse_addon')
    def test_manifest_updated_long_developer_name(self, parse_addon):
        truncated_developer_name = u'é' * 255
        long_developer_name = truncated_developer_name + u'ßßßß'
        parse_addon.return_value = {
            'version': '4.1',
            'developer_name': long_developer_name,
        }
        # Note: we need a valid FileUpload instance, but in the end we are not
        # using its contents since we are mocking parse_addon().
        path = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                               'addons', 'mozball.webapp')
        upload = self.get_upload(abspath=path, is_webapp=True)
        app = Addon.objects.get(pk=337141)
        app.manifest_updated('', upload)
        version = app.current_version.reload()
        eq_(version.version, '4.1')
        eq_(version.developer_name, truncated_developer_name)
