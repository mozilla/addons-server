import datetime
from unittest import mock

from freezegun import freeze_time
from waffle.testutils import override_switch

from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.blocklist.cron import MLBF_TIME_CONFIG_KEY, upload_mlbf_to_kinto
from olympia.blocklist.mlbf import get_mlbf_key_format
from olympia.blocklist.models import Block
from olympia.lib.kinto import KintoServer
from olympia.zadmin.models import get_config, set_config


class TestUploadToKinto(TestCase):
    def setUp(self):
        addon_factory()
        self.block = Block.objects.create(
            addon=addon_factory(),
            updated_by=user_factory())

    @freeze_time('2020-01-01 12:34:56')
    @override_switch('blocklist_mlbf_submit', active=True)
    @mock.patch('olympia.blocklist.cron.get_mlbf_key_format')
    @mock.patch.object(KintoServer, 'publish_attachment')
    def test_upload_mlbf_to_kinto(self, publish_mock, get_mlbf_key_mock):
        key_format = get_mlbf_key_format()
        get_mlbf_key_mock.return_value = key_format

        upload_mlbf_to_kinto()

        publish_mock.assert_called_with(
            {'key_format': key_format,
             'generation_time':
                datetime.datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000},
            ('filter.bin', mock.ANY, 'application/octet-stream'))
        assert (
            get_config(MLBF_TIME_CONFIG_KEY, json_value=True) ==
            int(datetime.datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000))

    @override_switch('blocklist_mlbf_submit', active=False)
    @mock.patch.object(KintoServer, 'publish_attachment')
    def test_waffle_off_disables_publishing(self, publish_mock):
        upload_mlbf_to_kinto()

        publish_mock.assert_not_called()
        assert not get_config(MLBF_TIME_CONFIG_KEY)

    @freeze_time('2020-01-01 12:34:56')
    @override_switch('blocklist_mlbf_submit', active=True)
    @mock.patch.object(KintoServer, 'publish_attachment')
    def test_no_need_for_new_mlbf(self, publish_mock):
        # This was the last time the mlbf was generated
        last_time = int(
            datetime.datetime(2020, 1, 1, 12, 34, 1).timestamp() * 1000)
        # And the Block was modified just before so would be included
        self.block.update(modified=datetime.datetime(2020, 1, 1, 12, 34, 0))
        set_config(MLBF_TIME_CONFIG_KEY, last_time, json_value=True)
        upload_mlbf_to_kinto()
        # So no need for a new bloomfilter
        publish_mock.assert_not_called()

        # But if we add a new Block a new filter is needed
        addon_factory()
        Block.objects.create(
            addon=addon_factory(),
            updated_by=user_factory())
        upload_mlbf_to_kinto()
        publish_mock.assert_called_once()
        assert (
            get_config(MLBF_TIME_CONFIG_KEY, json_value=True) ==
            int(datetime.datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000))
