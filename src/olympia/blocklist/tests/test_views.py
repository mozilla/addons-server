from django.test.utils import override_settings

from olympia.amo.tests import addon_factory, reverse_ns, TestCase, user_factory
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.blocklist.models import Block
from olympia.blocklist.serializers import BlockSerializer


class TestBlockViewSet(TestCase):
    def setUp(self):
        self.block = Block.objects.create(
            guid='foo@baa.com',
            min_version='45',
            reason='something happened',
            url='https://goo.gol',
            updated_by=user_factory())

    def test_get_pk(self):
        url = reverse_ns('blocklist-block-detail', args=(str(self.block.id),))
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json() == BlockSerializer(instance=self.block).data

    def test_get_guid(self):
        url = reverse_ns('blocklist-block-detail', args=(self.block.guid,))
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json() == BlockSerializer(instance=self.block).data

    def test_wrap_outgoing_links(self):
        url = reverse_ns('blocklist-block-detail', args=(self.block.guid,))
        response = self.client.get(url + '?wrap_outgoing_links')
        assert response.status_code == 200
        assert response.json()['url'] == get_outgoing_url(self.block.url)

    def test_addon_name(self):
        url = reverse_ns(
            'blocklist-block-detail',
            args=(self.block.guid,),
            api_version='v5')
        addon = addon_factory(
            guid=self.block.guid,
            name='English name',
            default_locale='en-CA')
        addon.name = {'fr': 'Lé name Francois'}
        addon.save()
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json()['addon_name'] == {
            'en-CA': 'English name',
            'fr': 'Lé name Francois'}

        url += '?lang=de-DE'
        response = self.client.get(url)
        assert response.json()['addon_name'] == {'en-CA': 'English name'}

        overridden_api_gates = {
            'v5': ('l10n_flat_input_output',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            response = self.client.get(url)
        assert response.json()['addon_name'] == 'English name'
