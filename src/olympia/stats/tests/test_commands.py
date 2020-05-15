import boto3
import json
import os
import shutil

from botocore.stub import Stubber, ANY
from datetime import date

from django.conf import settings
from django.core import management
from django.test.testcases import TransactionTestCase
from django.test.utils import override_settings

from unittest import mock

from olympia import amo
from olympia.amo.storage_utils import rm_stored_dir
from olympia.amo.tests import addon_factory
from olympia.stats.management.commands import get_stats_data
from olympia.stats.management.commands.download_counts_from_file import \
    is_valid_source  # noqa
from olympia.stats.management.commands.update_counts_from_file import Command
from olympia.stats.models import DownloadCount, UpdateCount


hive_folder = os.path.join(settings.ROOT, 'src/olympia/stats/fixtures/files')


class FixturesFolderMixin(object):
    # You have to define these values in your subclasses.
    date = 'YYYY-MM-DD'
    source_folder = 'dummy'
    stats_source = 'dummy'

    def get_tmp_hive_folder(self):
        return os.path.join(hive_folder, self.id())

    def clean_up_files(self):
        tmp_hive_folder = self.get_tmp_hive_folder()
        if os.path.isdir(tmp_hive_folder):
            rm_stored_dir(tmp_hive_folder)

    def setUp(self):
        super(FixturesFolderMixin, self).setUp()
        self.clean_up_files()
        shutil.copytree(os.path.join(hive_folder, self.source_folder),
                        os.path.join(self.get_tmp_hive_folder(), self.date))

    def tearDown(self):
        self.clean_up_files()
        super(FixturesFolderMixin, self).tearDown()


class TestADICommand(FixturesFolderMixin, TransactionTestCase):
    fixtures = ('base/addon_3615', 'base/featured', 'base/appversion.json')
    date = '2014-07-10'
    source_folder = 'src'
    stats_source = 'file'

    def setUp(self):
        super(TestADICommand, self).setUp()
        self.command = Command()

    def test_update_counts_from_file(self):
        management.call_command('update_counts_from_file',
                                self.get_tmp_hive_folder(), date=self.date,
                                stats_source=self.stats_source)
        assert UpdateCount.objects.all().count() == 1
        update_count = UpdateCount.objects.last()
        # should be identical to `statuses.userEnabled`
        assert update_count.count == 4
        assert update_count.date == date(2014, 7, 10)
        assert update_count.versions == {u'3.8': 2, u'3.7': 3}
        assert update_count.statuses == {u'userDisabled': 1, u'userEnabled': 4}
        application = u'{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'
        assert update_count.applications[application] == {u'3.6': 18}
        assert update_count.oses == {u'WINNT': 5}
        assert update_count.locales == {u'en-us': 1, u'en-US': 4}

    def test_update_counts_from_file_includes_disabled_addons(self):
        addon_factory(
            guid='{39e6cf40-02f6-4bda-b1ee-409910ffd9f9}',
            slug='disabled-addon',
            status=amo.STATUS_DISABLED)
        addon_factory(
            guid='9c444b87-1124-4fd2-b97f-8fb7e9be1820',
            slug='incomplete-addon', status=amo.STATUS_NULL)

        management.call_command('update_counts_from_file',
                                self.get_tmp_hive_folder(), date=self.date,
                                stats_source=self.stats_source)
        assert UpdateCount.objects.all().count() == 2

        update_count = UpdateCount.objects.get(addon_id=3615)
        # should be identical to `statuses.userEnabled`
        assert update_count.count == 4
        assert update_count.date == date(2014, 7, 10)
        assert update_count.versions == {u'3.8': 2, u'3.7': 3}
        assert update_count.statuses == {u'userDisabled': 1, u'userEnabled': 4}

        update_count = UpdateCount.objects.get(addon__slug='disabled-addon')
        assert update_count.count == 2
        assert update_count.date == date(2014, 7, 10)
        assert update_count.versions == {}
        assert update_count.statuses == {u'userEnabled': 2}

        # Make sure we didn't generate any stats for incomplete add-ons
        assert not UpdateCount.objects.filter(
            addon__slug='incomplete-addon').exists()

    def test_update_version(self):
        # Initialize the known addons and their versions.
        self.command.addons_versions = {3615: ['3.5', '3.6']}
        uc = UpdateCount(addon_id=3615)
        self.command.update_version(uc, '3.6', 123)
        assert uc.versions == {'3.6': 123}
        # Test very long version:
        self.command.update_version(uc, '1' * 33, 1)
        assert uc.versions == {'3.6': 123, '1' * 32: 1}  # Trimmed.

    def test_update_status(self):
        uc = UpdateCount(addon_id=3615)
        self.command.update_status(uc, 'foobar', 123)  # Non-existent status.
        assert not uc.statuses
        self.command.update_status(uc, 'userEnabled', 123)
        assert uc.statuses == {'userEnabled': 123}

    def test_update_app(self):
        firefox_guid = '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'
        uc = UpdateCount(addon_id=3615)
        self.command.update_app(uc, 'foobar', '1.0', 123)  # Non-existent app.
        assert not uc.applications
        # Malformed versions.
        self.command.update_app(uc, firefox_guid, '3.0.1.2', 123)
        self.command.update_app(uc, firefox_guid, '3.0123', 123)
        self.command.update_app(uc, firefox_guid, '3.0c2', 123)
        self.command.update_app(uc, firefox_guid, 'a.b.c', 123)
        assert not uc.applications
        # Well formed versions.
        self.command.update_app(uc, firefox_guid, '1.0', 123)
        self.command.update_app(uc, firefox_guid, '1.0.1', 124)
        self.command.update_app(uc, firefox_guid, '1.0a1', 125)
        self.command.update_app(uc, firefox_guid, '1.0b2', 126)
        assert uc.applications == {firefox_guid: {
            '1.0': 123,
            '1.0.1': 124,
            '1.0a1': 125,
            '1.0b2': 126}}

    def test_update_os(self):
        uc = UpdateCount(addon_id=3615)
        self.command.update_os(uc, 'foobar', 123)  # Non-existent OS.
        assert not uc.oses
        self.command.update_os(uc, 'WINNT', 123)
        assert uc.oses == {'WINNT': 123}

    def test_update_locale(self):
        current_locales = [  # Taken from the language pack index.
            'ach', 'af', 'ak', 'an', 'ar', 'as', 'ast', 'ast-ES', 'az',
            'bb-BK', 'be', 'bg', 'bn', 'br', 'bs', 'ca',
            'ca-valencia', 'cs', 'csb', 'cy', 'cy-GB', 'da', 'de', 'dsb', 'el',
            'en-GB', 'en-ZA', 'eo', 'es-AR', 'es-CL', 'es-ES', 'es-MX', 'et',
            'eu', 'fa', 'ff', 'fi', 'fj-FJ', 'fr', 'fur-IT', 'fy-NL', 'ga-IE',
            'gd', 'gl', 'gu-IN', 'he', 'hi', 'hi-IN', 'hr', 'hsb', 'hu',
            'hy-AM', 'id', 'is', 'it', 'ja', 'kk', 'km', 'kn', 'ko', 'ku',
            'lg', 'lij', 'lt', 'lv', 'mai', 'mg', 'mk', 'ml', 'mr', 'ms',
            'nb-NO', 'nl', 'nn-NO', 'nr', 'nso', 'or', 'pa-IN', 'pl', 'pt-BR',
            'pt-PT', 'rm', 'ro', 'ru', 'si', 'sk', 'sl', 'son', 'sq', 'sr',
            'ss', 'st', 'sv-SE', 'sw', 'sw-TZ', 'ta', 'ta-IN', 'ta-LK', 'te',
            'th', 'tn', 'tr', 'ts', 'uk', 'ur', 've', 'vi', 'wa', 'wo-SN',
            'xh', 'zap-MX-diiste', 'zh-CN', 'zh-TW', 'zu']
        uc = UpdateCount(addon_id=3615)
        self.command.update_locale(uc, 'foobar', 123)  # Non-existent locale.
        assert not uc.locales
        for locale in current_locales:
            self.command.update_locale(uc, locale, 1)
        assert len(uc.locales) == len(current_locales)

    def test_trim_field(self):
        uc = UpdateCount(addon_id=3615, count=1, date='2015-01-11')
        self.command.trim_field(uc.versions)  # Empty field.
        assert not uc.versions

        uc.versions = {'3.6': 123, '3.7': 321}
        self.command.trim_field(uc.versions)  # Small enough to fit in the db.
        assert uc.versions == {'3.6': 123, '3.7': 321}  # Unchanged.

        very_long_key = 'x' * (2 ** 16)
        uc.versions[very_long_key] = 1
        self.command.trim_field(uc.versions)  # Too big, must be trimmed.
        assert uc.versions == {'3.6': 123, '3.7': 321}  # Keep the most used.

        uc.versions[very_long_key] = 1000  # Most used.
        self.command.trim_field(uc.versions)  # Too big, must be trimmed.
        # Nothing left: least used removed, but still too big, so all the keys
        # were removed.
        assert uc.versions == {}

        # Make sure we can store a very large field in the database.
        long_key = 'x' * 65528  # This makes the dict barely fit in the db.
        uc.versions[long_key] = 1
        assert len(json.dumps(uc.versions)) == (2 ** 16) - 1
        uc.save()
        uc = UpdateCount.objects.get(pk=uc.pk)  # Reload
        # Fits in the database, so no truncation.
        assert len(json.dumps(uc.versions)) == (2 ** 16) - 1

    def test_download_counts_from_file(self):
        management.call_command('download_counts_from_file',
                                self.get_tmp_hive_folder(), date=self.date,
                                stats_source=self.stats_source)
        assert DownloadCount.objects.all().count() == 2
        download_count = DownloadCount.objects.get(addon_id=3615)
        assert download_count.count == 3
        assert download_count.date == date(2014, 7, 10)
        assert download_count.sources == {u'search': 2, u'cb-dl-bob': 1}

    def test_download_counts_from_file_includes_disabled_addons(self):
        # We only exclude STATUS_NULL add-ons
        addon_factory(slug='disabled-addon', status=amo.STATUS_DISABLED)
        addon_factory(slug='incomplete-addon', status=amo.STATUS_NULL)

        management.call_command('download_counts_from_file',
                                self.get_tmp_hive_folder(), date=self.date,
                                stats_source=self.stats_source)

        assert DownloadCount.objects.all().count() == 3
        download_count = DownloadCount.objects.get(addon_id=3615)
        assert download_count.count == 3
        assert download_count.date == date(2014, 7, 10)
        assert download_count.sources == {u'search': 2, u'cb-dl-bob': 1}

        download_count = DownloadCount.objects.get(
            addon__slug='disabled-addon')
        assert download_count.count == 1
        assert download_count.date == date(2014, 7, 10)
        assert download_count.sources == {u'search': 1}

        # Make sure we didn't generate any stats for incomplete add-ons
        assert not DownloadCount.objects.filter(
            addon__slug='incomplete-addon').exists()

    @mock.patch(
        'olympia.stats.management.commands.download_counts_from_file.'
        'close_old_connections')
    def test_download_counts_from_file_closes_old_connections(
            self, close_old_connections_mock):
        management.call_command('download_counts_from_file',
                                self.get_tmp_hive_folder(), date=self.date,
                                stats_source=self.stats_source)
        assert DownloadCount.objects.all().count() == 2
        close_old_connections_mock.assert_called_once()

    def test_is_valid_source(self):
        assert is_valid_source('foo',
                               fulls=['foo', 'bar'],
                               prefixes=['baz', 'cruux'])
        assert not is_valid_source('foob',
                                   fulls=['foo', 'bar'],
                                   prefixes=['baz', 'cruux'])
        assert is_valid_source('bazfoo',
                               fulls=['foo', 'bar'],
                               prefixes=['baz', 'cruux'])
        assert not is_valid_source('ba',
                                   fulls=['foo', 'bar'],
                                   prefixes=['baz', 'cruux'])


class TestADICommandS3(TransactionTestCase):
    fixtures = ('base/addon_3615', 'base/featured', 'base/appversion.json')
    date = '2014-07-10'
    stats_source = 's3'

    def add_response(self, stat):
        stat_path = os.path.join(hive_folder, 'src', '%s.hive' % stat)
        data = get_stats_data(stat_path)
        response = {
            'Body': data,
        }
        expected_params = {'Bucket': 'test-bucket',
                           'Key': os.path.join('amo_stats', stat,
                                               self.date, '000000_0'),
                           'Range': ANY}
        self.stubber.add_response('get_object', response, expected_params)

    def setUp(self):
        self.client = boto3.client('s3')
        self.stubber = Stubber(self.client)
        self.stubber.activate()

    def tearDown(self):
        self.stubber.deactivate()

    @override_settings(AWS_STATS_S3_BUCKET='test-bucket')
    @mock.patch('olympia.stats.management.commands.boto3')
    def test_update_counts_from_s3(self, mock_boto3):
        stats = ['app', 'locale', 'os', 'status', 'version']

        for x in range(2):
            for stat in stats:
                self.add_response('update_counts_by_%s' % stat)

        mock_boto3.client.return_value = self.client
        management.call_command('update_counts_from_file',
                                date=self.date, stats_source=self.stats_source)

        assert UpdateCount.objects.all().count() == 1
        update_count = UpdateCount.objects.last()
        # should be identical to `statuses.userEnabled`
        assert update_count.count == 4
        assert update_count.date == date(2014, 7, 10)
        assert update_count.versions == {u'3.8': 2, u'3.7': 3}
        assert update_count.statuses == {u'userDisabled': 1, u'userEnabled': 4}
        application = u'{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'
        assert update_count.applications[application] == {u'3.6': 18}
        assert update_count.oses == {u'WINNT': 5}
        assert update_count.locales == {u'en-us': 1, u'en-US': 4}

    @override_settings(AWS_STATS_S3_BUCKET='test-bucket')
    @mock.patch('olympia.stats.management.commands.boto3')
    def test_download_counts_from_s3(self, mock_boto3):
        for x in range(2):
            self.add_response('download_counts')

        mock_boto3.client.return_value = self.client

        management.call_command('download_counts_from_file',
                                date=self.date, stats_source=self.stats_source)
        assert DownloadCount.objects.all().count() == 2
        download_count = DownloadCount.objects.get(addon_id=3615)
        assert download_count.count == 3
        assert download_count.date == date(2014, 7, 10)
        assert download_count.sources == {u'search': 2, u'cb-dl-bob': 1}
