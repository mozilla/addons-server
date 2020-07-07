import boto3
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
from olympia.stats.models import DownloadCount


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
        assert is_valid_source('foobaz',
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
