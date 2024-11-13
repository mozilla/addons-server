from django.core.management import call_command

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)
from olympia.blocklist.mlbf import MLBF
from olympia.blocklist.models import BlockType


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

        call_command('export_blocklist', '1', '--block-type', BlockType.BLOCKED.name)
        mlbf = MLBF.load_from_storage(1)
        assert mlbf.storage.exists(mlbf.filter_path(BlockType.BLOCKED))
        call_command(
            'export_blocklist', '1', '--block-type', BlockType.SOFT_BLOCKED.name
        )
        mlbf = MLBF.load_from_storage(1)
        assert mlbf.storage.exists(mlbf.filter_path(BlockType.SOFT_BLOCKED))
