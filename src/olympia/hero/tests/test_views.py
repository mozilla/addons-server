import json

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import addon_factory, TestCase, reverse_ns
from olympia.promoted.models import PromotedAddon

from ..models import PrimaryHero, SecondaryHero, SecondaryHeroModule
from ..serializers import (
    PrimaryHeroShelfSerializer, SecondaryHeroShelfSerializer)


class TestPrimaryHeroShelfViewSet(TestCase):
    def setUp(self):
        self.url = reverse_ns('hero-primary-list', api_version='v5')

    def test_basic(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {'results': []}

        hero_a = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory()),
            description='Its a déscription!',
            image='foo.png',
            gradient_color='#123456')
        hero_b = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(summary='fooo')),
            image='baa.png',
            gradient_color='#987654')
        hero_external = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(homepage='https://mozilla.org/')),
            image='external.png',
            gradient_color='#FABFAB',
            is_external=True)
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory()),
            image='wah.png',
            gradient_color='#989898')

        # The shelves aren't enabled so still won't show up
        response = self.client.get(self.url)
        assert response.json() == {'results': []}

        hero_a.update(enabled=True)
        hero_b.update(enabled=True)
        hero_external.update(enabled=True)
        # don't enable the 3rd PrimaryHero object
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
            # - 1 to fetch the add-ons version previews (for static themes)
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
            absolutify(hero_a.promoted_addon.addon.get_detail_url()))
        assert response.json()['results'][2]['external']['homepage'] == {
            'en-US': 'https://mozilla.org/'
        }

    def test_outgoing_wrapper(self):
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(homepage='https://mozilla.org/')),
            image='external.png',
            gradient_color='#FABFAB',
            is_external=True,
            enabled=True)
        response = self.client.get(self.url, {'lang': 'en-US'})
        # We don't wrap links with outgoing by default
        assert b'outgoing.' not in response.content
        # But they should be if the param is passed.
        response = self.client.get(
            self.url, {'lang': 'en-US', 'wrap_outgoing_links': ''})
        assert b'outgoing.' in response.content

    def test_all_param(self):
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory()),
            image='wah.png',
            gradient_color='#989898',
            enabled=True)
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory()),
            image='wah.png',
            gradient_color='#989898',
            enabled=True)
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory()),
            image='wah.png',
            gradient_color='#989898',
            enabled=False)

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.json()['results']) == 2

        response = self.client.get(self.url + '?all=true')
        assert response.status_code == 200
        assert len(response.json()['results']) == 3

    def test_raw_param(self):
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(summary='addon')),
            image='wah.png',
            gradient_color='#989898',
            enabled=True)
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory()),
            description='hero',
            image='wah.png',
            gradient_color='#989898',
            enabled=True)
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(summary=None)),
            image='wah.png',
            gradient_color='#989898',
            enabled=True)

        response = self.client.get(self.url)
        assert response.status_code == 200
        results = response.json()['results']
        assert len(results) == 3
        assert results[0]['description'] == 'addon'
        assert results[1]['description'] == 'hero'
        assert results[2]['description'] == ''

        response = self.client.get(self.url + '?raw')
        assert response.status_code == 200
        results = response.json()['results']
        assert len(results) == 3
        assert results[0]['description'] == ''
        assert results[1]['description'] == 'hero'
        assert results[2]['description'] == ''


class TestSecondaryHeroShelfViewSet(TestCase):
    def setUp(self):
        self.url = reverse_ns('hero-secondary-list', api_version='v5')

    def test_basic(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {'results': []}

        hero_a = SecondaryHero.objects.create(
            headline='Its a héadline!',
            description='foo')
        hero_b = SecondaryHero.objects.create(
            headline='%^*',
            description='',
            cta_url='http://goo.gl',
            cta_text='goozilla')
        SecondaryHero.objects.create(
            headline='dfdfd!',
            description='dfdfd')
        SecondaryHeroModule.objects.create(shelf=hero_a)
        SecondaryHeroModule.objects.create(shelf=hero_a)
        SecondaryHeroModule.objects.create(shelf=hero_a)

        # The shelves aren't enabled so won't show up.
        response = self.client.get(self.url)
        assert response.json() == {'results': []}

        hero_a.update(enabled=True)
        hero_b.update(enabled=True)
        # don't enable the 3rd PrimaryHero object
        with self.assertNumQueries(2):
            # 2 queries:
            # - 1 to fetch all SecondaryHero results
            # - 1 to fetch all the SecondaryHeroModules
            response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            'results': [
                SecondaryHeroShelfSerializer(instance=hero_a).data,
                SecondaryHeroShelfSerializer(instance=hero_b).data]}

    def test_outgoing_wrapper(self):
        hero = SecondaryHero.objects.create(
            headline='%^*',
            description='',
            cta_url='/addon/adblockplus/',
            cta_text='goozilla',
            enabled=True)
        # No outgoing wrapping by default
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert b'outgoing.' not in response.content
        response = self.client.get(
            self.url, {'lang': 'en-US', 'wrap_outgoing_links': ''})
        # But we also don't want to wrap internal urls
        assert b'outgoing.' not in response.content
        assert b'http://testserver' in response.content

        # update the cta to an external url - test the no wrap param case first
        hero.update(cta_url='http://goo.gl')
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert b'outgoing.' not in response.content
        response = self.client.get(
            self.url, {'lang': 'en-US', 'wrap_outgoing_links': ''})
        # This time it should be wrapped
        assert b'outgoing.' in response.content

    def test_all_param(self):
        SecondaryHero.objects.create(
            headline='dfdfd!',
            description='dfdfd',
            enabled=True)
        SecondaryHero.objects.create(
            headline='dfdfd!',
            description='dfdfd',
            enabled=True)
        SecondaryHero.objects.create(
            headline='dfdfd!',
            description='dfdfd',
            enabled=False)

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.json()['results']) == 2

        response = self.client.get(self.url + '?all=true')
        assert response.status_code == 200
        assert len(response.json()['results']) == 3


class TestHeroShelvesView(TestCase):
    def setUp(self):
        self.url = reverse_ns('hero-shelves', api_version='v5')

    def test_basic(self):
        phero = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            enabled=True)
        shero = SecondaryHero.objects.create(
            headline='headline', description='description',
            enabled=True)
        SecondaryHeroModule.objects.create(shelf=shero)
        SecondaryHeroModule.objects.create(shelf=shero)
        SecondaryHeroModule.objects.create(shelf=shero)

        with self.assertNumQueries(13):
            # 13 queries:
            # - 11 as TestPrimaryHeroShelfViewSet.test_basic above
            # - 2 as TestSecondaryHeroShelfViewSet.test_basic above
            response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.status_code == 200
        assert response.json() == {
            'primary': PrimaryHeroShelfSerializer(instance=phero).data,
            'secondary': SecondaryHeroShelfSerializer(instance=shero).data,
        }

    def test_outgoing_wrapper(self):
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(homepage='http://foo.baa')),
            enabled=True, is_external=True)
        SecondaryHero.objects.create(
            headline='headline', description='description',
            cta_url='http://go.here/', cta_text='go here!',
            enabled=True)
        response = self.client.get(
            self.url, {'lang': 'en-US', 'wrap_outgoing_links': ''})
        assert 'outgoing.' in json.dumps(response.json()['primary'])
        assert 'outgoing.' in json.dumps(response.json()['secondary'])

    def test_shelf_randomness(self):
        addon_1 = addon_factory()
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_1),
            enabled=True)
        addon_2 = addon_factory()
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_2),
            enabled=True)
        addon_3 = addon_factory()
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_3),
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
