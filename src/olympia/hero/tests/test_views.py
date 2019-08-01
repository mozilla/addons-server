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
        with self.assertNumQueries(11):
            # 11 queries:
            # - 1 to fetch the primaryhero/discoveryitem items
            # - 1 to fetch the add-ons (can't be joined with the previous one
            #   because we want to hit the Addon transformer)
            # - 1 to fetch add-ons translations
            # - 1 to fetch add-ons categories
            # - 1 to fetch add-ons current_version
            # - 1 to fetch the versions translations
            # - 1 to fetch the versions applications_versions
            # - 1 to fetch the versions files
            # - 1 to fetch the add-ons authors
            # - 1 to fetch the add-ons personas
            # - 1 to fetch the add-ons previews
            response = self.client.get(self.url, {'lang': 'en-US'})
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

        with self.assertNumQueries(11):
            # 11 queries:
            # - 1 to fetch the primaryhero/discoveryitem items
            # - 1 to fetch the add-ons (can't be joined with the previous one
            #   because we want to hit the Addon transformer)
            # - 1 to fetch add-ons translations
            # - 1 to fetch add-ons categories
            # - 1 to fetch add-ons current_version
            # - 1 to fetch the versions translations
            # - 1 to fetch the versions applications_versions
            # - 1 to fetch the versions files
            # - 1 to fetch the add-ons authors
            # - 1 to fetch the add-ons personas
            # - 1 to fetch the add-ons previews
            response = self.client.get(self.url, {'lang': 'en-US'})
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
