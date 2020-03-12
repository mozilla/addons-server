from rest_framework.test import APIRequestFactory

from olympia.amo.tests import TestCase, user_factory
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.blocklist.models import Block
from olympia.blocklist.serializers import BlockSerializer


class TestBlockSerializer(TestCase):
    def test_basic(self):
        block = Block.objects.create(
            guid='foo@baa',
            min_version='45',
            reason='something happened',
            url='https://goo.gol',
            updated_by=user_factory())
        serializer = BlockSerializer(instance=block)
        assert serializer.data == {
            'id': block.id,
            'guid': 'foo@baa',
            'min_version': '45',
            'max_version': '*',
            'reason': 'something happened',
            'url': 'https://goo.gol',
            'created': block.created.isoformat()[:-7] + 'Z',
            'modified': block.modified.isoformat()[:-7] + 'Z',
        }

    def test_wrap_outgoing_links(self):
        block = Block.objects.create(
            guid='foo@baa',
            min_version='45',
            reason='something happened',
            url='https://goo.gol',
            updated_by=user_factory())
        request = APIRequestFactory().get('/', {'wrap_outgoing_links': 1})
        serializer = BlockSerializer(
            instance=block, context={'request': request})

        assert serializer.data['url'] == get_outgoing_url(block.url)
