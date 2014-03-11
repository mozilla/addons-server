import calendar
import time

from django.conf import settings

import mock
from nose.tools import eq_

from addons.models import AddonUser
import amo
import amo.tests
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.tests import addon_factory
from mkt.receipts.utils import create_receipt, get_key
from mkt.webapps.models import Installed, Webapp
from users.models import UserProfile


# We are testing times down to the second. To make sure we don't fail, this
# is the amount of leeway in seconds we are giving the timing tests.
TEST_LEEWAY = 100


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestReceipt(amo.tests.TestCase):
    fixtures = ['base/users.json']

    def setUp(self):
        self.app = Webapp.objects.create(type=amo.ADDON_WEBAPP)
        self.app.update(manifest_url='http://f.c/')
        self.user = UserProfile.objects.get(pk=999)
        self.other_user = UserProfile.objects.exclude(pk=999)[0]

    def create_install(self, user, webapp):
        webapp.update(type=amo.ADDON_WEBAPP,
                      manifest_url='http://somesite.com/')
        return Installed.objects.safer_get_or_create(user=user,
                                                     addon=webapp)[0]

    def test_get_or_create(self):
        install = self.create_install(self.user, self.app)
        eq_(install, self.create_install(self.user, self.app))

    def test_has_installed(self):
        assert not self.app.has_installed(self.user)
        self.create_install(self.user, self.app)
        assert self.app.has_installed(self.user)

    def test_receipt(self):
        assert (create_receipt(self.app, self.user, 'some-uuid')
                .startswith('eyJhbGciOiAiUlM1MTIiLCA'))

    def test_receipt_different(self):
        assert (create_receipt(self.app, self.user, 'some-uuid')
                != create_receipt(self.app, self.other_user, 'other-uuid'))

    def test_addon_premium(self):
        for type_ in amo.ADDON_PREMIUMS:
            self.app.update(premium_type=type_)
            assert create_receipt(self.app, self.user, 'some-uuid')

    def test_install_has_uuid(self):
        install = self.create_install(self.user, self.app)
        assert install.uuid.startswith(str(install.pk))

    def test_install_not_premium(self):
        for type_ in amo.ADDON_FREES:
            self.app.update(premium_type=type_)
            Installed.objects.all().delete()
            install = self.create_install(self.user,
                                          Webapp.objects.get(pk=self.app.pk))
            eq_(install.premium_type, type_)

    def test_install_premium(self):
        for type_ in amo.ADDON_PREMIUMS:
            self.app.update(premium_type=type_)
            Installed.objects.all().delete()
            install = self.create_install(self.user, self.app)
            eq_(install.premium_type, type_)

    @mock.patch('jwt.encode')
    def test_receipt_data(self, encode):
        encode.return_value = 'tmp-to-keep-memoize-happy'
        create_receipt(self.app, self.user, 'some-uuid')
        receipt = encode.call_args[0][0]
        eq_(receipt['product']['url'], self.app.manifest_url[:-1])
        eq_(receipt['product']['storedata'], 'id=%s' % int(self.app.pk))
        assert receipt['exp'] > (calendar.timegm(time.gmtime()) +
                                 settings.WEBAPPS_RECEIPT_EXPIRY_SECONDS -
                                 TEST_LEEWAY)
        eq_(receipt['reissue'], absolutify(reverse('receipt.reissue')))

    def test_receipt_not_reviewer(self):
        with self.assertRaises(ValueError):
            create_receipt(self.app, self.user, 'some-uuid',
                           flavour='reviewer')

    def test_receipt_other(self):
        with self.assertRaises(AssertionError):
            create_receipt(self.app, self.user, 'some-uuid', flavour='wat')

    @mock.patch('jwt.encode')
    def for_user(self, app, user, flavour, encode):
        encode.return_value = 'tmp-to-keep-memoize-happy'
        create_receipt(app, user, 'some-uuid', flavour=flavour)
        receipt = encode.call_args[0][0]
        eq_(receipt['typ'], flavour + '-receipt')
        eq_(receipt['verify'],
            absolutify(reverse('receipt.verify', args=[app.guid])))
        return receipt

    def test_receipt_data_developer(self):
        user = UserProfile.objects.get(pk=5497308)
        receipt = self.for_user(self.app, user, 'developer')
        assert receipt['exp'] > (calendar.timegm(time.gmtime()) +
                                 (60 * 60 * 24) - TEST_LEEWAY)

    def test_receipt_data_reviewer(self):
        user = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.app, user=user)
        receipt = self.for_user(self.app, user, 'reviewer')
        assert receipt['exp'] > (calendar.timegm(time.gmtime()) +
                                 (60 * 60 * 24) - TEST_LEEWAY)

    def test_receipt_packaged(self):
        app = addon_factory(type=amo.ADDON_WEBAPP, is_packaged=True,
                            app_domain='app://foo.com')
        user = UserProfile.objects.get(pk=5497308)
        receipt = self.for_user(app, user, 'developer')
        eq_(receipt['product']['url'], 'app://foo.com')

    def test_receipt_packaged_no_origin(self):
        app = addon_factory(type=amo.ADDON_WEBAPP, is_packaged=True)
        user = UserProfile.objects.get(pk=5497308)
        receipt = self.for_user(app, user, 'developer')
        eq_(receipt['product']['url'], settings.SITE_URL)


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key() + '.foo')
class TestBrokenReceipt(amo.tests.TestCase):
    def test_get_key(self):
        self.assertRaises(IOError, get_key)
