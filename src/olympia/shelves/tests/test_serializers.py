from rest_framework.request import Request as DRFRequest
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from freezegun import freeze_time

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tests.test_serializers import AddonSerializerOutputTestMixin
from olympia.amo.tests import addon_factory, collection_factory, ESTestCase, reverse_ns
from olympia.bandwagon.models import CollectionAddon
from olympia.constants.promoted import RECOMMENDED
from olympia.users.models import UserProfile

from ..models import Shelf
from ..serializers import ESSponsoredAddonSerializer, ShelfSerializer
from ..views import SponsoredShelfViewSet


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

        cls.mozilla_user = UserProfile.objects.create(pk=settings.TASK_USER_ID)
        collection = collection_factory(author=cls.mozilla_user, slug='privacy-matters')
        addon = addon_factory(name='test addon privacy01')
        CollectionAddon.objects.create(addon=addon, collection=collection)

        # add some extra extensions to test count limits
        addon_factory(
            name='test extra extension 1',
            type=amo.ADDON_EXTENSION,
            average_daily_users=4,
            weekly_downloads=1,
        )
        addon_factory(
            name='test extra extension 2',
            type=amo.ADDON_EXTENSION,
            average_daily_users=4,
            weekly_downloads=1,
        )
        addon_factory(
            name='test extra theme 1',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=4,
            weekly_downloads=1,
        )
        addon_factory(
            name='test extra theme 2',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=4,
            weekly_downloads=1,
        )

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
        self.request = DRFRequest(self.request)

    def serialize(self, instance, **context):
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

        assert len(pop_data['addons']) == 3
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

    def test_addon_count(self):
        shelf = Shelf(
            title='Populâr stuff',
            endpoint='search',
            criteria='?sort=users&type=extension',
        )

        data = self.serialize(shelf)
        # non-themes are limited to 4 by default
        assert len(data['addons']) == 4

        shelf.endpoint = 'search-themes'
        shelf.criteria = '?sort=users&type=statictheme'
        data = self.serialize(shelf)
        # themes are limited to 3 by default
        assert len(data['addons']) == 3

        # double check by changing the endpoint without changing the criteria
        shelf.endpoint = 'search'
        data = self.serialize(shelf)
        assert len(data['addons']) == 4

        # check collections are limited to 4 also
        collection = collection_factory(author=self.mozilla_user, slug='all-the-addons')
        for addon in Addon.objects.filter(type=amo.ADDON_EXTENSION):
            CollectionAddon.objects.create(addon=addon, collection=collection)
        assert collection.addons.count() == 5
        shelf.endpoint = 'collections'
        shelf.criteria = 'all-the-addons'

        data = self.serialize(shelf)
        assert len(data['addons']) == 4


class TestESSponsoredAddonSerializer(AddonSerializerOutputTestMixin, ESTestCase):
    serializer_class = ESSponsoredAddonSerializer
    view_class = SponsoredShelfViewSet

    def tearDown(self):
        super().tearDown()
        self.empty_index('default')
        self.refresh()

    def search(self):
        self.reindex(Addon)

        view = self.view_class()
        view.request = self.request
        qs = view.get_queryset()

        # We don't even filter - there should only be one addon in the index
        # at this point
        return qs.execute()[0]

    def serialize(self, adzerk_results=None):
        view = self.view_class(action='list')
        view.request = self.request
        view.adzerk_results = adzerk_results or {}
        self.serializer = self.serializer_class(
            context={
                'request': self.request,
                'view': view,
            }
        )

        obj = self.search()

        with self.assertNumQueries(0):
            result = self.serializer.to_representation(obj)
        return result

    def _test_author(self, author, data):
        """Override because the ES serializer doesn't include picture_url."""
        assert data == {
            'id': author.pk,
            'name': author.name,
            'url': author.get_absolute_url(),
            'username': author.username,
        }

    def get_request(self, path, data=None, **extra):
        api_version = 'v5'  # choose v5 to ignore 'l10n_flat_input_output' gate
        request = APIRequestFactory().get(f'/api/{api_version}{path}', data, **extra)
        request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        request.version = api_version
        return request

    @freeze_time('2020-01-01')
    def test_click_url_and_data(self):
        self.addon = addon_factory()
        adzerk_results = {str(self.addon.id): {'click': 'foobar'}}
        result = self.serialize(adzerk_results)
        assert result['click_url'] == (
            'http://testserver/api/v5/shelves/sponsored/click/'
        )
        assert result['click_data'] == ('foobar:1imRQe:mJEcjX6cM3cvkSbb2qMMPPHWC8o')

    @freeze_time('2020-01-01')
    def test_events(self):
        self.addon = addon_factory()
        adzerk_results = {
            str(self.addon.id): {
                'click': 'foobar',
                'impression': 'impressive',
                'conversion': 'hyhyhy',
            }
        }
        result = self.serialize(adzerk_results)
        assert result['event_data'] == {
            'click': 'foobar:1imRQe:mJEcjX6cM3cvkSbb2qMMPPHWC8o',
            'conversion': 'hyhyhy:1imRQe:NQyj05lumKmHaj5Zj4yF69Q9bS4',
        }
