from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.legacy_api.utils import find_compatible_version


class TestCompatibleVersion(TestCase):
    def test_compatible_version(self):
        addon = addon_factory()
        version = version_factory(addon=addon, version='99')
        version_factory(
            addon=addon, version='100',
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert find_compatible_version(addon, amo.FIREFOX.id) == version
