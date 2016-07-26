import json

import mock
from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.addons.models import Addon
from olympia.compat.indexers import AppCompatIndexer
from olympia.compat.models import CompatReport


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
    'appMultiprocessEnabled': True,
    'multiprocessCompatible': True,
}


class TestCompatReportModel(TestCase):

    def test_none(self):
        assert CompatReport.get_counts('xxx') == {'success': 0, 'failure': 0}

    def test_some(self):
        guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        CompatReport.objects.create(
            guid=guid,
            works_properly=True,
            app_multiprocess_enabled=True,
            multiprocess_compatible=True)
        CompatReport.objects.create(
            guid=guid,
            works_properly=True,
            app_multiprocess_enabled=False,
            multiprocess_compatible=True)
        CompatReport.objects.create(
            guid=guid,
            works_properly=False,
            app_multiprocess_enabled=False,
            multiprocess_compatible=True)
        CompatReport.objects.create(
            guid='ballin',
            works_properly=True,
            app_multiprocess_enabled=True,
            multiprocess_compatible=True)
        CompatReport.objects.create(
            guid='ballin',
            works_properly=False,
            app_multiprocess_enabled=True,
            multiprocess_compatible=True)
        assert CompatReport.get_counts(guid) == {'success': 2, 'failure': 1}


class TestIncoming(TestCase):

    def setUp(self):
        super(TestIncoming, self).setUp()
        self.url = reverse('compat.incoming')
        self.data = dict(incoming_data)
        self.json = json.dumps(self.data)

    def test_success(self):
        count = CompatReport.objects.count()
        r = self.client.post(self.url, self.json,
                             content_type='application/json')
        assert r.status_code == 204
        assert CompatReport.objects.count() == count + 1

        cr = CompatReport.objects.order_by('-id')[0]
        assert cr.app_build == incoming_data['appBuild']
        assert cr.app_guid == incoming_data['appGUID']
        assert cr.works_properly == incoming_data['worksProperly']
        assert cr.comments == incoming_data['comments']
        assert cr.client_ip == '127.0.0.1'
        assert cr.app_multiprocess_enabled == (
            incoming_data['appMultiprocessEnabled'])
        assert cr.multiprocess_compatible == (
            incoming_data['multiprocessCompatible'])

        # Check that the other_addons field is stored as json.
        vals = CompatReport.objects.filter(id=cr.id).values('other_addons')
        assert vals[0]['other_addons'] == (
            json.dumps(incoming_data['otherAddons']))

    def test_e10s_status_unknown(self):
        del self.data['multiprocessCompatible']
        self.json = json.dumps(self.data)

        count = CompatReport.objects.count()
        r = self.client.post(self.url, self.json,
                             content_type='application/json')
        assert r.status_code == 204
        assert CompatReport.objects.count() == count + 1

        cr = CompatReport.objects.order_by('-id')[0]
        assert cr.multiprocess_compatible is None

    def test_bad_json(self):
        r = self.client.post(self.url, 'wuuu#$',
                             content_type='application/json')
        assert r.status_code == 400

    def test_bad_field(self):
        self.data['save'] = 1
        js = json.dumps(self.data)
        r = self.client.post(self.url, js, content_type='application/json')
        assert r.status_code == 400


class TestReporter(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestReporter, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.url = reverse('compat.reporter') + '?guid={0}'

    def test_success(self):
        r = self.client.get(reverse('compat.reporter'))
        assert r.status_code == 200

    def test_redirect(self):
        CompatReport.objects.create(guid=self.addon.guid,
                                    app_guid=amo.FIREFOX.guid)
        expected = reverse('compat.reporter_detail', args=[self.addon.guid])

        self.assert3xx(
            self.client.get(self.url.format(self.addon.id)), expected)
        self.assert3xx(
            self.client.get(self.url.format(self.addon.slug)), expected)
        self.assert3xx(
            self.client.get(self.url.format(self.addon.guid)), expected)
        self.assert3xx(
            self.client.get(self.url.format(self.addon.guid[:5])), expected)

    @mock.patch('olympia.compat.views.owner_or_unlisted_reviewer',
                lambda r, a: True)
    def test_unlisted_addon_redirect_for_authorized(self):
        """Can display the reports for an unlisted addon if authorized."""
        self.addon.update(is_listed=False)
        self.test_redirect()

    @mock.patch('olympia.compat.views.owner_or_unlisted_reviewer',
                lambda r, a: False)
    def test_unlisted_addon_no_redirect_for_unauthorized(self):
        """If the user isn't authorized, don't redirect to unlisted addon."""
        self.addon.update(is_listed=False)
        CompatReport.objects.create(guid=self.addon.guid,
                                    app_guid=amo.FIREFOX.guid)

        assert self.client.get(
            self.url.format(self.addon.id)).status_code == 200
        assert self.client.get(
            self.url.format(self.addon.slug)).status_code == 200
        assert self.client.get(
            self.url.format(self.addon.guid)).status_code == 200
        assert self.client.get(
            self.url.format(self.addon.guid[:5])).status_code == 200

    def test_unlisted_addons_listed_in_left_sidebar(self):
        """Display unlisted addons in the 'reports for your add-ons' list."""
        self.addon.update(is_listed=False)
        self.client.login(username='del@icio.us', password='password')
        response = self.client.get(reverse('compat.reporter'))
        assert self.addon in response.context['addons']


class TestReporterDetail(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestReporterDetail, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = reverse('compat.reporter_detail', args=[self.addon.guid])
        self.reports = []

    def _generate(self):
        apps = [
            (amo.FIREFOX.guid, '10.0.1', True, False, False),      # 0
            (amo.FIREFOX.guid, '10.0a1', True, True, False),       # 1
            (amo.FIREFOX.guid, '10.0', False, False, False),       # 2
            (amo.FIREFOX.guid, '6.0.1', False, False, False),      # 3

            (amo.THUNDERBIRD.guid, '10.0', True, True, False),     # 4
            (amo.THUNDERBIRD.guid, '6.6.3', False, False, False),  # 5
            (amo.THUNDERBIRD.guid, '6.0.1', False, False, False),  # 6

            (amo.SEAMONKEY.guid, '2.3.0', False, True, False),     # 7
            (amo.SEAMONKEY.guid, '2.3a1', False, False, False),    # 8
            (amo.SEAMONKEY.guid, '2.3', False, False, False),      # 9
        ]
        for (app_guid, app_version, works_properly, multiprocess_compatible,
             app_multiprocess_enabled) in apps:
            report = CompatReport.objects.create(
                guid=self.addon.guid,
                app_guid=app_guid,
                app_version=app_version,
                works_properly=works_properly,
                multiprocess_compatible=multiprocess_compatible,
                app_multiprocess_enabled=app_multiprocess_enabled)
            self.reports.append(report.pk)

    def check_table(self, data={}, good=0, bad=0, appver=None, report_pks=[]):
        r = self.client.get(self.url, data)
        assert r.status_code == 200

        # Check that we got the correct reports.
        assert sorted(r.id for r in r.context['reports'].object_list) == (
            sorted(self.reports[pk] for pk in report_pks))

        doc = pq(r.content)
        assert doc('.compat-info tbody tr').length == good + bad

        reports = doc('#reports')
        if good == 0 and bad == 0:
            assert reports.find('.good, .bad').length == 0
            assert doc('.no-results').length == 1
        else:
            # Check "X success reports" and "X failure reports" buttons.
            assert reports.find('.good').text().split()[0] == str(good)
            assert reports.find('.bad').text().split()[0] == str(bad)

            # Check "Filter by Application" field.
            option = doc('#compat-form select[name="appver"] option[selected]')
            assert option.val() == appver
        return r

    def test_appver_all(self):
        self._generate()
        self.check_table(
            good=3, bad=7, appver=None,
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
        self.check_table(
            data={'appver': appver}, good=3, bad=7,
            report_pks=[idx for idx, val in enumerate(self.reports)])

    def test_thunderbird_multiple(self):
        self._generate()
        appver = '%s-%s' % (amo.THUNDERBIRD.id, '6.0')
        self.check_table(data={'appver': appver}, good=0, bad=2, appver=appver,
                         report_pks=[5, 6])

    def test_thunderbird_unknown(self):
        self._generate()
        appver = '%s-%s' % (amo.THUNDERBIRD.id, '0.9999')
        self.check_table(
            data={'appver': appver}, good=3, bad=7,
            report_pks=[idx for idx, val in enumerate(self.reports)])

    def test_seamonkey_multiple(self):
        self._generate()
        appver = '%s-%s' % (amo.SEAMONKEY.id, '2.3')
        self.check_table(data={'appver': appver}, good=0, bad=3, appver=appver,
                         report_pks=[7, 8, 9])

    def test_seamonkey_unknown(self):
        self._generate()
        appver = '%s-%s' % (amo.SEAMONKEY.id, '0.9999')
        self.check_table(
            data={'appver': appver}, good=3, bad=7,
            report_pks=[idx for idx, val in enumerate(self.reports)])

    def test_app_unknown(self):
        # Testing for some unknown application such as 'Conkeror'.
        app_guid = '{a79fe89b-6662-4ff4-8e88-09950ad4dfde}'
        report = CompatReport.objects.create(
            guid=self.addon.guid, app_guid=app_guid, app_version='0.9.3',
            works_properly=True)
        self.reports.append(report.pk)
        r = self.check_table(good=1, bad=0, appver=None, report_pks=[0])
        msg = 'Unknown (%s)' % app_guid
        assert msg in r.content, 'Expected %s in body' % msg

    @mock.patch('olympia.compat.views.owner_or_unlisted_reviewer',
                lambda r, a: True)
    def test_unlisted_addon_details_for_authorized(self):
        """If the user is authorized, display the reports."""
        self.addon.update(is_listed=False)
        self._generate()
        self.check_table(
            good=3, bad=7, appver=None,
            report_pks=[idx for idx, val in enumerate(self.reports)])

    @mock.patch('olympia.compat.views.owner_or_unlisted_reviewer',
                lambda r, a: False)
    def test_unlisted_addon_no_details_for_unauthorized(self):
        """If the user isn't authorized, don't display the reports."""
        self.addon.update(is_listed=False)
        self._generate()
        self.check_table(
            good=0, bad=0, appver=None,
            report_pks=[])


class TestAppCompatIndexer(TestCase):
    def setUp(self):
        self.indexer = AppCompatIndexer()

    def test_mapping(self):
        doc_name = self.indexer.get_doctype_name()
        assert doc_name

        mapping_properties = self.indexer.get_mapping()[doc_name]['properties']

        # Spot check: make sure addon-specific 'summary' field is not present.
        assert 'summary' not in mapping_properties

    def test_no_extract(self):
        # Extraction is handled differently for this class because it's quite
        # specific, so it does not have an extract_document() method.
        assert not hasattr(self.indexer, 'extract_document')
