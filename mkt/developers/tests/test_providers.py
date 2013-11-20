from django.core.exceptions import ImproperlyConfigured

from mock import patch
from nose.tools import eq_, ok_, raises

from test_utils import TestCase

from constants.payments import PROVIDER_REFERENCE
from mkt.developers.models import PaymentAccount, SolitudeSeller
from mkt.developers.providers import get_provider, Reference
from mkt.site.fixtures import fixture

from users.models import UserProfile


class Patcher(object):

    def setUp(self, *args, **kw):
        super(Patcher, self).setUp(*args, **kw)
        client_patcher = patch('mkt.developers.models.client')
        self.patched_client = client_patcher.start()
        self.patched_client.patcher = client_patcher

        provider_patcher = patch('mkt.developers.providers.Bango.client')
        self.patched_provider = provider_patcher.start()
        self.patched_provider.patcher = provider_patcher

    def tearDown(self, *args, **kw):
        super(Patcher, self).tearDown(*args, **kw)
        self.patched_client.patcher.stop()
        self.patched_provider.patcher.stop()


class TestSetup(TestCase):

    @raises(ImproperlyConfigured)
    def test_multiple(self):
        with self.settings(PAYMENT_PROVIDERS=['foo', 'bar']):
            get_provider()


class TestReference(TestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        self.user = UserProfile.objects.get(pk=999)
        self.ref = Reference()

    @patch('mkt.developers.models.client')
    def test_setup_seller(self, client):
        self.ref.setup_seller(self.user)
        ok_(SolitudeSeller.objects.filter(user=self.user).exists())

    @patch('mkt.developers.models.client')
    @patch.object(Reference, 'client')
    def test_account_create(self, providers, models):
        data = {'account_name': 'account', 'name': 'f', 'email': 'a@a.com'}
        res = self.ref.account_create(self.user, data)
        acct = PaymentAccount.objects.get(user=self.user)
        eq_(acct.provider, PROVIDER_REFERENCE)
        eq_(res.pk, acct.pk)
