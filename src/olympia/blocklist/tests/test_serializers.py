from rest_framework.test import APIRequestFactory

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
            updated_by=user_factory())

    def test_basic_no_addon(self):
        serializer = BlockSerializer(instance=self.block)
        assert serializer.data == {
            'id': self.block.id,
            'addon_name': None,
            'guid': 'foo@baa',
            'min_version': '45',
            'max_version': '*',
            'reason': 'something happened',
            'url': 'https://goo.gol',
            'created': self.block.created.isoformat()[:-7] + 'Z',
            'modified': self.block.modified.isoformat()[:-7] + 'Z',
        }

    def test_with_addon(self):
        addon_factory(guid=self.block.guid, name='Addón náme')
        serializer = BlockSerializer(instance=self.block)
        assert serializer.data['addon_name'] == {
            'en-US': 'Addón náme'}

    def test_wrap_outgoing_links(self):
        request = APIRequestFactory().get('/', {'wrap_outgoing_links': 1})
        serializer = BlockSerializer(
            instance=self.block, context={'request': request})

        assert serializer.data['url'] == get_outgoing_url(self.block.url)

        self.block.update(url='')
        serializer = BlockSerializer(
            instance=self.block, context={'request': request})
        assert serializer.data['url'] == ''
