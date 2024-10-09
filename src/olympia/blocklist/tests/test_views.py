from django.test.utils import override_settings

from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    reverse_ns,
    user_factory,
)
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.blocklist.serializers import BlockSerializer


class TestBlockViewSet(TestCase):
    def setUp(self):
        self.addon = addon_factory(
            guid='foo@baa.com', name='English name', default_locale='en-CA'
        )
        self.block = block_factory(
            addon=self.addon,
            reason='something happened',
            url='https://goo.gol',
            updated_by=user_factory(),
        )
        self.url = reverse_ns(
            'blocklist-block-detail',
            api_version='v5',
            args=(str(self.block.guid),),
        )

    def test_get_pk(self):
        self.url = reverse_ns(
            'blocklist-block-detail', api_version='v5', args=(str(self.block.id),)
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        serialized = BlockSerializer(instance=self.block).data
        assert response.json() == {**serialized, 'versions': serialized['blocked']}

    def test_get_guid(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        serialized = BlockSerializer(instance=self.block).data
        assert response.json() == {**serialized, 'versions': serialized['blocked']}

    def test_v4_shims(self):
        id_url = reverse_ns(
            'blocklist-block-detail', api_version='v4', args=(str(self.block.id),)
        )
        response = self.client.get(id_url)
        assert response.status_code == 200
        serialized = BlockSerializer(instance=self.block).data
        expected = {
            **serialized,
            'versions': serialized['blocked'],
            'min_version': self.addon.current_version.version,
            'max_version': self.addon.current_version.version,
            'url': serialized['url']['url'],
        }
        assert response.json() == expected

        guid_url = reverse_ns(
            'blocklist-block-detail', api_version='v4', args=(str(self.addon.guid),)
        )
        response = self.client.get(guid_url)
        assert response.status_code == 200
        assert response.json() == expected

    def test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()['url'] == {
            'url': self.block.url,
            'outgoing': get_outgoing_url(self.block.url),
        }

    def test_addon_name(self):
        self.addon.name = {'fr': 'Lé name Francois'}
        self.addon.save()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()['addon_name'] == {
            'en-CA': 'English name',
            'fr': 'Lé name Francois',
        }

        url = self.url + '?lang=de-DE'
        response = self.client.get(url)
        assert response.json()['addon_name'] == {
            'en-CA': 'English name',
            'de-DE': None,
            '_default': 'en-CA',
        }
        assert list(response.json()['addon_name'])[0] == 'en-CA'

        overridden_api_gates = {'v5': ('l10n_flat_input_output',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            response = self.client.get(url)
        assert response.json()['addon_name'] == 'English name'
