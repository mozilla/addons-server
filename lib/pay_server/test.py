import datetime
import json

from django.conf import settings

from mock import patch
from nose.tools import eq_
import test_utils

from users.models import UserProfile
from lib.pay_server import client, model_to_uid, ZamboniEncoder


@patch.object(settings, 'SECLUSION_HOSTS', ('http://localhost'))
@patch.object(settings, 'DOMAIN', 'testy')
class TestUtils(test_utils.TestCase):

    def setUp(self):
        self.user = UserProfile.objects.create()

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
