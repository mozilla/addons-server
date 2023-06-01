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


class TestExportBlocklist(TestCase):
    def test_command(self):
        for _idx in range(0, 5):
            addon_factory()
        # all versions
        block_factory(
            addon=addon_factory(file_kw={'is_signed': True}),
            updated_by=user_factory(),
        )
        # one version
        one = block_factory(
            addon=addon_factory(file_kw={'is_signed': True}),
            updated_by=user_factory(),
        )
        version_factory(addon=one.addon)
        # all versions, unlisted
        block_factory(
            addon=addon_factory(
                version_kw={'channel': amo.CHANNEL_UNLISTED},
                file_kw={'is_signed': True},
            ),
            updated_by=user_factory(),
        )

        call_command('export_blocklist', '1')
        out_path = os.path.join(settings.MLBF_STORAGE_PATH, '1', 'filter')
        assert os.path.exists(out_path)
