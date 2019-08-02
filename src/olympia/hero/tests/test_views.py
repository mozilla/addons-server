from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import addon_factory, TestCase, reverse_ns
from olympia.discovery.models import DiscoveryItem

from ..models import PrimaryHero
from ..serializers import PrimaryHeroShelfSerializer


class TestPrimaryHeroShelfViewSet(TestCase):
    def setUp(self):
        self.url = reverse_ns('hero-primary-list', api_version='v5')

    def test_basic(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {'results': []}

        hero_a = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(
                addon=addon_factory(),
                custom_heading='Its a héading!'),
            image='foo.png',
            gradient_color='#123456')
        hero_b = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(
                addon=addon_factory()),
            image='baa.png',
            gradient_color='#987654')
        hero_external = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(
                addon=addon_factory(homepage='https://mozilla.org/')),
            image='external.png',
            gradient_color='#FABFAB',
            is_external=True)

        # The shelf isn't enabled so still won't show up
        response = self.client.get(self.url)
        assert response.json() == {'results': []}

        PrimaryHero.objects.update(enabled=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            'results': [
                PrimaryHeroShelfSerializer(instance=hero_a).data,
                PrimaryHeroShelfSerializer(instance=hero_b).data,
                PrimaryHeroShelfSerializer(instance=hero_external).data]}
        # double check the different serializer representations
        assert response.json()['results'][0]['addon']['url'] == (
            absolutify(hero_a.disco_addon.addon.get_detail_url()))
        assert response.json()['results'][2]['external']['homepage'] == {
            'en-US': 'https://mozilla.org/'
        }


class TestHeroShelvesView(TestCase):
    def setUp(self):
        self.url = reverse_ns('hero-shelves', api_version='v5')

    def test_basic(self):
        hero = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon_factory()),
            enabled=True)

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            'primary': PrimaryHeroShelfSerializer(instance=hero).data,
        }

    def test_shelf_randomness(self):
        addon_1 = addon_factory()
        PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon_1),
            enabled=True)
        addon_2 = addon_factory()
        PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon_2),
            enabled=True)
        addon_3 = addon_factory()
        PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon_3),
            enabled=True)
        addon_ids = {addon_1.id, addon_2.id, addon_3.id}

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()['primary']['addon']['id'] in addon_ids

        found_ids = set()
        # check its not just returning the same add-on each time
        for count in range(0, 19):
            response = self.client.get(self.url)
            found_ids.add(response.json()['primary']['addon']['id'])
            if len(found_ids) == 3:
                break

        assert found_ids == addon_ids
