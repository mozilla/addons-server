import json

from nose.tools import eq_
from pyquery import PyQuery as pq

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


class TestIndex(amo.tests.TestCase):

    # TODO: Test valid version processing here.

    def test_no_version_redirect(self):
        res = self.client.get(reverse('compat.index'))
        self.assert3xx(res, reverse('compat.index',
                                    args=[amo.COMPAT[0]['main']]))


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


class TestReporterDetail(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.url = reverse('compat.reporter_detail', args=[self.addon.guid])
        self.reports = []

    def _generate(self):
        apps = [
            (amo.FIREFOX.guid, '10.0.1', True),      # 0
            (amo.FIREFOX.guid, '10.0a1', True),      # 1
            (amo.FIREFOX.guid, '10.0', False),       # 2
            (amo.FIREFOX.guid, '6.0.1', False),      # 3

            (amo.THUNDERBIRD.guid, '10.0', True),    # 4
            (amo.THUNDERBIRD.guid, '6.6.3', False),  # 5
            (amo.THUNDERBIRD.guid, '6.0.1', False),  # 6

            (amo.SEAMONKEY.guid, '2.3.0', False),    # 7
            (amo.SEAMONKEY.guid, '2.3a1', False),    # 8
            (amo.SEAMONKEY.guid, '2.3', False),      # 9
        ]
        for app_guid, app_version, works_properly in apps:
            report = CompatReport.objects.create(guid=self.addon.guid,
                                                 app_guid=app_guid,
                                                 app_version=app_version,
                                                 works_properly=works_properly)
            self.reports.append(report.pk)

    def check_table(self, data={}, good=0, bad=0, appver=None, report_pks=[]):
        r = self.client.get(self.url, data)
        eq_(r.status_code, 200)

        # Check that we got the correct reports.
        eq_(sorted(r.id for r in r.context['reports'].object_list),
            sorted(self.reports[pk] for pk in report_pks))

        doc = pq(r.content)
        eq_(doc('.compat-info tbody tr').length, good + bad)

        reports = doc('#reports')
        if good == 0 and bad == 0:
            eq_(reports.find('.good, .bad').length, 0)
            eq_(doc('.no-results').length, 1)
        else:
            # Check "X success reports" and "X failure reports" buttons.
            eq_(reports.find('.good').text().split()[0], str(good))
            eq_(reports.find('.bad').text().split()[0], str(bad))

            # Check "Filter by Application" field.
            eq_(doc('#compat-form select[name=appver] option[selected]').val(),
                appver)

        return r

    def test_appver_all(self):
        self._generate()
        self.check_table(good=3, bad=7, appver='',
            report_pks=[idx for idx, val in enumerate(self.reports)])

    def test_firefox_single(self):
        self._generate()
        appver = '%s-%s' % (amo.FIREFOX.id, '6.0')
        self.check_table(data={'appver': appver}, good=0, bad=1, appver=appver,
                         report_pks=[3])

    def test_firefox_multiple(self):
        self._generate()
        appver = '%s-%s' % (amo.FIREFOX.id, '10.0')
        self.check_table(data={'appver': appver}, good=2, bad=1, appver=appver,
                         report_pks=[0, 1, 2])

    def test_firefox_empty(self):
        self._generate()
        appver = '%s-%s' % (amo.FIREFOX.id,
                            amo.COMPAT[0]['main'])  # Firefox 11.
        self.check_table(data={'appver': appver}, good=0, bad=0, appver=appver,
                         report_pks=[])

    def test_firefox_unknown(self):
        self._generate()
        # If we have a bad app/version combination, we don't apply any filters.
        appver = '%s-%s' % (amo.FIREFOX.id, '0.9999')
        self.check_table(data={'appver': appver}, good=3, bad=7,
            report_pks=[idx for idx, val in enumerate(self.reports)])

    def test_thunderbird_multiple(self):
        self._generate()
        appver = '%s-%s' % (amo.THUNDERBIRD.id, '6.0')
        self.check_table(data={'appver': appver}, good=0, bad=2, appver=appver,
                         report_pks=[5, 6])

    def test_thunderbird_unknown(self):
        self._generate()
        appver = '%s-%s' % (amo.THUNDERBIRD.id, '0.9999')
        self.check_table(data={'appver': appver}, good=3, bad=7,
            report_pks=[idx for idx, val in enumerate(self.reports)])

    def test_seamonkey_multiple(self):
        self._generate()
        appver = '%s-%s' % (amo.SEAMONKEY.id, '2.3')
        self.check_table(data={'appver': appver}, good=0, bad=3, appver=appver,
                         report_pks=[7, 8, 9])

    def test_seamonkey_unknown(self):
        self._generate()
        appver = '%s-%s' % (amo.SEAMONKEY.id, '0.9999')
        self.check_table(data={'appver': appver}, good=3, bad=7,
            report_pks=[idx for idx, val in enumerate(self.reports)])

    def test_app_unknown(self):
        # Testing for some unknown application such as 'Conkeror'.
        app_guid = '{a79fe89b-6662-4ff4-8e88-09950ad4dfde}'
        report = CompatReport.objects.create(guid=self.addon.guid,
            app_guid=app_guid, app_version='0.9.3', works_properly=True)
        self.reports.append(report.pk)
        r = self.check_table(good=1, bad=0, appver='', report_pks=[0])
        msg = 'Unknown (%s)' % app_guid
        assert msg in r.content, 'Expected %s in body' % msg
