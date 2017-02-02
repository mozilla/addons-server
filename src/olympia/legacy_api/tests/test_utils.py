from olympia import amo
from olympia.amo.tests import addon_factory, TestCase, version_factory
from olympia.legacy_api.utils import find_compatible_version


class TestCompatibleVersion(TestCase):
    def test_compatible_version(self):
        addon = addon_factory()
        version = version_factory(
            addon=addon,
            status=amo.STATUS_PUBLIC, version='99')
        version_factory(
            addon=addon, status=amo.STATUS_PUBLIC, version='100',
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert find_compatible_version(addon, amo.FIREFOX.id) == version
