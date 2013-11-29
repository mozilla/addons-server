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
    """
    This class patch your test case so that any attempt to call solitude
    from zamboni through these classes will use the mock.

    Use this class as mixin on any tests that alter payment accounts.

    If you override setUp or tearDown be sure to call super.
    """

    def setUp(self, *args, **kw):
        super(Patcher, self).setUp(*args, **kw)
        client_patcher = patch('mkt.developers.models.client',
                               name='test_providers.Patcher.client_patcher')
        self.patched_client = client_patcher.start()
        self.patched_client.patcher = client_patcher

        bango_patcher = patch('mkt.developers.providers.Bango.client',
                              name='test_providers.Patcher.bango_patcher')
        self.bango_patcher = bango_patcher.start()
        self.bango_patcher.patcher = bango_patcher

        ref_patcher = patch('mkt.developers.providers.Reference.client',
                            name='test_providers.Patcher.ref_patcher')
        self.ref_patcher = ref_patcher.start()
        self.ref_patcher.patcher = ref_patcher

    def tearDown(self, *args, **kw):
        super(Patcher, self).tearDown(*args, **kw)
        self.patched_client.patcher.stop()
        self.bango_patcher.patcher.stop()
        self.ref_patcher.patcher.stop()


class TestSetup(TestCase):

    @raises(ImproperlyConfigured)
    def test_multiple(self):
        with self.settings(PAYMENT_PROVIDERS=['foo', 'bar']):
            get_provider()


class TestReference(Patcher, TestCase):
    fixtures = fixture('user_999')

    def setUp(self, *args, **kw):
        super(TestReference, self).setUp(*args, **kw)
        self.user = UserProfile.objects.get(pk=999)
        self.ref = Reference()

    def test_setup_seller(self):
        self.ref.setup_seller(self.user)
        ok_(SolitudeSeller.objects.filter(user=self.user).exists())

    def test_account_create(self):
        data = {'account_name': 'account', 'name': 'f', 'email': 'a@a.com'}
        res = self.ref.account_create(self.user, data)
        acct = PaymentAccount.objects.get(user=self.user)
        eq_(acct.provider, PROVIDER_REFERENCE)
        eq_(res.pk, acct.pk)

    def make_account(self):
        seller = SolitudeSeller.objects.create(user=self.user)
        return PaymentAccount.objects.create(user=self.user,
                                             solitude_seller=seller)

    def test_terms_retrieve(self):
        account = self.make_account()
        self.ref.terms_retrieve(account)
        assert self.ref_patcher.terms.called

    def test_terms_update(self):
        account = self.make_account()
        self.ref.terms_update(account)
        eq_(account.reload().agreed_tos, True)
        assert self.ref_patcher.sellers.called

    def test_account_retrieve(self):
        account = self.make_account()
        self.ref.account_retrieve(account)
        assert self.ref_patcher.sellers.called

    def test_account_update(self):
        account = self.make_account()
        self.ref.account_update(account, {'account_name': 'foo'})
        eq_(account.reload().name, 'foo')
        assert self.ref_patcher.sellers.called
