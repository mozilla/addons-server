from django.test.utils import override_settings

from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.amo.urlresolvers import get_outgoing_url

from ..models import Block, BlockVersion
from ..serializers import BlockSerializer


class TestBlockSerializer(TestCase):
    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.block = Block.objects.create(
            guid='foo@baa',
            reason='something happened',
            url='https://goo.gol',
            updated_by=user_factory(),
        )

    def test_basic_no_addon(self):
        expected = {
            'id': self.block.id,
            'addon_name': None,
            'guid': 'foo@baa',
            'reason': 'something happened',
            'blocked': [],
            'soft_blocked': [],
            'url': {
                'url': 'https://goo.gol',
                'outgoing': get_outgoing_url('https://goo.gol'),
            },
            'is_all_versions': True,
            'created': self.block.created.isoformat()[:-7] + 'Z',
            'modified': self.block.modified.isoformat()[:-7] + 'Z',
        }
        serializer = BlockSerializer(context={'request': self.request})
        assert serializer.to_representation(self.block) == expected

        with override_settings(DRF_API_GATES={None: ('block-min-max-versions-shim',)}):
            assert serializer.to_representation(self.block) == {
                **expected,
                'min_version': '0',
                'max_version': '*',
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
        version_6 = version_factory(addon=addon, version='123456')
        BlockVersion.objects.create(block=self.block, version=version_2)
        BlockVersion.objects.create(block=self.block, version=version_4)
        BlockVersion.objects.create(block=self.block, version=version_6, soft=True)

        expected = {
            'id': self.block.id,
            'addon_name': {'en-US': 'Addón náme'},
            'guid': 'foo@baa',
            'reason': 'something happened',
            'url': {
                'url': 'https://goo.gol',
                'outgoing': get_outgoing_url('https://goo.gol'),
            },
            'blocked': [version_2.version, version_4.version],
            'soft_blocked': [version_6.version],
            'is_all_versions': False,
            'created': self.block.created.isoformat()[:-7] + 'Z',
            'modified': self.block.modified.isoformat()[:-7] + 'Z',
        }
        serializer = BlockSerializer(context={'request': self.request})
        assert serializer.to_representation(self.block) == expected

        with override_settings(DRF_API_GATES={None: ('block-min-max-versions-shim',)}):
            assert serializer.to_representation(self.block) == {
                **expected,
                'min_version': version_2.version,
                'max_version': version_4.version,
            }
        with override_settings(DRF_API_GATES={None: ('block-versions-list-shim',)}):
            assert serializer.to_representation(self.block) == {
                **expected,
                'versions': expected['blocked'],
            }

    def test_is_all_versions(self):
        # no add-on so True
        assert BlockSerializer(instance=self.block).data['is_all_versions'] is True

        addon = addon_factory(
            guid=self.block.guid, name='Addón náme', file_kw={'is_signed': True}
        )
        BlockVersion.objects.create(
            block=self.block, version=addon.current_version, soft=False
        )
        BlockVersion.objects.create(
            block=self.block, version=version_factory(addon=addon), soft=True
        )
        version_factory(addon=addon, file_kw={'is_signed': False})  # not signed
        self.block.refresh_from_db()
        del self.block.addon
        # add-on with only two signed versions - so all blocked - but not disabled
        assert BlockSerializer(instance=self.block).data['is_all_versions'] is False

        addon.update(status=amo.STATUS_DISABLED)
        del self.block.addon
        # now the add-on is disabled with all signed versions blocked
        assert BlockSerializer(instance=self.block).data['is_all_versions'] is True

        # but if there was another signed version, even deleted on a deleted addon...
        old_addon = addon_factory(file_kw={'is_signed': True})
        old_addon.current_version.delete()
        old_addon.delete()
        old_addon.addonguid.update(guid=addon.guid)
        # ... the guid isn't completely blocked
        assert BlockSerializer(instance=self.block).data['is_all_versions'] is False
