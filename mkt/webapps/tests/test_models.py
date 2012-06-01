import calendar
from datetime import datetime, timedelta
import json
import time
import unittest

import test_utils
import mock
from nose import SkipTest
from nose.tools import eq_, raises
import waffle

from django.conf import settings

import amo
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from addons.models import (Addon, AddonDeviceType, AddonUser, BlacklistedSlug,
                           DeviceType, Preview)
from mkt.developers.tests.test_views import BaseWebAppTest
from mkt.webapps.models import create_receipt, get_key, Installed, Webapp
from files.models import File
from users.models import UserProfile
from versions.models import Version

# We are testing times down to the second. To make sure we don't fail, this
# is the amount of leeway in seconds we are giving the timing tests.
TEST_LEEWAY = 100


class TestWebapp(test_utils.TestCase):

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
        eq_(webapp.get_url_path(), '/en-US/app/woo/')

    def test_get_stats_url(self):
        webapp = Webapp(app_slug='woo')

        eq_(webapp.get_stats_url(), '/en-US/app/woo/statistics/')

        eq_(
            webapp.get_stats_url(
                action='installs_series',
                args=['day', '20120101', '20120201', 'json']),
                '/en-US/app/woo/statistics/installs-day-20120101-20120201.json'
        )

    def test_get_origin(self):
        url = 'http://www.xx.com:4000/randompath/manifest.webapp'
        webapp = Webapp(manifest_url=url)
        eq_(webapp.origin, 'http://www.xx.com:4000')

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


class TestWebappManager(test_utils.TestCase):

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
        w = Webapp.objects.create(status=amo.STATUS_PUBLIC)
        w._current_version = Version.objects.create(addon=w)
        w.save()
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


class TestManifest(BaseWebAppTest):

    def test_get_manifest_json(self):
        webapp = self.post_addon()
        assert webapp.current_version
        assert webapp.current_version.has_files
        with open(self.manifest, 'r') as mf:
            manifest_json = json.load(mf)
            eq_(webapp.get_manifest_json(), manifest_json)


class TestDomainFromURL(unittest.TestCase):

    def test_simple(self):
        eq_(Webapp.domain_from_url('http://mozilla.com/'), 'mozilla.com')

    def test_long_path(self):
        eq_(Webapp.domain_from_url('http://mozilla.com/super/rad.webapp'),
            'mozilla.com')

    def test_normalize_www(self):
        eq_(Webapp.domain_from_url('http://www.mozilla.com/super/rad.webapp'),
            'mozilla.com')

    def test_with_port(self):
        eq_(Webapp.domain_from_url('http://mozilla.com:9000/'), 'mozilla.com')

    def test_subdomains(self):
        eq_(Webapp.domain_from_url('http://apps.mozilla.com/'),
            'apps.mozilla.com')

    def test_https(self):
        eq_(Webapp.domain_from_url('https://mozilla.com/'), 'mozilla.com')

    @raises(ValueError)
    def test_none(self):
        Webapp.domain_from_url(None)

    @raises(ValueError)
    def test_empty(self):
        Webapp.domain_from_url('')


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestReceipt(amo.tests.TestCase):
    fixtures = ['base/users.json']

    def setUp(self):
        self.webapp = Webapp.objects.create(type=amo.ADDON_WEBAPP)
        self.user = UserProfile.objects.get(pk=999)
        self.other_user = UserProfile.objects.exclude(pk=999)[0]

    def create_install(self, user, webapp):
        webapp.update(type=amo.ADDON_WEBAPP,
                      manifest_url='http://somesite.com/')
        return Installed.objects.safer_get_or_create(user=user,
                                                     addon=webapp)[0]

    def test_get_or_create(self):
        install = self.create_install(self.user, self.webapp)
        eq_(install, self.create_install(self.user, self.webapp))

    def test_has_installed(self):
        assert not self.webapp.has_installed(self.user)
        self.create_install(self.user, self.webapp)
        assert self.webapp.has_installed(self.user)

    def test_receipt(self):
        ins = self.create_install(self.user, self.webapp)
        assert create_receipt(ins.pk).startswith('eyJhbGciOiAiUlM1MTIiLCA')

    def test_receipt_different(self):
        ins = self.create_install(self.user, self.webapp)
        ins_other = self.create_install(self.other_user, self.webapp)
        assert create_receipt(ins.pk) != create_receipt(ins_other.pk)

    def test_addon_premium(self):
        for type_ in amo.ADDON_PREMIUMS:
            self.webapp.update(premium_type=type_)
            ins = self.create_install(self.user, self.webapp)
            assert create_receipt(ins.pk)

    def test_addon_free(self):
        for type_ in amo.ADDON_FREES:
            self.webapp.update(premium_type=amo.ADDON_FREE)
            ins = self.create_install(self.user, self.webapp)
            assert create_receipt(ins.pk)

    def test_install_has_uuid(self):
        install = self.create_install(self.user, self.webapp)
        assert install.uuid.startswith(str(install.pk))

    def test_install_not_premium(self):
        for type_ in amo.ADDON_FREES:
            self.webapp.update(premium_type=type_)
            Installed.objects.all().delete()
            install = self.create_install(self.user,
                            Webapp.objects.get(pk=self.webapp.pk))
            eq_(install.premium_type, type_)

    def test_install_premium(self):
        for type_ in amo.ADDON_PREMIUMS:
            self.webapp.update(premium_type=type_)
            Installed.objects.all().delete()
            install = self.create_install(self.user, self.webapp)
            eq_(install.premium_type, type_)

    @mock.patch('jwt.encode')
    def test_receipt_data(self, encode):
        encode.return_value = 'tmp-to-keep-memoize-happy'
        ins = self.create_install(self.user, self.webapp)
        create_receipt(ins.pk)
        receipt = encode.call_args[0][0]
        eq_(receipt['product']['url'], self.webapp.manifest_url[:-1])
        eq_(receipt['product']['storedata'], 'id=%s' % int(ins.addon.pk))
        assert receipt['exp'] > (calendar.timegm(time.gmtime()) +
                                 settings.WEBAPPS_RECEIPT_EXPIRY_SECONDS -
                                 TEST_LEEWAY)
        eq_(receipt['reissue'], self.webapp.get_purchase_url('reissue'))

    def test_receipt_not_reviewer(self):
        ins = self.create_install(self.user, self.webapp)
        self.assertRaises(ValueError,
                          create_receipt, ins.pk, flavour='reviewer')

    def test_receipt_other(self):
        ins = self.create_install(self.user, self.webapp)
        self.assertRaises(AssertionError,
                          create_receipt, ins.pk, flavour='wat')

    @mock.patch('jwt.encode')
    def for_user(self, ins, flavour, encode):
        encode.return_value = 'tmp-to-keep-memoize-happy'
        create_receipt(ins.pk, flavour=flavour)
        receipt = encode.call_args[0][0]
        eq_(receipt['product']['type'], flavour)
        eq_(receipt['verify'],
            absolutify(reverse('reviewers.apps.receipt',
                               args=[self.webapp.app_slug])))
        assert receipt['exp'] > (calendar.timegm(time.gmtime()) +
                                 (60 * 60 * 24) - TEST_LEEWAY)

    def test_receipt_data_author(self):
        user = UserProfile.objects.get(pk=5497308)
        ins = self.create_install(user, self.webapp)
        self.for_user(ins, 'author')

    def test_receipt_data_reviewer(self):
        user = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.webapp, user=user)
        ins = self.create_install(user, self.webapp)
        self.for_user(ins, 'reviewer')

    @mock.patch.object(settings, 'SIGNING_SERVER_ACTIVE', True)
    @mock.patch('mkt.webapps.models.sign')
    def test_receipt_signer(self, sign):
        sign.return_value = 'something-cunning'
        ins = self.create_install(self.user, self.webapp)
        eq_(create_receipt(ins.pk), 'something-cunning')
        #TODO: more goes here.


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key() + '.foo')
class TestBrokenReceipt(amo.tests.TestCase):
    def test_get_key(self):
        self.assertRaises(IOError, get_key)


class TestTransformer(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube']

    @mock.patch('mkt.webapps.models.Addon.transformer')
    def test_addon_transformer_called(self, transformer):
        transformer.return_value = {}
        list(Webapp.objects.all())
        assert transformer.called

    def test_device_types(self):
        dtype = DeviceType.objects.create(name='fligphone', class_name='phone')
        AddonDeviceType.objects.create(addon_id=337141, device_type=dtype)
        webapps = list(Webapp.objects.filter(id=337141))

        with self.assertNumQueries(0):
            for webapp in webapps:
                assert webapp._device_types
                eq_(webapp.device_types, [dtype])

    def test_device_type_cache(self):
        webapp = Webapp.objects.get(id=337141)
        webapp._device_types = []
        with self.assertNumQueries(0):
            eq_(webapp.device_types, [])
