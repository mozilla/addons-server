import datetime
import json

from django.conf import settings

from mock import patch
from nose.tools import eq_
import test_utils

from addons.models import Addon
from users.models import UserProfile
from lib.pay_server import client, model_to_uid, ZamboniEncoder


@patch.object(settings, 'SECLUSION_HOSTS', ('http://localhost'))
@patch.object(settings, 'DOMAIN', 'testy')
class TestUtils(test_utils.TestCase):

    def setUp(self):
        self.user = UserProfile.objects.create()
        self.addon = Addon.objects.create(type=1)

    def test_uid(self):
        eq_(model_to_uid(self.user), 'testy:users:%s' % self.user.pk)

    def test_encoder(self):
        today = datetime.date.today()
        res = json.loads(json.dumps({'uuid': self.user, 'date': today},
                                    cls=ZamboniEncoder))
        eq_(res['uuid'], 'testy:users:%s' % self.user.pk)
        eq_(res['date'], today.strftime('%Y-%m-%d'))

    @patch.object(client, 'get_buyer')
    @patch.object(client, 'post_buyer')
    def test_create(self, post_buyer, get_buyer):
        get_buyer.return_value = {'meta': {'total_count': 0}}
        client.create_buyer_if_missing(self.user)
        assert post_buyer.called

    @patch.object(client, 'get_buyer')
    @patch.object(client, 'post_buyer')
    def test_not_created(self, post_buyer, get_buyer):
        get_buyer.return_value = {'meta': {'total_count': 1}}
        client.create_buyer_if_missing(self.user)
        assert not post_buyer.called

    @patch.object(client, 'get_buyer')
    def test_create(self, get_buyer):
        get_buyer.return_value = {'meta': {'total_count': 1},
                                  'objects': [{'paypal': 'foo'}]}
        eq_(client.lookup_buyer_paypal(self.user), 'foo')

    @patch.object(client, 'get_buyer')
    def test_create_err(self, get_buyer):
        get_buyer.return_value = {'meta': {'total_count': 2}}
        with self.assertRaises(ValueError):
            client.lookup_buyer_paypal(self.user)

    @patch.object(client, 'get_seller')
    @patch.object(client, 'post_seller')
    def test_create(self, post_seller, get_seller):
        get_seller.return_value = {
                'meta': {'total_count': 1},
                'objects': [{'paypal': {'resource_pk': 1}}]
            }
        eq_(client.create_seller_paypal(self.addon), {'resource_pk': 1})

    @patch.object(client, 'get_seller')
    @patch.object(client, 'post_seller')
    @patch.object(client, 'post_seller_paypal')
    def test_no_paypal(self, post_seller_paypal, post_seller, get_seller):
        get_seller.return_value = {
                'meta': {'total_count': 1},
                'objects': [{'resource_uri': 1, 'paypal': None}]
            }
        post_seller_paypal.return_value = {'resource_pk': 1}
        eq_(client.create_seller_paypal(self.addon), {'resource_pk': 1})
        assert post_seller_paypal.called

    @patch.object(client, 'get_seller')
    @patch.object(client, 'post_seller')
    @patch.object(client, 'post_seller_paypal')
    def test_nothing(self, post_seller_paypal, post_seller, get_seller):
        get_seller.return_value = {
                'meta': {'total_count': 0},
            }
        post_seller_paypal.return_value = {'resource_pk': 1}
        eq_(client.create_seller_paypal(self.addon), {'resource_pk': 1})
        assert post_seller_paypal.called

    @patch.object(client, 'get_seller')
    def test_too_many(self, get_seller):
        get_seller.return_value = {
                'meta': {'total_count': 2},
            }
        with self.assertRaises(ValueError):
            client.create_seller_paypal(self.addon)
