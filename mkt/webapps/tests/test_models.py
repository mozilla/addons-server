from datetime import datetime, timedelta
import json
import unittest

import test_utils
import mock
from nose.tools import eq_, raises
import waffle

from django.conf import settings

import amo
from addons.models import Addon, BlacklistedSlug
from mkt.developers.tests.test_views import BaseWebAppTest
from files.models import File
from users.models import UserProfile
from versions.models import Version
from mkt.webapps.models import Installed, Webapp, get_key


class TestWebapp(test_utils.TestCase):

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

    def test_get_origin(self):
        url = 'http://www.xx.com:4000/randompath/manifest.webapp'
        webapp = Webapp(manifest_url=url)
        eq_(webapp.origin, 'http://www.xx.com:4000')

    def test_reviewed(self):
        assert not Webapp().is_unreviewed()

    def can_be_purchased(self):
        assert Webapp(premium_type=True).can_be_purchased()
        assert not Webapp(premium_type=False).can_be_purchased()

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

    def test_delete_app_domain(self):
        waffle.models.Switch.objects.create(name='soft_delete', active=True)
        # When an app is deleted its slugs and domain should get relinquished.
        webapp = Webapp.objects.create(slug='ballin', app_slug='app-ballin',
                                       app_domain='http://omg.org/yes',
                                       status=amo.STATUS_PENDING)
        webapp.delete()

        post_mortem = Addon.with_deleted.filter(id=webapp.id)
        eq_(post_mortem.count(), 1)
        for attr in ['slug', 'app_slug', 'app_domain']:
            eq_(getattr(post_mortem[0], attr), None)


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
        self.listed_eq = (lambda f=[]: eq_(list(Webapp.objects.listed()), f))

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

    def test_no_receipt(self):
        self.webapp.update(type=amo.ADDON_EXTENSION)
        ap = Installed.objects.create(user=self.user, addon=self.webapp)
        eq_(ap.receipt, '')

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
        assert ins.receipt.startswith('eyJhbGciOiAiUlM1MTIiLCA'), ins.receipt

    def test_get_receipt(self):
        ins = self.create_install(self.user, self.webapp)
        assert self.webapp.get_receipt(self.user), ins

    def test_no_receipt_second_try(self):
        assert not self.webapp.get_receipt(self.user)

    def test_receipt_different(self):
        ins = self.create_install(self.user, self.webapp)
        ins_other = self.create_install(self.other_user, self.webapp)
        assert ins.receipt != ins_other.receipt

    def test_addon_premium(self):
        for type_ in amo.ADDON_PREMIUMS:
            self.webapp.update(premium_type=type_)
            self.create_install(self.user, self.webapp)
            assert self.webapp.get_receipt(self.user)

    def test_addon_free(self):
        for type_ in amo.ADDON_FREES:
            self.webapp.update(premium_type=amo.ADDON_FREE)
            self.create_install(self.user, self.webapp)
            assert self.webapp.get_receipt(self.user)

    def test_install_has_email(self):
        install = self.create_install(self.user, self.webapp)
        eq_(install.email, u'regular@mozilla.com')

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
        assert ins.receipt
        product = encode.call_args[0][0]['product']
        eq_(product['url'], self.webapp.manifest_url[:-1])
        eq_(product['storedata'], 'id=%s' % int(ins.addon.pk))


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key() + '.foo')
class TestBrokenReceipt(amo.tests.TestCase):
    def test_get_key(self):
        self.assertRaises(IOError, get_key)
