from olympia.amo.tests import TestCase
from olympia.versions.compare import MAX_VERSION_PART

from ..models import Block


class TestBlock(TestCase):
    def test_is_version_blocked(self):
        block = Block.objects.create(guid='anyguid@')
        # default is 0 to *
        assert block.is_version_blocked('0')
        assert block.is_version_blocked(str(MAX_VERSION_PART + 1))

        # Now with some restricted version range
        block.update(min_version='2.0')
        assert not block.is_version_blocked('1')
        assert not block.is_version_blocked('2.0b1')
        assert block.is_version_blocked('2')
        assert block.is_version_blocked('3')
        assert block.is_version_blocked(str(MAX_VERSION_PART + 1))
        block.update(max_version='10.*')
        assert not block.is_version_blocked('11')
        assert not block.is_version_blocked(str(MAX_VERSION_PART + 1))
        assert block.is_version_blocked('10')
        assert block.is_version_blocked('9')
        assert block.is_version_blocked('10.1')
        assert block.is_version_blocked('10.%s' % (MAX_VERSION_PART +1))
