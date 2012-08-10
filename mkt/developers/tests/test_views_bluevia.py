import json

from django.conf import settings

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from market.models import AddonPremium
from mkt.developers.models import AddonBlueViaConfig, BlueViaConfig
from users.models import UserProfile


class TestBlueVia(amo.tests.WebappTestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestBlueVia, self).setUp()
        self.url = self.app.get_dev_url('payments')
        self.client.login(username='admin@mozilla.com', password='password')
        self.user = UserProfile.objects.get(username='admin')
        AddonPremium.objects.create(addon=self.app)

    def test_get_bluevia_url(self):
        url = self.app.get_dev_url('get_bluevia_url')
        res = json.loads(self.client.get(url).content)
        eq_(res['error'], False)
        eq_(res['bluevia_url'].startswith(settings.BLUEVIA_URL), True)

    def test_bluevia_callback_register(self):
        url = self.app.get_dev_url('bluevia_callback')
        developer_id = 'abc123wootrofllolomgbbqznyandragons'
        res = self.client.post(url, data={'developerId': developer_id,
                                          'status': 'registered'})
        data = json.loads(res.content)
        eq_(data['error'], False)
        eq_(BlueViaConfig.objects.count(), 1)
        eq_(AddonBlueViaConfig.objects.count(), 1)
        eq_(AddonBlueViaConfig.objects.get(addon=self.app).bluevia_config
            .developer_id, developer_id)

    def bluevia_callback_test(self):
        url = self.app.get_dev_url('bluevia_callback')
        developer_id = 'abc123wootrofllolomgbbqznyandragons'
        res = self.client.post(url, data={'developerId': developer_id,
                                          'status': 'loggedin'})
        data = json.loads(res.content)
        eq_(data['error'], False)
        eq_(AddonBlueViaConfig.objects.count(), 1)
        eq_(AddonBlueViaConfig.objects.get(addon=self.app).bluevia_config
            .developer_id, developer_id)
        eq_(str(AddonBlueViaConfig.objects.get(addon=self.app).bluevia_config
            .created) in data['html'], True)

    def test_bluevia_callback_log_in(self):
        self.bluevia_callback_test()
        eq_(BlueViaConfig.objects.count(), 1)

    def create_bluevia_configs(self):
        bluevia_config = BlueViaConfig.objects.create(developer_id='old123',
            user=self.user)
        AddonBlueViaConfig.objects.create(addon=self.app,
            bluevia_config=bluevia_config)

    def test_bluevia_callback_existing(self):
        self.create_bluevia_configs()
        self.bluevia_callback_test()
        eq_(BlueViaConfig.objects.count(), 2)

    def test_bluevia_remove(self):
        self.create_bluevia_configs()

        url = self.app.get_dev_url('bluevia_remove')
        res = self.client.post(url)
        data = json.loads(res.content)
        eq_(data['error'], False)
        eq_(BlueViaConfig.objects.count(), 1)
        eq_(AddonBlueViaConfig.objects.count(), 0)

    def test_bluevia_remove_error(self):
        url = self.app.get_dev_url('bluevia_remove')
        res = self.client.post(url)
        data = json.loads(res.content)
        eq_(data['error'], True)

    def test_bluevia_payments_page(self):
        res = self.client.get(self.url)
        eq_(pq(res.content)('#bluevia').length, 0)

        self.create_bluevia_configs()

        res = self.client.get(self.url)
        eq_(pq(res.content)('#bluevia').length, 1)
