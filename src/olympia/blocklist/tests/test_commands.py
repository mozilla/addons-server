import os
import json
from datetime import datetime
from unittest import mock

from django.core.management import call_command
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
    blocklist_json = json.loads(file_object.read())


class TestImportBlocklist(TestCase):

    def setUp(self):
        responses.add(
            responses.GET,
            import_blocklist.Command.KINTO_JSON_BLOCKLIST_URL,
            json=blocklist_json)
        self.task_user = user_factory(id=settings.TASK_USER_ID)
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
        imported = KintoImport.objects.create(
            kinto_id='5d2778e3-cbaa-5192-89f0-5abf3ea10656')
        assert len(blocklist_json['data']) == 8

        call_command('import_blocklist')
        assert import_task_mock.call_count == 7
        assert import_task_mock.call_args_list[0][0] == (
            blocklist_json['data'][0],)
        assert import_task_mock.call_args_list[1][0] == (
            blocklist_json['data'][1],)
        # blocklist_json['data'][2] is the already imported block
        assert imported.kinto_id == blocklist_json['data'][2]['id']
        assert import_task_mock.call_args_list[2][0] == (
            blocklist_json['data'][3],)
        assert import_task_mock.call_args_list[3][0] == (
            blocklist_json['data'][4],)
        assert import_task_mock.call_args_list[4][0] == (
            blocklist_json['data'][5],)


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
        out_path = os.path.join(settings.MLBF_STORAGE_PATH, '1.filter')
        assert os.path.exists(out_path)
