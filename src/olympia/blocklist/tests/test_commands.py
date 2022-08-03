import os
import json

from django.core.management import call_command
from django.core.management.base import CommandError
from django.conf import settings

from olympia import amo
from olympia.amo.tests import addon_factory, TestCase, user_factory

from ..models import Block


# This is a fragment of the actual json blocklist file
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
blocklist_file = os.path.join(TESTS_DIR, 'blocklists', 'blocklist.json')
with open(blocklist_file) as file_object:
    blocklist_json = json.load(file_object)


class TestExportBlocklist(TestCase):
    def test_command(self):
        for idx in range(0, 5):
            addon_factory()
        # one version, 0 - *
        Block.objects.create(
            addon=addon_factory(file_kw={'is_signed': True}),
            updated_by=user_factory(),
        )
        # one version, 0 - 9999
        Block.objects.create(
            addon=addon_factory(file_kw={'is_signed': True}),
            updated_by=user_factory(),
            max_version='9999',
        )
        # one version, 0 - *, unlisted
        Block.objects.create(
            addon=addon_factory(
                version_kw={'channel': amo.CHANNEL_UNLISTED},
                file_kw={'is_signed': True},
            ),
            updated_by=user_factory(),
        )

        call_command('export_blocklist', '1')
        out_path = os.path.join(settings.MLBF_STORAGE_PATH, '1', 'filter')
        assert os.path.exists(out_path)


class TestBulkAddBlocks(TestCase):
    def test_command(self):
        user_factory(id=settings.TASK_USER_ID)

        with self.assertRaises(CommandError):
            # no input guids
            call_command('bulk_add_blocks')
        assert Block.objects.count() == 0

        guids_path = os.path.join(TESTS_DIR, 'blocklists', 'input_guids.txt')
        call_command('bulk_add_blocks', guids_input=guids_path)
        # no guids matching addons
        assert Block.objects.count() == 0

        addon_factory(guid='{0020bd71-b1ba-4295-86af-db7f4e7eaedc}')
        addon_factory(guid='{another-random-guid')
        call_command('bulk_add_blocks', guids_input=guids_path)
        # this time we have 1 matching guid so one Block created
        assert Block.objects.count() == 1
        assert Block.objects.last().guid == ('{0020bd71-b1ba-4295-86af-db7f4e7eaedc}')

        addon_factory(guid='{00116dc4-ba1f-42c5-b20c-da7f743f7377}')
        call_command('bulk_add_blocks', guids_input=guids_path, min_version='44')
        # The guid before shouldn't be added twice
        # assert Block.objects.count() == 2
        prev_block = Block.objects.first()
        assert prev_block.guid == '{0020bd71-b1ba-4295-86af-db7f4e7eaedc}'
        assert prev_block.min_version == '44'
        new_block = Block.objects.last()
        assert new_block.guid == '{00116dc4-ba1f-42c5-b20c-da7f743f7377}'
        assert new_block.min_version == '44'
