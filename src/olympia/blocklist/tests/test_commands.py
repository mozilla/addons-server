import os
import json
from datetime import datetime
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.conf import settings

import responses

from olympia import amo
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.blocklist.management.commands import import_blocklist

from ..models import Block, KintoImport


# This is a fragment of the actual json blocklist file
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
blocklist_file = os.path.join(TESTS_DIR, 'blocklists', 'blocklist.json')
with open(blocklist_file) as file_object:
    blocklist_json = json.load(file_object)


class TestImportBlocklist(TestCase):

    def setUp(self):
        responses.add(
            responses.GET,
            import_blocklist.Command.KINTO_JSON_BLOCKLIST_URL,
            json=blocklist_json)
        self.task_user = user_factory(
            id=settings.TASK_USER_ID, username='mozilla')
        assert KintoImport.objects.count() == 0

    def test_empty(self):
        """ Test nothing is added if none of the guids match - any nothing
        fails.
        """
        addon_factory(file_kw={'is_webextension': True})
        assert Block.objects.count() == 0
        call_command('import_blocklist')
        assert Block.objects.count() == 0
        assert KintoImport.objects.count() == 8
        # the sample blocklist.json contains one regex for Thunderbird only
        assert KintoImport.objects.filter(
            outcome=KintoImport.OUTCOME_NOTFIREFOX).count() == 1
        assert KintoImport.objects.filter(
            outcome=KintoImport.OUTCOME_NOMATCH).count() == 7

    def test_regex(self):
        """ Test regex style "guids" are parsed and expanded to blocks."""
        addon_factory(
            guid='_qdNembers_@exmys.myysarch.com',
            file_kw={'is_webextension': True})
        addon_factory(
            guid='_dqMNemberstst_@www.dowespedtgttest.com',
            file_kw={'is_webextension': True})
        addon_factory(
            guid='{90ac2d06-caf8-46b9-5325-59c82190b687}',
            file_kw={'is_webextension': True})
        # this one is in the regex but doesn't have any webextension versions.
        addon_factory(
            guid='{_qjNembers_@wwqw.texcenteernow.com}',
            file_kw={'is_webextension': False})
        # And random other addon
        addon_factory(file_kw={'is_webextension': True})

        call_command('import_blocklist')
        assert Block.objects.count() == 3
        blocks = list(Block.objects.all())
        this_block = blocklist_json['data'][0]
        assert blocks[0].guid == '_dqMNemberstst_@www.dowespedtgttest.com'
        assert blocks[1].guid == '_qdNembers_@exmys.myysarch.com'
        assert blocks[2].guid == '{90ac2d06-caf8-46b9-5325-59c82190b687}'
        # the rest of the metadata should be the same
        for block in blocks:
            assert block.url == this_block['details']['bug']
            assert block.reason == this_block['details']['why']
            assert block.min_version == (
                this_block['versionRange'][0]['minVersion'])
            assert block.max_version == (
                this_block['versionRange'][0]['maxVersion'])
            assert block.kinto_id == '*' + this_block['id']
            assert block.include_in_legacy
            assert block.modified == datetime(2019, 11, 29, 22, 22, 46, 785000)
            assert block.is_imported_from_kinto_regex
        assert KintoImport.objects.count() == 8
        assert KintoImport.objects.filter(
            outcome=KintoImport.OUTCOME_NOMATCH).count() == 6
        kinto = KintoImport.objects.get(
            outcome=KintoImport.OUTCOME_REGEXBLOCKS)
        assert kinto.kinto_id == this_block['id']
        assert kinto.record == this_block

    def test_no_start_end_regex(self):
        """There are some regex that don't start with ^ and end with $"""
        addon_factory(
            guid='__TEMPLATE__APPLICATION__@puua-mapa.com',
            file_kw={'is_webextension': True})
        addon_factory(
            guid='{84aebb36-1433-4082-b7ec-29b790d12c17}',
            file_kw={'is_webextension': True})
        addon_factory(
            guid='{0c9970a2-6874-493b-a486-2295cfe251c2}',
            file_kw={'is_webextension': True})
        addon_factory(file_kw={'is_webextension': True})
        call_command('import_blocklist')
        assert Block.objects.count() == 3
        blocks = list(Block.objects.all())
        assert blocks[0].guid == '__TEMPLATE__APPLICATION__@puua-mapa.com'
        assert blocks[1].guid == '{84aebb36-1433-4082-b7ec-29b790d12c17}'
        assert blocks[2].guid == '{0c9970a2-6874-493b-a486-2295cfe251c2}'

    def test_single_guid(self):
        addon_factory(
            guid='{99454877-975a-443e-a0c7-03ab910a8461}',
            file_kw={'is_webextension': True})
        addon_factory(
            guid='Ytarkovpn.5.14@firefox.com',
            file_kw={'is_webextension': True})
        # And random other addon
        addon_factory(file_kw={'is_webextension': True})

        call_command('import_blocklist')
        assert Block.objects.count() == 2
        blocks = list(Block.objects.all())

        assert blocks[0].guid == '{99454877-975a-443e-a0c7-03ab910a8461}'
        assert blocks[0].url == blocklist_json['data'][1]['details']['bug']
        assert blocks[0].reason == blocklist_json['data'][1]['details']['why']
        assert blocks[0].min_version == (
            blocklist_json['data'][1]['versionRange'][0]['minVersion'])
        assert blocks[0].max_version == (
            blocklist_json['data'][1]['versionRange'][0]['maxVersion'])
        assert blocks[0].kinto_id == blocklist_json['data'][1]['id']
        assert blocks[0].include_in_legacy
        assert blocks[0].modified == datetime(2019, 11, 29, 15, 32, 56, 477000)
        assert not blocks[0].is_imported_from_kinto_regex

        assert blocks[1].guid == 'Ytarkovpn.5.14@firefox.com'
        assert blocks[1].url == blocklist_json['data'][2]['details']['bug']
        assert blocks[1].reason == blocklist_json['data'][2]['details']['why']
        assert blocks[1].min_version == (
            blocklist_json['data'][2]['versionRange'][0]['minVersion'])
        assert blocks[1].max_version == (
            blocklist_json['data'][2]['versionRange'][0]['maxVersion'])
        assert blocks[1].kinto_id == blocklist_json['data'][2]['id']
        assert blocks[1].include_in_legacy
        assert blocks[1].modified == datetime(2019, 11, 22, 16, 49, 58, 416000)
        assert not blocks[1].is_imported_from_kinto_regex

        assert KintoImport.objects.count() == 8
        assert KintoImport.objects.filter(
            outcome=KintoImport.OUTCOME_NOMATCH).count() == 5
        kintos = KintoImport.objects.filter(
            outcome=KintoImport.OUTCOME_BLOCK).order_by('created')
        assert kintos.count() == 2
        assert kintos[0].kinto_id == blocks[0].kinto_id
        assert kintos[0].record == blocklist_json['data'][1]
        assert kintos[1].kinto_id == blocks[1].kinto_id
        assert kintos[1].record == blocklist_json['data'][2]

    def test_single_guids_not_webextension(self):
        addon_factory(
            guid='Ytarkovpn.5.14@firefox.com',
            file_kw={'is_webextension': False})
        # And random other addon
        addon_factory(file_kw={'is_webextension': True})

        call_command('import_blocklist')
        assert Block.objects.count() == 0

        assert KintoImport.objects.count() == 8
        assert KintoImport.objects.filter(
            outcome=KintoImport.OUTCOME_NOMATCH).count() == 7

    def test_target_application(self):
        fx_addon = addon_factory(
            guid='mozilla_ccc2.2@inrneg4gdownlomanager.com',
            file_kw={'is_webextension': True})
        # Block only for Thunderbird
        addon_factory(
            guid='{0D2172E4-C3AE-465A-B80D-53F840275B5E}',
            file_kw={'is_webextension': True})
        addon_factory(file_kw={'is_webextension': True})

        call_command('import_blocklist')
        assert Block.objects.count() == 1
        this_block = blocklist_json['data'][5]
        assert (
            this_block['versionRange'][0]['targetApplication'][0]['guid'] ==
            amo.FIREFOX.guid)
        assert Block.objects.get().guid == fx_addon.guid
        assert KintoImport.objects.count() == 8
        assert KintoImport.objects.filter(
            outcome=KintoImport.OUTCOME_NOMATCH).count() == 6
        kinto = KintoImport.objects.get(
            outcome=KintoImport.OUTCOME_REGEXBLOCKS)
        assert kinto.kinto_id == this_block['id']
        assert kinto.record == this_block

    def test_bracket_escaping(self):
        """Some regexs don't escape the {} which is invalid in mysql regex.
        Check we escape it correctly."""
        addon1 = addon_factory(
            guid='{f0af364e-5167-45ca-9cf0-66b396d1918c}',
            file_kw={'is_webextension': True})
        addon2 = addon_factory(
            guid='{01e26e69-a2d8-48a0-b068-87869bdba3d0}',
            file_kw={'is_webextension': True})
        addon_factory(file_kw={'is_webextension': True})

        call_command('import_blocklist')
        assert Block.objects.count() == 2
        blocks = list(Block.objects.all())
        this_block = blocklist_json['data'][3]
        assert blocks[0].guid == addon2.guid
        assert blocks[1].guid == addon1.guid
        # the rest of the metadata should be the same
        for block in blocks:
            assert block.url == this_block['details']['bug']
            assert block.reason == this_block['details']['why']
            assert block.min_version == (
                this_block['versionRange'][0]['minVersion'])
            assert block.max_version == (
                this_block['versionRange'][0]['maxVersion'])
            assert block.kinto_id == '*' + this_block['id']
            assert block.include_in_legacy

    def test_regex_syntax_changed_to_mysql(self):
        """mysql doesn't support /d special charactor, only [:digit:]."""
        addon1 = addon_factory(
            guid='aapbdbdomjkkjkaonfhkkikfgjllcleb@chrome-store-foxified-990648491',  # noqa
            file_kw={'is_webextension': True})
        addon2 = addon_factory(
            guid='aapbdbdomjkkjkaonfhkkikfgjllcleb@chromeStoreFoxified-1006328831',  # noqa
            file_kw={'is_webextension': True})
        addon_factory(file_kw={'is_webextension': True})

        call_command('import_blocklist')
        assert Block.objects.count() == 2
        blocks = list(Block.objects.all())
        assert blocks[0].guid == addon1.guid
        assert blocks[1].guid == addon2.guid

    @mock.patch('olympia.blocklist.management.commands.import_blocklist.'
                'import_block_from_blocklist.delay')
    def test_blocks_are_not_imported_twice(self, import_task_mock):
        addon_factory(guid='{99454877-975a-443e-a0c7-03ab910a8461}')
        addon_factory()
        imported_not_changed = KintoImport.objects.create(
            kinto_id='5d2778e3-cbaa-5192-89f0-5abf3ea10656',
            timestamp=1574441398416)
        imported_and_changed = KintoImport.objects.create(
            kinto_id='9085fdba-8598-46a9-b9fd-4e7343a15c62',
            timestamp=0)
        assert len(blocklist_json['data']) == 8

        call_command('import_blocklist')
        assert import_task_mock.call_count == 7
        assert import_task_mock.call_args_list[0][0] == (
            blocklist_json['data'][0],)
        assert import_task_mock.call_args_list[1][0] == (
            blocklist_json['data'][1],)
        # blocklist_json['data'][2] is the already imported block
        assert imported_not_changed.kinto_id == blocklist_json['data'][2]['id']
        assert import_task_mock.call_args_list[2][0] == (
            blocklist_json['data'][3],)
        assert import_task_mock.call_args_list[3][0] == (
            blocklist_json['data'][4],)
        # we skip over blocklist_json['data'][5] because its done at the end
        assert import_task_mock.call_args_list[4][0] == (
            blocklist_json['data'][6],)
        assert import_task_mock.call_args_list[5][0] == (
            blocklist_json['data'][7],)

        # blocklist_json['data'][5] was already imported but has a different
        # last_modified timestamp so we're processing it again
        assert import_task_mock.call_args_list[6][0] == (
            blocklist_json['data'][5],)
        assert imported_and_changed.kinto_id == blocklist_json['data'][5]['id']

    def test_existing_kinto_import_updates_changes(self):
        # this is the KintoImport from the last time
        existing_import = KintoImport.objects.create(
            kinto_id='029fa6f9-2341-40b7-5443-9a66a057f199',
            timestamp=0)
        # A Block created last time
        existing_block = Block.objects.create(
            addon=addon_factory(
                guid='{bf8194c2-b86d-4ebc-9b53-1c07b6ff779e}',
                file_kw={'is_webextension': True}),
            kinto_id='*029fa6f9-2341-40b7-5443-9a66a057f199',
            min_version='123',
            max_version='456',
            reason='old reason',
            updated_by=self.task_user)
        # Another Block created last time, but not in the current guid regex.
        block_to_be_deleted_id = Block.objects.create(
            addon=addon_factory(file_kw={'is_webextension': True}),
            kinto_id='*029fa6f9-2341-40b7-5443-9a66a057f199',
            min_version='123',
            max_version='456',
            reason='old reason',
            updated_by=self.task_user).id
        # Addon that would match the block guid regex but isn't already a Block
        new_addon = addon_factory(
            guid='{f0af364e-5167-45ca-9cf0-66b396d1918c}',
            file_kw={'is_webextension': True})
        # And this is a KintoImport from last time but has been deleted from v2
        KintoImport.objects.create(
            kinto_id='1234567890', timestamp=0)
        # And a block that was created last time from that import
        Block.objects.create(
            guid='something@',
            kinto_id='1234567890', updated_by=self.task_user)
        assert Block.objects.all().count() == 3
        assert KintoImport.objects.filter(
            kinto_id='029fa6f9-2341-40b7-5443-9a66a057f199').exists()
        assert KintoImport.objects.filter(
            kinto_id='1234567890').exists()

        call_command('import_blocklist')

        assert Block.objects.all().count() == 2
        # existing block is still there, but updated
        existing_block.reload()
        assert Block.objects.all()[0] == existing_block
        assert existing_block.min_version == '0'
        assert existing_block.max_version == '*'
        assert existing_block.reason.startswith('The installer that includes ')
        # Obsolete block is gone
        assert not Block.objects.filter(id=block_to_be_deleted_id).exists()
        # And new block has been added
        assert Block.objects.all()[1].guid == new_addon.guid

        existing_import.reload()
        assert existing_import.timestamp != 0

        assert not KintoImport.objects.filter(kinto_id='1234567890').exists()
        assert not Block.objects.filter(kinto_id='1234567890').exists()


class TestExportBlocklist(TestCase):

    def test_command(self):
        for idx in range(0, 5):
            addon_factory()
        # one version, 0 - *
        Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())
        # one version, 0 - 9999
        Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory(),
            max_version='9999')
        # one version, 0 - *, unlisted
        Block.objects.create(
            addon=addon_factory(
                version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())

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
        assert Block.objects.last().guid == (
            '{0020bd71-b1ba-4295-86af-db7f4e7eaedc}')

        addon_factory(guid='{00116dc4-ba1f-42c5-b20c-da7f743f7377}')
        call_command(
            'bulk_add_blocks', guids_input=guids_path, min_version='44')
        # The guid before shouldn't be added twice
        # assert Block.objects.count() == 2
        prev_block = Block.objects.first()
        assert prev_block.guid == '{0020bd71-b1ba-4295-86af-db7f4e7eaedc}'
        assert prev_block.min_version == '44'
        new_block = Block.objects.last()
        assert new_block.guid == '{00116dc4-ba1f-42c5-b20c-da7f743f7377}'
        assert new_block.min_version == '44'
