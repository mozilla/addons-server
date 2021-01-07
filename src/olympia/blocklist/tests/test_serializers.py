from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.blocklist.models import Block
from olympia.blocklist.serializers import BlockSerializer


class TestBlockSerializer(TestCase):
    def setUp(self):
        self.block = Block.objects.create(
            guid='foo@baa',
            min_version='45',
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
            'min_version': '45',
            'max_version': '*',
            'reason': 'something happened',
            'url': {
                'url': 'https://goo.gol',
                'outgoing': get_outgoing_url('https://goo.gol'),
            },
            'created': self.block.created.isoformat()[:-7] + 'Z',
            'modified': self.block.modified.isoformat()[:-7] + 'Z',
        }

    def test_with_addon(self):
        addon_factory(guid=self.block.guid, name='Addón náme')
        serializer = BlockSerializer(instance=self.block)
        assert serializer.data['addon_name'] == {'en-US': 'Addón náme'}
