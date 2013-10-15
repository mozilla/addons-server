import json

from django.conf import settings

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from editors.models import RereviewQueue
from users.models import UserProfile


class TestGenerateError(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        metlog = settings.METLOG
        METLOG_CONF = {
            'logger': 'zamboni',
            'plugins': {'cef': ('metlog_cef.cef_plugin:config_plugin',
                                {'override': True})},
            'sender': {'class': 'metlog.senders.DebugCaptureSender'},
        }
        from metlog.config import client_from_dict_config
        self.metlog = client_from_dict_config(METLOG_CONF, metlog)
        self.metlog.sender.msgs.clear()

    def test_metlog_statsd(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'metlog_statsd'})

        eq_(len(self.metlog.sender.msgs), 1)
        msg = json.loads(self.metlog.sender.msgs[0])

        eq_(msg['severity'], 6)
        eq_(msg['logger'], 'zamboni')
        eq_(msg['payload'], '1')
        eq_(msg['type'], 'counter')
        eq_(msg['fields']['rate'], 1.0)
        eq_(msg['fields']['name'], 'z.zadmin')

    def test_metlog_json(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'metlog_json'})

        eq_(len(self.metlog.sender.msgs), 1)
        msg = json.loads(self.metlog.sender.msgs[0])

        eq_(msg['type'], 'metlog_json')
        eq_(msg['logger'], 'zamboni')
        eq_(msg['fields']['foo'], 'bar')
        eq_(msg['fields']['secret'], 42)

    def test_metlog_cef(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'metlog_cef'})

        eq_(len(self.metlog.sender.msgs), 1)
        msg = json.loads(self.metlog.sender.msgs[0])

        eq_(msg['type'], 'cef')
        eq_(msg['logger'], 'zamboni')

    def test_metlog_sentry(self):
        self.url = reverse('zadmin.generate-error')
        self.client.post(self.url,
                         {'error': 'metlog_sentry'})

        msgs = [json.loads(m) for m in self.metlog.sender.msgs]
        eq_(len(msgs), 1)
        msg = msgs[0]

        eq_(msg['type'], 'sentry')


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
        eq_(rows.find('a').attr('href'), '337141/')


class TestManifestRevalidation(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube', 'base/users']

    def setUp(self):
        self.url = reverse('zadmin.manifest_revalidation')

    def _test_revalidation(self):
        current_count = RereviewQueue.objects.count()
        response = self.client.post(self.url)
        eq_(response.status_code, 200)
        self.assertTrue('Manifest revalidation queued' in response.content)
        eq_(RereviewQueue.objects.count(), current_count + 1)

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
