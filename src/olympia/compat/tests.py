import json

from datetime import datetime

import mock

from django_extensions.db.fields.json import JSONList
from pyquery import PyQuery as pq

from olympia import amo
from olympia.addons.models import Addon, AppSupport
from olympia.addons.utils import generate_addon_guid
from olympia.amo.tests import ESTestCase, TestCase, version_factory
from olympia.amo.urlresolvers import reverse
from olympia.compat import FIREFOX_COMPAT
from olympia.compat.cron import compatibility_report
from olympia.compat.indexers import AppCompatIndexer
from olympia.compat.models import CompatReport, CompatTotals
from olympia.stats.models import UpdateCount
from olympia.versions.models import ApplicationsVersions


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
        # This is the structure sent to /compatibility/incoming from the ACR.
        self.data = {
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
        self.json = json.dumps(self.data)

    def test_success(self):
        count = CompatReport.objects.count()
        r = self.client.post(self.url, self.json,
                             content_type='application/json')
        assert r.status_code == 204
        assert CompatReport.objects.count() == count + 1

        cr = CompatReport.objects.order_by('-id')[0]
        assert cr.app_build == self.data['appBuild']
        assert cr.app_guid == self.data['appGUID']
        assert cr.works_properly == self.data['worksProperly']
        assert cr.comments == self.data['comments']
        assert cr.client_ip == '127.0.0.1'
        assert cr.app_multiprocess_enabled == (
            self.data['appMultiprocessEnabled'])
        assert cr.multiprocess_compatible == (
            self.data['multiprocessCompatible'])

        # Check that the other_addons field is stored as json.
        # This is a dummy check and relies on implementation details of
        # django-extensions but more recent versions of django apply
        # to_python to .values and even raw queries more properly so we'll
        # have to live with it.
        vals = CompatReport.objects.filter(id=cr.id).values('other_addons')
        assert isinstance(vals[0]['other_addons'], JSONList)
        assert vals[0]['other_addons'] == self.data['otherAddons']

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
        self.make_addon_unlisted(self.addon)
        self.test_redirect()

    @mock.patch('olympia.compat.views.owner_or_unlisted_reviewer',
                lambda r, a: False)
    def test_unlisted_addon_no_redirect_for_unauthorized(self):
        """If the user isn't authorized, don't redirect to unlisted addon."""
        self.make_addon_unlisted(self.addon)
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

    @mock.patch('olympia.compat.views.owner_or_unlisted_reviewer',
                lambda r, a: False)
    def test_mixed_listed_unlisted_redirect_for_unauthorized(self):
        """If the user isn't authorized, and the add-on has both unlisted and
        listed versions, redirect to show the listed versions."""
        self.make_addon_unlisted(self.addon)
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED)
        self.test_redirect()

    def test_unlisted_addons_listed_in_left_sidebar(self):
        """Display unlisted addons in the 'reports for your add-ons' list."""
        self.make_addon_unlisted(self.addon)
        self.client.login(email='del@icio.us')
        response = self.client.get(reverse('compat.reporter'))
        assert self.addon in response.context['addons']


class TestReporterDetail(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestReporterDetail, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = reverse('compat.reporter_detail', args=[self.addon.guid])
        self.reports = []

    def _generate(self, version=None):
        apps = [
            (amo.FIREFOX.guid, FIREFOX_COMPAT[0]['main'], True, False, False),
            (amo.FIREFOX.guid, FIREFOX_COMPAT[0]['main'], True, False, False),
            (amo.FIREFOX.guid, FIREFOX_COMPAT[1]['main'], True, True, False),
            (amo.FIREFOX.guid, FIREFOX_COMPAT[2]['main'], False, False, False),
            (amo.FIREFOX.guid, FIREFOX_COMPAT[3]['main'], False, False, False),
        ]
        if version is None:
            version = self.addon.find_latest_version(channel=None)
        for (app_guid, app_version, works_properly, multiprocess_compatible,
             app_multiprocess_enabled) in apps:
            report = CompatReport.objects.create(
                guid=self.addon.guid,
                version=version,
                app_guid=app_guid,
                app_version=app_version,
                works_properly=works_properly,
                multiprocess_compatible=multiprocess_compatible,
                app_multiprocess_enabled=app_multiprocess_enabled)
            self.reports.append(report.pk)

    def check_table(
            self, data=None, good=0, bad=0, appver=None, report_pks=None):
        if data is None:
            data = {}
        if report_pks is None:
            report_pks = []
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
            good=3, bad=2, appver='',
            report_pks=[idx for idx, val in enumerate(self.reports)])

    def test_single(self):
        self._generate()
        appver = FIREFOX_COMPAT[2]['main']
        self.check_table(data={'appver': appver}, good=0, bad=1, appver=appver,
                         report_pks=[3])

    def test_multiple(self):
        self._generate()
        appver = FIREFOX_COMPAT[0]['main']
        self.check_table(data={'appver': appver}, good=2, bad=0, appver=appver,
                         report_pks=[0, 1])

    def test_empty(self):
        self._generate()
        # Pick a version we haven't generated any reports for.
        appver = FIREFOX_COMPAT[4]['main']
        self.check_table(data={'appver': appver}, good=0, bad=0, appver=appver,
                         report_pks=[])

    def test_unknown(self):
        self._generate()
        # If we have a bad version, we don't apply any filters.
        appver = '0.9999'
        self.check_table(
            data={'appver': appver}, good=3, bad=2,
            report_pks=[idx for idx, val in enumerate(self.reports)])

    def test_app_unknown(self):
        # Testing for some unknown application such as 'Conkeror'.
        app_guid = '{a79fe89b-6662-4ff4-8e88-09950ad4dfde}'
        report = CompatReport.objects.create(
            guid=self.addon.guid, app_guid=app_guid, app_version='0.9.3',
            works_properly=True)
        self.reports.append(report.pk)
        self.check_table(good=1, bad=0, appver='', report_pks=[0])

    @mock.patch('olympia.compat.views.owner_or_unlisted_reviewer',
                lambda r, a: True)
    def test_unlisted_addon_details_for_authorized(self):
        """If the user is authorized, display the reports."""
        self.make_addon_unlisted(self.addon)
        self._generate()
        self.check_table(
            good=3, bad=2, appver='',
            report_pks=[idx for idx, val in enumerate(self.reports)])

    @mock.patch('olympia.compat.views.owner_or_unlisted_reviewer',
                lambda r, a: False)
    def test_unlisted_addon_no_details_for_unauthorized(self):
        """If the user isn't authorized, don't display the reports."""
        self.make_addon_unlisted(self.addon)
        self._generate()
        self.check_table(
            good=0, bad=0, appver=None,
            report_pks=[])

    @mock.patch('olympia.compat.views.owner_or_unlisted_reviewer',
                lambda r, a: False)
    def test_mixed_listed_unlisted_details_for_unauthorized(self):
        """If the user isn't authorized, and the add-on has both unlisted and
        listed versions, display the listed versions."""
        self.make_addon_unlisted(self.addon)
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED)
        # Generate compat reports for the listed version.
        self._generate(version=self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED))
        reports_listed_only = list(self.reports)
        # And generate some for the unlisted version we shouldn't see.
        self._generate(version=self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED))

        self.check_table(
            good=3, bad=2, appver='',
            report_pks=[idx for idx, val in enumerate(reports_listed_only)])

    def test_e10s_field_appears(self):
        self._generate()
        appver = FIREFOX_COMPAT[0]['main']
        r = self.check_table(data={'appver': appver}, good=2, bad=0,
                             appver=appver, report_pks=[0, 1])
        doc = pq(r.content)
        assert doc('.app-multiprocess-enabled').length > 0
        assert doc('.multiprocess-compatible').length > 0


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


class TestCompatibilityReportCronMixin(object):
    def run_compatibility_report(self):
        compatibility_report()
        self.refresh()

    def populate(self):
        now = datetime.now()
        guid = generate_addon_guid()
        name = 'Addon %s' % guid
        addon = amo.tests.addon_factory(name=name, guid=guid)
        UpdateCount.objects.create(addon=addon, count=10, date=now)
        return addon

    def generate_reports(self, addon, good, bad, app, app_version):
        defaults = {
            'guid': addon.guid,
            'app_guid': app.guid,
            'app_version': app_version}
        for x in xrange(good):
            CompatReport.objects.create(works_properly=True, **defaults)
        for x in xrange(bad):
            CompatReport.objects.create(works_properly=False, **defaults)


class TestCompatibilityReportCron(
        TestCompatibilityReportCronMixin, ESTestCase):
    def setUp(self):
        self.app_version = FIREFOX_COMPAT[0]['main']
        super(TestCompatibilityReportCron, self).setUp()

    def test_with_bad_support_data(self):
        # Test containing an addon which has an AppSupport data indicating it
        # supports Firefox but does not have Firefox in its compatible apps for
        # some reason (https://github.com/mozilla/addons-server/issues/3353).
        addon = self.populate()
        self.generate_reports(addon=addon, good=1, bad=1, app=amo.FIREFOX,
                              app_version=self.app_version)

        # Now change compatibility to support Thunderbird instead of Firefox,
        # but make sure AppSupport stays in the previous state.
        ApplicationsVersions.objects.filter(
            application=amo.FIREFOX.id).update(application=amo.THUNDERBIRD.id)
        assert AppSupport.objects.filter(
            addon=addon, app=amo.FIREFOX.id).exists()

        self.run_compatibility_report()

        assert CompatTotals.objects.count() == 1
        assert CompatTotals.objects.get().total == 10

    def test_with_no_compat_at_all(self):
        # Test containing an add-on which has `None` as its compat info for
        # Firefox (https://github.com/mozilla/addons-server/issues/6161).
        addon = self.populate()
        self.generate_reports(addon=addon, good=1, bad=1, app=amo.FIREFOX,
                              app_version=self.app_version)

        addon.update(type=amo.ADDON_DICT)
        assert AppSupport.objects.filter(
            addon=addon, app=amo.FIREFOX.id).exists()

        self.run_compatibility_report()

        assert CompatTotals.objects.count() == 1
        assert CompatTotals.objects.get().total == 10

    def test_compat_totals(self):
        assert not CompatTotals.objects.exists()

        # Add second add-on, generate reports for both.
        addon1 = self.populate()
        addon2 = self.populate()
        # count needs to be higher than 50 to test totals properly.
        UpdateCount.objects.filter(addon=addon1).update(count=60)
        self.generate_reports(addon1, good=1, bad=2, app=amo.FIREFOX,
                              app_version=self.app_version)
        self.generate_reports(addon2, good=3, bad=4, app=amo.FIREFOX,
                              app_version=self.app_version)

        self.run_compatibility_report()

        assert CompatTotals.objects.count() == 1
        assert CompatTotals.objects.get().total == 70

    def test_compat_totals_already_exists(self):
        CompatTotals.objects.create(total=42)

        # Add second add-on, generate reports for both.
        addon1 = self.populate()
        addon2 = self.populate()
        # count needs to be higher than 50 to test totals properly.
        UpdateCount.objects.filter(addon=addon1).update(count=60)
        self.generate_reports(addon1, good=1, bad=2, app=amo.FIREFOX,
                              app_version=self.app_version)
        self.generate_reports(addon2, good=3, bad=4, app=amo.FIREFOX,
                              app_version=self.app_version)

        self.run_compatibility_report()

        assert CompatTotals.objects.count() == 1
        assert CompatTotals.objects.get().total == 70
