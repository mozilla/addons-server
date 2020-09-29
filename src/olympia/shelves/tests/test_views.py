import json

from django.conf import settings

from olympia import amo
from olympia.amo.tests import addon_factory, ESTestCase, reverse_ns
from olympia.constants.promoted import RECOMMENDED
from olympia.promoted.models import PromotedAddon
from olympia.shelves.models import Shelf, ShelfManagement


class TestShelfViewSet(ESTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Shouldn't be necessary, but just in case.
        cls.empty_index('default')

        addon_factory(
            name='test addon test01', type=amo.ADDON_EXTENSION,
            average_daily_users=46812, weekly_downloads=132, summary=None)
        addon_factory(
            name='test addon test02', type=amo.ADDON_STATICTHEME,
            average_daily_users=18981, weekly_downloads=145, summary=None)
        addon_ext = addon_factory(
            name='test addon test03', type=amo.ADDON_EXTENSION,
            average_daily_users=482, weekly_downloads=506, summary=None)
        addon_theme = addon_factory(
            name='test addon test04', type=amo.ADDON_STATICTHEME,
            average_daily_users=8838, weekly_downloads=358, summary=None)

        PromotedAddon.objects.create(
            addon=addon_ext, group_id=RECOMMENDED.id
        ).approve_for_version(version=addon_ext.current_version)

        PromotedAddon.objects.create(
            addon=addon_theme, group_id=RECOMMENDED.id
        ).approve_for_version(version=addon_theme.current_version)

        cls.refresh()

    def setUp(self):
        self.url = reverse_ns('shelves-list')

        shelf_a = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            criteria='?promoted=recommended&sort=random&type=extension',
            footer_text='See more recommended extensions')
        shelf_b = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            criteria='privacy-matters',
            footer_text='See more enhanced privacy extensions')
        shelf_c = Shelf.objects.create(
            title='Popular themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme',
            footer_text='See more popular themes')

        self.hpshelf_a = ShelfManagement.objects.create(
            shelf=shelf_a,
            position=3)
        self.hpshelf_b = ShelfManagement.objects.create(
            shelf=shelf_b,
            position=2)
        ShelfManagement.objects.create(
            shelf=shelf_c,
            position=1)

        self.search_url = reverse_ns('addon-search') + shelf_a.criteria

        self.collections_url = reverse_ns('collection-addon-list', kwargs={
            'user_pk': settings.TASK_USER_ID,
            'collection_slug': shelf_b.criteria})

    def test_no_enabled_shelves_empty_view(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            'count': 0,
            'next': None,
            'page_count': 1,
            'page_size': 25,
            'previous': None,
            'results': []}

    def test_only_enabled_shelves_in_view(self):
        self.hpshelf_a.update(enabled=True)
        self.hpshelf_b.update(enabled=True)
        # don't enable shelf_c

        with self.assertNumQueries(4):
            response = self.client.get(self.url)
        assert response.status_code == 200

        result = json.loads(response.content)

        assert len(result['results']) == 2

        assert result['results'][0]['title'] == 'Enhanced privacy extensions'
        assert result['results'][0]['url'] == self.collections_url
        assert result['results'][0]['endpoint'] == 'collections'
        assert result['results'][0]['criteria'] == 'privacy-matters'
        assert result['results'][0]['footer_text'] == (
            'See more enhanced privacy extensions')
        assert result['results'][0]['footer_pathname'] == ''
        assert result['results'][0]['addons'] is None

        assert result['results'][1]['title'] == 'Recommended extensions'
        assert result['results'][1]['url'] == self.search_url
        assert result['results'][1]['endpoint'] == 'search'
        assert result['results'][1]['criteria'] == (
            '?promoted=recommended&sort=random&type=extension')
        assert result['results'][1]['footer_text'] == (
            'See more recommended extensions')
        assert result['results'][1]['footer_pathname'] == ''
        assert result['results'][1]['addons'][0]['name']['en-US'] == (
            'test addon test03')
        assert result['results'][1]['addons'][0]['promoted']['category'] == (
            'recommended')
        assert result['results'][1]['addons'][0]['type'] == 'extension'
