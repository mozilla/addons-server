from datetime import datetime

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist

from mock import ANY, Mock, patch
from nose.tools import eq_, ok_, raises

from amo.tests import app_factory, TestCase
from constants.payments import PROVIDER_BANGO, PROVIDER_REFERENCE
from mkt.developers.models import PaymentAccount, SolitudeSeller
from mkt.developers.providers import Bango, get_provider, Reference
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
        # Once everything has moved over to the provider, this one
        # can be remoed.
        client_patcher = patch('mkt.developers.models.client',
                               name='test_providers.Patcher.client_patcher')
        self.patched_client = client_patcher.start()
        self.patched_client.patcher = client_patcher
        self.addCleanup(client_patcher.stop)

        bango_patcher = patch('mkt.developers.providers.Bango.client',
                              name='test_providers.Patcher.bango_patcher')
        self.bango_patcher = bango_patcher.start()
        self.bango_patcher.patcher = bango_patcher
        self.addCleanup(bango_patcher.stop)

        bango_p_patcher = patch(
                'mkt.developers.providers.Bango.client_provider',
                name='test_providers.Patcher.bango_p_patcher')
        self.bango_p_patcher = bango_p_patcher.start()
        self.bango_p_patcher.patcher = bango_p_patcher
        self.addCleanup(bango_p_patcher.stop)

        ref_patcher = patch('mkt.developers.providers.Reference.client',
                            name='test_providers.Patcher.ref_patcher')
        self.ref_patcher = ref_patcher.start()
        self.ref_patcher.patcher = ref_patcher
        self.addCleanup(ref_patcher.stop)

        generic_patcher = patch('mkt.developers.providers.Provider.generic',
                                name='test_providers.Patcher.generic_patcher')
        self.generic_patcher = generic_patcher.start()
        self.generic_patcher.patcher = generic_patcher
        self.addCleanup(generic_patcher.stop)


class TestSetup(TestCase):

    @raises(ImproperlyConfigured)
    def test_multiple(self):
        with self.settings(PAYMENT_PROVIDERS=['foo', 'bar']):
            get_provider()


class TestBango(Patcher, TestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        super(TestBango, self).setUp()
        self.user = UserProfile.objects.filter()[0]
        self.app = app_factory()
        self.make_premium(self.app)

        self.seller = SolitudeSeller.objects.create(
            resource_uri='sellerres', user=self.user
        )
        self.account = PaymentAccount.objects.create(
            solitude_seller=self.seller,
            user=self.user, name='paname', uri='acuri',
            inactive=False, seller_uri='selluri',
            account_id=123, provider=PROVIDER_BANGO
        )
        self.bango = Bango()

    def test_create(self):
        self.generic_patcher.product.get_object_or_404.return_value = {
            'resource_uri': 'gpuri'}
        self.bango_patcher.product.get_object_or_404.return_value = {
            'resource_uri': 'bpruri', 'bango_id': 'bango#', 'seller': 'selluri'
        }

        uri = self.bango.product_create(self.account, self.app)
        eq_(uri, 'bpruri')

    def test_create_new(self):
        self.bango_patcher.product.get_object_or_404.side_effect = (
            ObjectDoesNotExist)
        self.bango_p_patcher.product.post.return_value = {
            'resource_uri': '', 'bango_id': 1
        }
        self.bango.product_create(self.account, self.app)
        ok_('packageId' in
            self.bango_p_patcher.product.post.call_args[1]['data'])

    def test_terms_bleached(self):
        self.bango_patcher.sbi.agreement.get_object.return_value = {
            'text': '<script>foo</script><a>bar</a>'}
        eq_(self.bango.terms_retrieve(Mock())['text'],
            u'&lt;script&gt;foo&lt;/script&gt;<a>bar</a>')


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
                                             solitude_seller=seller,
                                             uri='/f/b/1')

    def test_terms_retrieve(self):
        account = self.make_account()
        self.ref.terms_retrieve(account)
        assert self.ref_patcher.terms.called

    def test_terms_bleached(self):
        account = self.make_account()
        account_mock = Mock()
        account_mock.get.return_value = {'text':
                                         '<script>foo</script><a>bar</a>'}
        self.ref_patcher.terms.return_value = account_mock
        eq_(self.ref.terms_retrieve(account)['text'],
            u'&lt;script&gt;foo&lt;/script&gt;<a>bar</a>')

    def test_terms_update(self):
        seller_mock = Mock()
        seller_mock.get.return_value = {
            'id': 1,
            'resource_uri': '/a/b/c',
            'resource_name': 'x',
            'initial_field': u'initial content',
        }
        seller_mock.put.return_value = {}
        self.ref_patcher.sellers.return_value = seller_mock
        account = self.make_account()
        self.ref.terms_update(account)
        eq_(account.reload().agreed_tos, True)
        assert self.ref_patcher.sellers.called
        seller_mock.get.assert_called_with()
        seller_mock.put.assert_called_with({
            'agreement': datetime.now().strftime('%Y-%m-%d'),
            'initial_field': u'initial content',
        })

    def test_account_retrieve(self):
        account = self.make_account()
        self.ref.account_retrieve(account)
        assert self.ref_patcher.sellers.called

    def test_account_update(self):
        account = self.make_account()
        self.ref.account_update(account, {'account_name': 'foo'})
        eq_(account.reload().name, 'foo')
        assert self.ref_patcher.sellers.called

    def test_product_create_exists(self):
        self.ref_patcher.products.get.return_value = [{'resource_uri': '/f'}]
        account = self.make_account()
        app = app_factory()
        self.ref.product_create(account, app)
        # Product should have been got from zippy, but not created by a post.
        assert self.ref_patcher.products.get.called

    @raises(ValueError)
    def test_product_mulitple(self):
        self.ref_patcher.products.get.return_value = [{}, {}]
        account = self.make_account()
        app = app_factory()
        self.ref.product_create(account, app)

    def test_product_create_not(self):
        self.generic_patcher.product.get_object_or_404.return_value = {
            'external_id': 'ext'}
        self.ref_patcher.products.get.return_value = []
        self.ref_patcher.products.post.return_value = {'resource_uri': '/f'}
        account = self.make_account()
        app = app_factory()
        self.ref.product_create(account, app)
        self.ref_patcher.products.get.assert_called_with(
            seller_id='1', external_id='ext')
        self.ref_patcher.products.post.assert_called_with(data={
            'seller_id': '1',
            'external_id': 'ext',
            'name': unicode(app.name),
            'uuid': ANY,
        })
