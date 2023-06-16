from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.amo.urlresolvers import get_outgoing_url

from ..models import Block, BlockVersion
from ..serializers import BlockSerializer


class TestBlockSerializer(TestCase):
    def setUp(self):
        self.block = Block.objects.create(
            guid='foo@baa',
            reason='something happened',
            url='https://goo.gol',
            updated_by=user_factory(),
        )

    def test_basic_no_addon(self):
        serializer = BlockSerializer(instance=self.block)
        assert serializer.data == {
            'id': self.block.id,
            'addon_name': None,
            'guid': 'foo@baa',
            'min_version': '',
            'max_version': '',
            'reason': 'something happened',
            'url': {
                'url': 'https://goo.gol',
                'outgoing': get_outgoing_url('https://goo.gol'),
            },
            'versions': [],
            'created': self.block.created.isoformat()[:-7] + 'Z',
            'modified': self.block.modified.isoformat()[:-7] + 'Z',
        }

    def test_with_addon(self):
        addon = addon_factory(
            guid=self.block.guid, name='Addón náme', version_kw={'version': '1.0'}
        )
        _version_1 = addon.current_version
        _version_5 = version_factory(addon=addon, version='5555')
        version_2 = version_factory(
            addon=addon, channel=amo.CHANNEL_UNLISTED, version='2.0.2'
        )
        version_4 = version_factory(addon=addon, version='4')
        _version_3 = version_factory(addon=addon, version='3b1')
        BlockVersion.objects.create(block=self.block, version=version_2)
        BlockVersion.objects.create(block=self.block, version=version_4)

        serializer = BlockSerializer(instance=self.block)
        assert serializer.data == {
            'id': self.block.id,
            'addon_name': {'en-US': 'Addón náme'},
            'guid': 'foo@baa',
            'min_version': version_2.version,
            'max_version': version_4.version,
            'reason': 'something happened',
            'url': {
                'url': 'https://goo.gol',
                'outgoing': get_outgoing_url('https://goo.gol'),
            },
            'versions': [version_2.version, version_4.version],
            'created': self.block.created.isoformat()[:-7] + 'Z',
            'modified': self.block.modified.isoformat()[:-7] + 'Z',
        }
