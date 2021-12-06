import json
from unittest import mock

from django.conf import settings

from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.tests import (
    addon_factory,
    APITestClientWebToken,
    collection_factory,
    ESTestCase,
    reverse_ns,
    TestCase,
)
from olympia.bandwagon.models import CollectionAddon
from olympia.constants.promoted import RECOMMENDED
from olympia.hero.models import PrimaryHero, SecondaryHero, SecondaryHeroModule
from olympia.hero.serializers import (
    PrimaryHeroShelfSerializer,
    SecondaryHeroShelfSerializer,
)
from olympia.promoted.models import PromotedAddon
from olympia.shelves.models import Shelf
from olympia.tags.models import Tag
from olympia.users.models import UserProfile


class TestShelfViewSet(ESTestCase):
    client_class = APITestClientWebToken

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Shouldn't be necessary, but just in case.
        cls.empty_index('default')
        cls.tag = Tag.objects.first().tag_text

        addon_factory(
            name='test addon test01',
            type=amo.ADDON_EXTENSION,
            average_daily_users=46812,
            weekly_downloads=132,
            summary=None,
        )
        addon_factory(
            name='test addon test02',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=18981,
            weekly_downloads=145,
            summary=None,
        )
        addon_ext = addon_factory(
            name='test addon test03',
            type=amo.ADDON_EXTENSION,
            average_daily_users=482,
            weekly_downloads=506,
            summary=None,
            tags=(cls.tag,),
        )
        addon_theme = addon_factory(
            name='test addon test04',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=8838,
            weekly_downloads=358,
            summary=None,
        )

        PromotedAddon.objects.create(
            addon=addon_ext, group_id=RECOMMENDED.id
        ).approve_for_version(version=addon_ext.current_version)

        PromotedAddon.objects.create(
            addon=addon_theme, group_id=RECOMMENDED.id
        ).approve_for_version(version=addon_theme.current_version)

        user = UserProfile.objects.create(pk=settings.TASK_USER_ID)
        collection = collection_factory(author=user, slug='privacy-matters')
        addon = addon_factory(name='test addon privacy01')
        CollectionAddon.objects.create(addon=addon, collection=collection)

        cls.refresh()

    def setUp(self):
        self.url = reverse_ns('shelves-list', api_version='v5')

        self.shelf_a = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            criteria='?promoted=recommended&sort=random&type=extension',
            footer_text='See more recommended extensions',
            footer_pathname='/extensions/',
            position=3,
        )
        self.shelf_b = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            criteria='privacy-matters',
            footer_text='See more enhanced privacy extensions',
            position=2,
        )
        self.shelf_c = Shelf.objects.create(
            title='Popular themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme',
            footer_text='See more popular themes',
            footer_pathname='http://foo.baa',
            position=1,
        )
        self.shelf_d = Shelf.objects.create(
            title='Random {tag}',
            endpoint='random-tag',
            criteria='?',
            footer_text='something something tags!',
            position=4,
        )

        self.search_url = (
            reverse_ns('addon-search', api_version='v5') + self.shelf_a.criteria
        )

        self.collections_url = reverse_ns(
            'collection-addon-list',
            api_version='v5',
            kwargs={
                'user_pk': settings.TASK_USER_ID,
                'collection_slug': self.shelf_b.criteria,
            },
        )

    def test_no_enabled_shelves_empty_view(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            'results': [],
            'primary': None,
            'secondary': None,
        }

    @mock.patch.object(Shelf, 'tag', new_callable=mock.PropertyMock)
    def test_only_enabled_shelves_in_view(self, tag_mock):
        tag_mock.return_value = self.tag
        self.shelf_a.update(enabled=True)
        self.shelf_b.update(enabled=True)
        # don't enable shelf_c
        self.shelf_d.update(enabled=True)

        # would be 27 but we mocked Shelf.tag that does a query.
        with self.assertNumQueries(26):
            response = self.client.get(self.url)
        assert response.status_code == 200

        result = json.loads(response.content)

        assert len(result['results']) == 3

        assert result['results'][0]['title'] == {'en-US': 'Enhanced privacy extensions'}
        assert result['results'][0]['url'] == self.collections_url
        assert result['results'][0]['endpoint'] == 'collections'
        assert result['results'][0]['footer']['text'] == {
            'en-US': 'See more enhanced privacy extensions'
        }
        assert (
            result['results'][0]['footer']['url']
            == f'http://testserver/en-US/firefox/collections/{settings.TASK_USER_ID}/'
            'privacy-matters/'
        )
        assert (
            result['results'][0]['footer']['outgoing']
            == result['results'][0]['footer']['url']
        )
        assert result['results'][0]['addons'][0]['name']['en-US'] == (
            'test addon privacy01'
        )

        assert result['results'][1]['title'] == {'en-US': 'Recommended extensions'}
        assert result['results'][1]['url'] == self.search_url
        assert result['results'][1]['endpoint'] == 'search'
        assert result['results'][1]['footer']['text'] == {
            'en-US': 'See more recommended extensions'
        }
        assert result['results'][1]['footer']['url'] == 'http://testserver/extensions/'
        assert (
            result['results'][1]['footer']['outgoing']
            == 'http://testserver/extensions/'
        )
        assert result['results'][1]['addons'][0]['name']['en-US'] == (
            'test addon test03'
        )
        assert result['results'][1]['addons'][0]['promoted']['category'] == (
            'recommended'
        )
        assert result['results'][1]['addons'][0]['type'] == 'extension'

        assert result['results'][2]['title'] == {'en-US': f'Random {self.tag}'}
        assert result['results'][2]['url'] == (
            reverse_ns('addon-search', api_version='v5') + f'?tag={self.tag}'
        )
        assert result['results'][2]['endpoint'] == 'random-tag'
        assert result['results'][2]['footer']['text'] == {
            'en-US': 'something something tags!'
        }
        assert (
            result['results'][2]['footer']['url']
            == f'http://testserver/en-US/firefox/tag/{self.tag}/'
        )
        assert (
            result['results'][2]['footer']['outgoing']
            == result['results'][2]['footer']['url']
        )
        assert result['results'][2]['addons'][0]['name']['en-US'] == (
            'test addon test03'
        )
        assert result['results'][2]['addons'][0]['type'] == 'extension'

    # If we delete HeroShelvesView move all the TestHeroShelvesView tests here
    def test_only_hero_shelves_in_response(self):
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

        with self.assertNumQueries(15):
            # 15 queries:
            # - 1 to get the shelves
            # - 12 as TestPrimaryHeroShelfViewSet.test_basic
            # - 2 as TestSecondaryHeroShelfViewSet.test_basic
            response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.status_code == 200
        assert response.json() == {
            'results': [],
            'primary': PrimaryHeroShelfSerializer(
                instance=phero, context={'request': request}
            ).data,
            'secondary': SecondaryHeroShelfSerializer(
                instance=shero, context={'request': request}
            ).data,
        }

    def test_full_response(self):
        phero = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            enabled=True,
            description='Hero!',
        )
        shero = SecondaryHero.objects.create(
            headline='headline', description='description', enabled=True
        )
        SecondaryHeroModule.objects.create(shelf=shero)
        SecondaryHeroModule.objects.create(shelf=shero)
        SecondaryHeroModule.objects.create(shelf=shero)

        self.shelf_a.update(enabled=True)

        with self.assertNumQueries(17):
            # 17 queries:
            # - 3 to get the shelves
            # - 12 as TestPrimaryHeroShelfViewSet.test_basic
            # - 2 as TestSecondaryHeroShelfViewSet.test_basic
            response = self.client.get(self.url)
        assert response.status_code == 200

        result = json.loads(response.content)

        # We'll need a fake request with the right api version to pass to the
        # serializers to compare the data, so that the right API gates are
        # active.
        request = APIRequestFactory().get('/')
        request.version = api_settings.DEFAULT_VERSION

        for prop in ('count', 'next', 'page_count', 'page_size', 'previous'):
            assert prop not in result

        assert len(result['results']) == 1

        assert result['results'][0]['title'] == {'en-US': 'Recommended extensions'}
        assert result['results'][0]['addons'][0]['name'] == {
            'en-US': 'test addon test03'
        }

        assert (
            result['primary']
            == PrimaryHeroShelfSerializer(
                instance=phero, context={'request': request}
            ).data
        )
        assert (
            result['secondary']
            == SecondaryHeroShelfSerializer(
                instance=shero, context={'request': request}
            ).data
        )


class TestEditorialShelfViewSet(TestCase):
    client_class = APITestClientWebToken

    def test_basic(self):
        url = reverse_ns('shelves-editorial-list', api_version='v5')

        # we set position but it's not used for this endpoint
        self.shelf_a = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            criteria='?promoted=recommended&sort=random&type=extension',
            footer_text='See more!',
            position=3,
        )
        self.shelf_b = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            criteria='privacy-matters',
            footer_text='',
            position=6,
        )
        self.shelf_c = Shelf.objects.create(
            title='Popular themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme',
            footer_text='See more popular themes',
            position=1,
            enabled=False,
        )

        response = self.client.get(url)
        assert response.status_code == 200

        assert response.json() == {
            'results': [
                {'title': 'Recommended extensions', 'footer_text': 'See more!'},
                {'title': 'Enhanced privacy extensions', 'footer_text': ''},
                {'title': 'Popular themes', 'footer_text': 'See more popular themes'},
            ]
        }
