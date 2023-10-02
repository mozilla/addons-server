import json

from django.test.utils import override_settings

from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, reverse_ns
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.promoted.models import PromotedAddon

from ..models import PrimaryHero, PrimaryHeroImage, SecondaryHero, SecondaryHeroModule
from ..serializers import PrimaryHeroShelfSerializer, SecondaryHeroShelfSerializer


class TestPrimaryHeroShelfViewSet(TestCase):
    def setUp(self):
        self.url = reverse_ns('hero-primary-list', api_version='v5')
        uploaded_photo_1 = get_uploaded_file('animated.png')
        uploaded_photo_2 = get_uploaded_file('non-animated.png')
        uploaded_photo_3 = get_uploaded_file('preview_4x3.jpg')
        uploaded_photo_4 = get_uploaded_file('transparent.png')

        self.phi_a = PrimaryHeroImage.objects.create(custom_image=uploaded_photo_1)
        self.phi_b = PrimaryHeroImage.objects.create(custom_image=uploaded_photo_2)
        self.phi_c = PrimaryHeroImage.objects.create(custom_image=uploaded_photo_3)
        self.phi_d = PrimaryHeroImage.objects.create(custom_image=uploaded_photo_4)

    def test_basic(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {'results': []}

        hero_a = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            description='Its a déscription!',
            select_image=self.phi_a,
            gradient_color='#123456',
        )
        hero_b = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(summary='fooo')
            ),
            select_image=self.phi_b,
            gradient_color='#987654',
        )
        hero_external = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(homepage='https://mozilla.org/')
            ),
            select_image=self.phi_c,
            gradient_color='#FABFAB',
            is_external=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            select_image=self.phi_d,
            gradient_color='#989898',
        )

        # The shelves aren't enabled so still won't show up
        response = self.client.get(self.url)
        assert response.json() == {'results': []}

        # We'll need a fake request with the right api version to pass to the
        # serializers to compare the data, so that the right API gates are
        # active.
        request = APIRequestFactory().get('/')
        request.version = api_settings.DEFAULT_VERSION

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
            # - 1 to fetch add-ons current_version + file
            # - 1 to fetch the versions translations
            # - 1 to fetch the versions applications_versions
            # - 1 to fetch the add-ons authors
            # - 1 to fetch the add-ons version previews (for static themes)
            # - 1 to fetch the add-ons previews
            # - 1 to fetch the permissions for the files
            response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.status_code == 200
        assert response.json() == {
            'results': [
                PrimaryHeroShelfSerializer(
                    instance=hero_a, context={'request': request}
                ).data,
                PrimaryHeroShelfSerializer(
                    instance=hero_b, context={'request': request}
                ).data,
                PrimaryHeroShelfSerializer(
                    instance=hero_external, context={'request': request}
                ).data,
            ]
        }
        results = response.json()['results']
        # double check the different serializer representations
        assert results[0]['addon']['url'] == (
            absolutify(hero_a.promoted_addon.addon.get_detail_url())
        )
        assert results[2]['external']['homepage']['url'] == {
            'en-US': 'https://mozilla.org/'
        }
        assert 'outgoing.' in (results[2]['external']['homepage']['outgoing']['en-US'])

    @override_settings(DRF_API_GATES={'v5': ('wrap-outgoing-parameter',)})
    def test_outgoing_wrapper_gate(self):
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(homepage='https://mozilla.org/')
            ),
            select_image=self.phi_a,
            gradient_color='#FABFAB',
            is_external=True,
            enabled=True,
        )
        response = self.client.get(self.url, {'lang': 'en-US'})
        # We don't wrap links with outgoing by default
        assert b'outgoing.' not in response.content
        # But they should be if the param is passed.
        response = self.client.get(
            self.url, {'lang': 'en-US', 'wrap_outgoing_links': ''}
        )
        assert b'outgoing.' in response.content

    def test_all_param(self):
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            select_image=self.phi_a,
            gradient_color='#989898',
            enabled=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            select_image=self.phi_b,
            gradient_color='#989898',
            enabled=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            select_image=self.phi_c,
            gradient_color='#989898',
            enabled=False,
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.json()['results']) == 2

        response = self.client.get(self.url + '?all=true')
        assert response.status_code == 200
        assert len(response.json()['results']) == 3

    def test_public_filtering(self):
        ph = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            select_image=self.phi_a,
            gradient_color='#989898',
            enabled=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(status=amo.STATUS_DELETED)
            ),
            select_image=self.phi_b,
            gradient_color='#989898',
            enabled=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(disabled_by_user=True)
            ),
            select_image=self.phi_c,
            gradient_color='#989898',
            enabled=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(status=amo.STATUS_NOMINATED)
            ),
            select_image=self.phi_d,
            gradient_color='#989898',
            enabled=True,
        )
        # external addons don't have to be public
        external = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(status=amo.STATUS_NULL)
            ),
            select_image=self.phi_a,
            gradient_color='#989898',
            enabled=True,
            is_external=True,
        )
        # but we still filter out deleted and disabled
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(status=amo.STATUS_DELETED)
            ),
            select_image=self.phi_b,
            gradient_color='#989898',
            enabled=True,
            is_external=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(status=amo.STATUS_DISABLED)
            ),
            select_image=self.phi_c,
            gradient_color='#989898',
            enabled=True,
            is_external=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(disabled_by_user=True)
            ),
            select_image=self.phi_d,
            gradient_color='#989898',
            enabled=True,
            is_external=True,
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.json()['results']) == 2
        assert response.json()['results'][0]['addon']['id'] == (
            ph.promoted_addon.addon.id
        )
        assert response.json()['results'][1]['external']['id'] == (
            external.promoted_addon.addon.id
        )

        response = self.client.get(self.url + '?all=true')
        assert response.status_code == 200
        assert len(response.json()['results']) == 8

    def test_raw_param(self):
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(summary='addon')
            ),
            select_image=self.phi_a,
            gradient_color='#989898',
            enabled=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            description='hero',
            select_image=self.phi_b,
            gradient_color='#989898',
            enabled=True,
        )
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(summary=None)
            ),
            select_image=self.phi_c,
            gradient_color='#989898',
            enabled=True,
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        results = response.json()['results']
        assert len(results) == 3
        assert results[0]['description'] == {'en-US': 'addon'}
        assert results[1]['description'] == {'en-US': 'hero'}
        assert results[2]['description'] is None

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
            headline='Its a héadline!', description='foo'
        )
        hero_b = SecondaryHero.objects.create(
            headline='%^*', description='', cta_url='http://goo.gl', cta_text='goozilla'
        )
        SecondaryHero.objects.create(headline='dfdfd!', description='dfdfd')
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
                SecondaryHeroShelfSerializer(instance=hero_b).data,
            ]
        }

    @override_settings(DRF_API_GATES={'v5': ('wrap-outgoing-parameter',)})
    def test_outgoing_wrapper_gate(self):
        hero = SecondaryHero.objects.create(
            headline='%^*',
            description='',
            cta_url='/addon/adblockplus/',
            cta_text='goozilla',
            enabled=True,
        )
        # No outgoing wrapping by default
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert b'outgoing.' not in response.content
        response = self.client.get(
            self.url, {'lang': 'en-US', 'wrap_outgoing_links': ''}
        )
        # But we also don't want to wrap internal urls
        assert b'outgoing.' not in response.content
        assert b'http://testserver' in response.content

        # update the cta to an external url - test the no wrap param case first
        hero.update(cta_url='http://goo.gl')
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert b'outgoing.' not in response.content
        response = self.client.get(
            self.url, {'lang': 'en-US', 'wrap_outgoing_links': ''}
        )
        # This time it should be wrapped
        assert b'outgoing.' in response.content

    def test_all_param(self):
        SecondaryHero.objects.create(
            headline='dfdfd!', description='dfdfd', enabled=True
        )
        SecondaryHero.objects.create(
            headline='dfdfd!', description='dfdfd', enabled=True
        )
        SecondaryHero.objects.create(
            headline='dfdfd!', description='dfdfd', enabled=False
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.json()['results']) == 2

        response = self.client.get(self.url + '?all=true')
        assert response.status_code == 200
        assert len(response.json()['results']) == 3


# If we delete HeroShelvesView move all these tests to TestShelfViewSet
class TestHeroShelvesView(TestCase):
    def setUp(self):
        self.url = reverse_ns('hero-shelves', api_version='v5')

    def test_basic(self):
        phero = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            enabled=True,
        )
        shero = SecondaryHero.objects.create(
            headline='headline', description='description', enabled=True
        )
        SecondaryHeroModule.objects.create(shelf=shero)
        SecondaryHeroModule.objects.create(shelf=shero)
        SecondaryHeroModule.objects.create(shelf=shero)

        # We'll need a fake request with the right api version to pass to the
        # serializers to compare the data, so that the right API gates are
        # active.
        request = APIRequestFactory().get('/')
        request.version = api_settings.DEFAULT_VERSION

        with self.assertNumQueries(13):
            # 13 queries:
            # - 11 as TestPrimaryHeroShelfViewSet.test_basic above
            # - 2 as TestSecondaryHeroShelfViewSet.test_basic above
            response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.status_code == 200
        assert response.json() == {
            'primary': PrimaryHeroShelfSerializer(
                instance=phero, context={'request': request}
            ).data,
            'secondary': SecondaryHeroShelfSerializer(
                instance=shero, context={'request': request}
            ).data,
        }

    def test_outgoing_wrapper(self):
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(homepage='http://foo.baa')
            ),
            enabled=True,
            is_external=True,
        )
        SecondaryHero.objects.create(
            headline='headline',
            description='description',
            cta_url='http://go.here/',
            cta_text='go here!',
            enabled=True,
        )
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert 'outgoing.' in json.dumps(response.json()['primary'])
        assert 'outgoing.' in json.dumps(response.json()['secondary'])

    def test_shelf_randomness(self):
        addon_1 = addon_factory()
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_1), enabled=True
        )
        addon_2 = addon_factory()
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_2), enabled=True
        )
        addon_3 = addon_factory()
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_3), enabled=True
        )
        addon_ids = {addon_1.id, addon_2.id, addon_3.id}

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()['primary']['addon']['id'] in addon_ids

        found_ids = set()
        # check its not just returning the same add-on each time
        for _count in range(0, 19):
            response = self.client.get(self.url)
            found_ids.add(response.json()['primary']['addon']['id'])
            if len(found_ids) == 3:
                break

        assert found_ids == addon_ids

    def test_no_valid_shelves(self):
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            enabled=False,
        )
        # No SecondaryHero at all
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.json()['primary'] is None
        assert response.json()['secondary'] is None
