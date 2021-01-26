import json

from django.conf import settings

from olympia import amo
from olympia.amo.tests import (
    addon_factory,
    APITestClient,
    collection_factory,
    ESTestCase,
    reverse_ns,
)
from olympia.bandwagon.models import CollectionAddon
from olympia.constants.promoted import RECOMMENDED
from olympia.hero.models import PrimaryHero, SecondaryHero, SecondaryHeroModule
from olympia.hero.serializers import (
    PrimaryHeroShelfSerializer,
    SecondaryHeroShelfSerializer,
)
from olympia.promoted.models import PromotedAddon
from olympia.shelves.models import Shelf, ShelfManagement
from olympia.users.models import UserProfile


class TestShelfViewSet(ESTestCase):
    client_class = APITestClient

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Shouldn't be necessary, but just in case.
        cls.empty_index('default')

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

        shelf_a = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            criteria='?promoted=recommended&sort=random&type=extension',
            footer_text='See more recommended extensions',
        )
        shelf_b = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            criteria='privacy-matters',
            footer_text='See more enhanced privacy extensions',
        )
        shelf_c = Shelf.objects.create(
            title='Popular themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme',
            footer_text='See more popular themes',
        )

        self.hpshelf_a = ShelfManagement.objects.create(shelf=shelf_a, position=3)
        self.hpshelf_b = ShelfManagement.objects.create(shelf=shelf_b, position=2)
        ShelfManagement.objects.create(shelf=shelf_c, position=1)

        self.search_url = (
            reverse_ns('addon-search', api_version='v5') + shelf_a.criteria
        )

        self.collections_url = reverse_ns(
            'collection-addon-list',
            api_version='v5',
            kwargs={
                'user_pk': settings.TASK_USER_ID,
                'collection_slug': shelf_b.criteria,
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

    def test_only_enabled_shelves_in_view(self):
        self.hpshelf_a.update(enabled=True)
        self.hpshelf_b.update(enabled=True)
        # don't enable shelf_c

        with self.assertNumQueries(25):
            response = self.client.get(self.url)
        assert response.status_code == 200

        result = json.loads(response.content)

        assert len(result['results']) == 2

        assert result['results'][0]['title'] == 'Enhanced privacy extensions'
        assert result['results'][0]['url'] == self.collections_url
        assert result['results'][0]['endpoint'] == 'collections'
        assert result['results'][0]['criteria'] == 'privacy-matters'
        assert result['results'][0]['footer_text'] == (
            'See more enhanced privacy extensions'
        )
        assert result['results'][0]['footer_pathname'] == ''
        assert result['results'][0]['addons'][0]['name']['en-US'] == (
            'test addon privacy01'
        )

        assert result['results'][1]['title'] == 'Recommended extensions'
        assert result['results'][1]['url'] == self.search_url
        assert result['results'][1]['endpoint'] == 'search'
        assert result['results'][1]['criteria'] == (
            '?promoted=recommended&sort=random&type=extension'
        )
        assert result['results'][1]['footer_text'] == (
            'See more recommended extensions'
        )
        assert result['results'][1]['footer_pathname'] == ''
        assert result['results'][1]['addons'][0]['name']['en-US'] == (
            'test addon test03'
        )
        assert result['results'][1]['addons'][0]['promoted']['category'] == (
            'recommended'
        )
        assert result['results'][1]['addons'][0]['type'] == 'extension'

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

        with self.assertNumQueries(14):
            # 14 queries:
            # - 1 to get the shelves
            # - 11 as TestPrimaryHeroShelfViewSet.test_basic
            # - 2 as TestSecondaryHeroShelfViewSet.test_basic
            response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.status_code == 200
        assert response.json() == {
            'results': [],
            'primary': PrimaryHeroShelfSerializer(instance=phero).data,
            'secondary': SecondaryHeroShelfSerializer(instance=shero).data,
        }

    def test_full_response(self):
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

        self.hpshelf_a.update(enabled=True)

        with self.assertNumQueries(16):
            # 16 queries:
            # - 3 to get the shelves
            # - 11 as TestPrimaryHeroShelfViewSet.test_basic
            # - 2 as TestSecondaryHeroShelfViewSet.test_basic
            response = self.client.get(self.url)
        assert response.status_code == 200

        result = json.loads(response.content)

        for prop in ('count', 'next', 'page_count', 'page_size', 'previous'):
            assert prop not in result

        assert len(result['results']) == 1

        assert result['results'][0]['title'] == 'Recommended extensions'
        assert result['results'][0]['addons'][0]['name']['en-US'] == (
            'test addon test03'
        )

        assert result['primary'] == PrimaryHeroShelfSerializer(instance=phero).data
        assert result['secondary'] == SecondaryHeroShelfSerializer(instance=shero).data
