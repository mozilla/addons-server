import json
import os
import unittest

import test_utils
import mock
from nose.tools import eq_, raises

from django.conf import settings

import amo
from addons.models import Addon, BlacklistedSlug
from devhub.tests.test_views import BaseWebAppTest
from users.models import UserProfile
from versions.models import Version
from webapps.models import Installed, Webapp, get_key, decode_receipt


key = os.path.join(os.path.dirname(__file__), 'sample.key')


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
        eq_(webapp.get_url_path(), '/en-US/apps/app/woo/')

    def test_get_url_path_more(self):
        webapp = Webapp(app_slug='woo')
        eq_(webapp.get_url_path(more=True), '/en-US/apps/app/woo/more')

    def test_get_origin(self):
        url = 'http://www.xx.com:4000/randompath/manifest.webapp'
        webapp = Webapp(manifest_url=url)
        eq_(webapp.origin, 'http://www.xx.com:4000')

    def test_reviewed(self):
        assert not Webapp().is_unreviewed()

    def can_be_purchased(self):
        assert Webapp(premium_type=True).can_be_purchased()
        assert not Webapp(premium_type=False).can_be_purchased()


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

    @mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY', 'rubbish')
    def test_get_key(self):
        self.assertRaises(IOError, get_key)

    @mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY', key)
    def create_install(self, user, webapp):
        webapp.update(type=amo.ADDON_WEBAPP,
                      manifest_url='http://somesite.com/')
        return webapp.get_or_create_install(user)

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
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        self.create_install(self.user, self.webapp)
        assert self.webapp.get_receipt(self.user)

    def test_addon_free(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        self.create_install(self.user, self.webapp)
        assert self.webapp.get_receipt(self.user)

    def test_crack_receipt(self):
        receipt = self.create_install(self.user, self.webapp).receipt
        result = decode_receipt(receipt)
        eq_(result['typ'], u'purchase-receipt')

    def test_install_has_email(self):
        install = self.create_install(self.user, self.webapp)
        eq_(install.email, u'regular@mozilla.com')

    def test_install_not_premium(self):
        install = self.create_install(self.user, self.webapp)
        eq_(install.premium_type, amo.ADDON_FREE)

    def test_install_premium(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        install = self.create_install(self.user, self.webapp)
        eq_(install.premium_type, amo.ADDON_PREMIUM)
