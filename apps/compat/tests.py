import json

from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from compat.models import CompatReport


# This is the structure sent to /compatibility/incoming from the ACR.
incoming_data = {
    'appBuild': '20110429030623',
    'appGUID': '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}',
    'appVersion': '6.0a1',
    'clientOS': 'Intel Mac OS X 10.6',
    'comments': 'what the what',
    'guid': 'jid0-VsMuA0YYTKCjBh5F0pxHAudnEps@jetpack',
    'otherAddons': [['yslow@yahoo-inc.com', '2.1.0']],
    'version': '2.2',
    'worksProperly': False,
}


class TestIncoming(amo.tests.TestCase):

    def setUp(self):
        self.url = reverse('compat.incoming')
        self.data = dict(incoming_data)
        self.json = json.dumps(self.data)

    def test_success(self):
        count = CompatReport.objects.count()
        r = self.client.post(self.url, self.json,
                             content_type='application/json')
        eq_(r.status_code, 204)
        eq_(CompatReport.objects.count(), count + 1)

        cr = CompatReport.objects.order_by('-id')[0]
        eq_(cr.app_build, incoming_data['appBuild'])
        eq_(cr.app_guid, incoming_data['appGUID'])
        eq_(cr.works_properly, incoming_data['worksProperly'])
        eq_(cr.comments, incoming_data['comments'])
        eq_(cr.client_ip, '127.0.0.1')

        # Check that the other_addons field is stored as json.
        vals = CompatReport.objects.filter(id=cr.id).values('other_addons')
        eq_(vals[0]['other_addons'],
            json.dumps(incoming_data['otherAddons'], separators=(',', ':')))

    def test_bad_json(self):
        r = self.client.post(self.url, 'wuuu#$',
                             content_type='application/json')
        eq_(r.status_code, 400)

    def test_bad_field(self):
        self.data['save'] = 1
        js = json.dumps(self.data)
        r = self.client.post(self.url, js, content_type='application/json')
        eq_(r.status_code, 400)


class TestReporter(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def test_success(self):
        r = self.client.get(reverse('compat.reporter'))
        eq_(r.status_code, 200)

    def test_redirect(self):
        addon = Addon.objects.get(id=3615)
        CompatReport.objects.create(guid=addon.guid, app_guid=amo.FIREFOX.guid)
        url = reverse('compat.reporter')
        expected = reverse('compat.reporter_detail', args=[addon.guid])

        self.assertRedirects(self.client.get(url + '?guid=%s' % addon.id),
                                             expected)
        self.assertRedirects(self.client.get(url + '?guid=%s' % addon.slug),
                                             expected)
        self.assertRedirects(self.client.get(url + '?guid=%s' % addon.guid),
                                             expected)
        self.assertRedirects(
            self.client.get(url + '?guid=%s' % addon.guid[:5]), expected)
