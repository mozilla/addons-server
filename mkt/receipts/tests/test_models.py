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
            absolutify(reverse('receipt.verify', args=[ins.addon.app_slug])))
        return receipt

    def test_receipt_data_developer(self):
        user = UserProfile.objects.get(pk=5497308)
        ins = self.create_install(user, self.webapp)
        receipt = self.for_user(ins, 'developer')
        assert receipt['exp'] > (calendar.timegm(time.gmtime()) +
                                 settings.WEBAPPS_RECEIPT_EXPIRY_SECONDS -
                                 TEST_LEEWAY)

    def test_receipt_data_reviewer(self):
        user = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.webapp, user=user)
        ins = self.create_install(user, self.webapp)
        receipt = self.for_user(ins, 'reviewer')
        assert receipt['exp'] > (calendar.timegm(time.gmtime()) +
                                 (60 * 60 * 24) - TEST_LEEWAY)

    @mock.patch.object(settings, 'SITE_URL', 'https://foo.com')
    def test_receipt_packaged(self):
        webapp = addon_factory(type=amo.ADDON_WEBAPP, is_packaged=True)
        user = UserProfile.objects.get(pk=5497308)
        ins = self.create_install(user, webapp)
        receipt = self.for_user(ins, 'developer')
        eq_(receipt['product']['url'], settings.SITE_URL)

    @mock.patch.object(settings, 'SIGNING_SERVER_ACTIVE', True)
    @mock.patch('mkt.receipts.utils.sign')
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
