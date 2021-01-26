from urllib import parse

from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from olympia import amo
from olympia.amo.tests import addon_factory, collection_factory, ESTestCase, reverse_ns
from olympia.bandwagon.models import CollectionAddon
from olympia.constants.promoted import RECOMMENDED
from olympia.users.models import UserProfile

from ..models import Shelf
from ..serializers import ShelfSerializer


class TestShelvesSerializer(ESTestCase):
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
        addon_factory(
            name='test addon test03',
            type=amo.ADDON_EXTENSION,
            average_daily_users=482,
            weekly_downloads=506,
            summary=None,
            promoted=RECOMMENDED,
        )
        addon_factory(
            name='test addon test04',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=8838,
            weekly_downloads=358,
            summary=None,
            promoted=RECOMMENDED,
        )

        user = UserProfile.objects.create(pk=settings.TASK_USER_ID)
        collection = collection_factory(author=user, slug='privacy-matters')
        addon = addon_factory(name='test addon privacy01')
        CollectionAddon.objects.create(addon=addon, collection=collection)

        cls.refresh()

    def setUp(self):
        self.search_pop_thm = Shelf.objects.create(
            title='Populâr themes',
            endpoint='search-themes',
            criteria='?sort=users&type=statictheme',
            footer_text='See more populâr themes',
        )

        self.search_rec_ext = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            criteria='?promoted=recommended&sort=random&type=extension',
            footer_text='See more recommended extensions',
        )

        self.collections_shelf = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            criteria='privacy-matters',
            footer_text='See more enhanced privacy extensions',
        )

        # Set up the request to support drf_reverse
        api_version = api_settings.DEFAULT_VERSION
        self.request = APIRequestFactory().get('/api/%s/' % api_version)
        self.request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        self.request.version = api_version
        self.request.user = AnonymousUser()

    def serialize(self, instance, **context):
        self.request.query_params = dict(parse.parse_qsl(instance.criteria))
        context['request'] = self.request
        return ShelfSerializer(instance, context=context).data

    def _get_result_url(self, instance):
        if instance.endpoint in ('search', 'search-themes'):
            return reverse_ns('addon-search') + instance.criteria
        elif instance.endpoint == 'collections':
            return reverse_ns(
                'collection-addon-list',
                kwargs={
                    'user_pk': str(settings.TASK_USER_ID),
                    'collection_slug': self.collections_shelf.criteria,
                },
            )
        else:
            return None

    def test_basic(self):
        data = self.serialize(self.search_rec_ext)
        assert data['title'] == 'Recommended extensions'
        assert data['endpoint'] == 'search'
        assert data['criteria'] == '?promoted=recommended&sort=random&type=extension'
        assert data['footer_text'] == 'See more recommended extensions'
        assert data['footer_pathname'] == ''

    def test_basic_themes(self):
        data = self.serialize(self.search_pop_thm)
        assert data['title'] == 'Populâr themes'
        assert data['endpoint'] == 'search-themes'
        assert data['criteria'] == '?sort=users&type=statictheme'
        assert data['footer_text'] == 'See more populâr themes'
        assert data['footer_pathname'] == ''

    def test_url_and_addons_search(self):
        pop_data = self.serialize(self.search_pop_thm)
        assert pop_data['url'] == self._get_result_url(self.search_pop_thm)

        assert len(pop_data['addons']) == 2
        assert pop_data['addons'][0]['name']['en-US'] == ('test addon test02')
        assert pop_data['addons'][0]['promoted'] is None
        assert pop_data['addons'][0]['type'] == 'statictheme'

        assert pop_data['addons'][1]['name']['en-US'] == ('test addon test04')
        assert pop_data['addons'][1]['promoted']['category'] == ('recommended')
        assert pop_data['addons'][1]['type'] == 'statictheme'

        # Test 'Recommended Extensions' shelf - should include 1 addon
        rec_data = self.serialize(self.search_rec_ext)
        assert rec_data['url'] == self._get_result_url(self.search_rec_ext)

        assert len(rec_data['addons']) == 1
        assert rec_data['addons'][0]['name']['en-US'] == ('test addon test03')
        assert rec_data['addons'][0]['promoted']['category'] == ('recommended')
        assert rec_data['addons'][0]['type'] == 'extension'

    def test_url_and_addons_collections(self):
        data = self.serialize(self.collections_shelf)
        assert data['url'] == self._get_result_url(self.collections_shelf)
        assert data['addons'][0]['name']['en-US'] == ('test addon privacy01')
