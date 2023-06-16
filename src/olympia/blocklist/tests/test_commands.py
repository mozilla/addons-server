import os

from django.conf import settings
from django.core.management import call_command

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)

from ..models import Block, BlockVersion


class TestExportBlocklist(TestCase):
    def test_command(self):
        user = user_factory()
        for _idx in range(0, 5):
            addon_factory()
        # all versions
        block_factory(
            addon=addon_factory(file_kw={'is_signed': True}),
            updated_by=user,
        )
        # one version
        one = block_factory(
            addon=addon_factory(file_kw={'is_signed': True}),
            updated_by=user,
        )
        version_factory(addon=one.addon)
        # all versions, unlisted
        block_factory(
            addon=addon_factory(
                version_kw={'channel': amo.CHANNEL_UNLISTED},
                file_kw={'is_signed': True},
            ),
            updated_by=user,
        )

        call_command('export_blocklist', '1')
        out_path = os.path.join(settings.MLBF_STORAGE_PATH, '1', 'filter')
        assert os.path.exists(out_path)


class TestCreateBlockversions(TestCase):
    def test_command(self):
        user = user_factory()
        Block.objects.create(guid='missing@', min_version='123', updated_by=user)
        addon = addon_factory(version_kw={'version': '0.1'})
        v1 = version_factory(addon=addon, version='1')
        v2 = version_factory(addon=addon, version='2.0.0')
        v2.delete()
        minmax_block = Block.objects.create(
            addon=addon, min_version='0.1.1', max_version='2', updated_by=user
        )
        full_block = Block.objects.create(addon=addon_factory(), updated_by=user)

        call_command('create_blockversions')

        assert BlockVersion.objects.count() == 3
        v1.refresh_from_db()
        v2.refresh_from_db()
        full_block.refresh_from_db()
        assert v1.blockversion.block == minmax_block
        assert v2.blockversion.block == minmax_block
        assert full_block.addon.current_version.blockversion.block == full_block

        # we can run it again without a problem
        call_command('create_blockversions')
        assert BlockVersion.objects.count() == 3

        # and extra versions / blocks are created
        new_version = version_factory(
            addon=addon, channel=amo.CHANNEL_UNLISTED, version='0.2'
        )
        new_block = Block.objects.create(addon=addon_factory(), updated_by=user)

        call_command('create_blockversions')

        assert BlockVersion.objects.count() == 5
        new_block.refresh_from_db()
        new_version.refresh_from_db()
        assert new_version.blockversion.block == minmax_block
        assert new_block.addon.current_version.blockversion.block == new_block
