import json

from django.conf import settings

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from editors.models import RereviewQueue
from users.models import UserProfile

from mkt.site.fixtures import fixture

class TestGenerateError(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        heka = settings.HEKA
        HEKA_CONF = {
            'logger': 'zamboni',
            'plugins': {'cef': ('heka_cef.cef_plugin:config_plugin',
                                {'override': True})},
            'stream': {'class': 'heka.streams.DebugCaptureStream'},
            'encoder': 'heka.encoders.NullEncoder',
        }
        from heka.config import client_from_dict_config
        self.heka = client_from_dict_config(HEKA_CONF, heka)
        self.heka.stream.msgs.clear()

    def test_heka_statsd(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'heka_statsd'})

        eq_(len(self.heka.stream.msgs), 1)
        msg = self.heka.stream.msgs[0]

        eq_(msg.severity, 6)
        eq_(msg.logger, 'zamboni')
        eq_(msg.payload, '1')
        eq_(msg.type, 'counter')

        rate = [f for f in msg.fields if f.name == 'rate'][0]
        name = [f for f in msg.fields if f.name == 'name'][0]

        eq_(rate.value_double, [1.0])
        eq_(name.value_string, ['z.zadmin'])

    def test_heka_json(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'heka_json'})

        eq_(len(self.heka.stream.msgs), 1)
        msg = self.heka.stream.msgs[0]

        eq_(msg.type, 'heka_json')
        eq_(msg.logger, 'zamboni')

        foo = [f for f in msg.fields if f.name == 'foo'][0]
        secret = [f for f in msg.fields if f.name == 'secret'][0]

        eq_(foo.value_string, ['bar'])
        eq_(secret.value_integer, [42])

    def test_heka_cef(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'heka_cef'})

        eq_(len(self.heka.stream.msgs), 1)

        msg = self.heka.stream.msgs[0]

        eq_(msg.type, 'cef')
        eq_(msg.logger, 'zamboni')

    def test_heka_sentry(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'heka_sentry'})

        msgs = self.heka.stream.msgs
        eq_(len(msgs), 1)
        msg = msgs[0]

        eq_(msg.type, 'sentry')


class TestAddonAdmin(amo.tests.TestCase):
    fixtures = ['base/users', 'base/337141-steamcube', 'base/addon_3615']

    def setUp(self):
        self.login('admin@mozilla.com')
        self.url = reverse('admin:addons_addon_changelist')

    def test_no_webapps(self):
        res = self.client.get(self.url, follow=True)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        rows = doc('#result_list tbody tr')
        eq_(rows.length, 1)
        eq_(rows.find('a').attr('href'), '/admin/models/addons/addon/337141/')


class TestManifestRevalidation(amo.tests.TestCase):
    fixtures = fixture('webapp_337141') + ['base/users']

    def setUp(self):
        self.url = reverse('zadmin.manifest_revalidation')

    def _test_revalidation(self):
        current_count = RereviewQueue.objects.count()
        response = self.client.post(self.url)
        eq_(response.status_code, 200)
        self.assertTrue('Manifest revalidation queued' in response.content)
        eq_(len(RereviewQueue.objects.all()), current_count + 1)

    def test_revalidation_by_reviewers(self):
        # Sr Reviewers users should be able to use the feature.
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'ReviewerAdminTools:View')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

        self._test_revalidation()

    def test_revalidation_by_admin(self):
        # Admin users should be able to use the feature.
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self._test_revalidation()

    def test_unpriviliged_user(self):
        # Unprivileged user should not be able to reach the feature.
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        eq_(self.client.post(self.url).status_code, 403)
