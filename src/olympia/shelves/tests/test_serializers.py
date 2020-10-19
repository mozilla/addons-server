from urllib import parse

from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from freezegun import freeze_time

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tests.test_serializers import (
    AddonSerializerOutputTestMixin)
from olympia.amo.tests import addon_factory, ESTestCase, reverse_ns
from olympia.constants.promoted import RECOMMENDED
from olympia.promoted.models import PromotedAddon

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
        self.search_shelf = Shelf.objects.create(
            title='Populâr themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme',
            footer_text='See more populâr themes')

        self.collections_shelf = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            criteria='privacy-matters',
            footer_text='See more enhanced privacy extensions')

        # Set up the request to support drf_reverse
        api_version = api_settings.DEFAULT_VERSION
        self.request = APIRequestFactory().get('/api/%s/' % api_version)
        self.request.versioning_scheme = (
            api_settings.DEFAULT_VERSIONING_CLASS()
        )
        self.request.version = api_version
        self.request.user = AnonymousUser()

    def get_serializer(self, instance, **extra_context):
        extra_context['request'] = self.request
        return ShelfSerializer(instance=instance, context=extra_context)

    def serialize(self, instance, **extra_context):
        if instance.endpoint == 'search':
            self.request.query_params = dict(parse.parse_qsl(
                self.search_shelf.criteria))
        return self.get_serializer(instance, **extra_context).data

    def test_shelf_serializer_search(self):
        data = self.serialize(instance=self.search_shelf)
        search_url = reverse_ns('addon-search') + self.search_shelf.criteria

        assert data['title'] == 'Populâr themes'
        assert data['url'] == search_url
        assert data['endpoint'] == self.search_shelf.endpoint
        assert data['criteria'] == self.search_shelf.criteria
        assert data['footer_text'] == 'See more populâr themes'
        assert data['footer_pathname'] == ''

        assert len(data['addons']) == 2

        assert data['addons'][0]['name']['en-US'] == 'test addon test02'
        assert data['addons'][0]['promoted'] is None
        assert data['addons'][0]['type'] == 'statictheme'

        assert data['addons'][1]['name']['en-US'] == 'test addon test04'
        assert data['addons'][1]['promoted']['category'] == 'recommended'
        assert data['addons'][1]['type'] == 'statictheme'

    def test_shelf_serializer_collections(self):
        data = self.serialize(instance=self.collections_shelf)
        collections_url = reverse_ns('collection-addon-list', kwargs={
            'user_pk': settings.TASK_USER_ID,
            'collection_slug': self.collections_shelf.criteria})
        assert data == {
            'title': 'Enhanced privacy extensions',
            'url': collections_url,
            'endpoint': self.collections_shelf.endpoint,
            'criteria': self.collections_shelf.criteria,
            'footer_text': 'See more enhanced privacy extensions',
            'footer_pathname': '',
            'addons': None
        }


class TestESSponsoredAddonSerializer(AddonSerializerOutputTestMixin,
                                     ESTestCase):
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
        self.serializer = self.serializer_class(context={
            'request': self.request,
            'view': view,
        })

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
        request = APIRequestFactory().get(
            f'/api/{api_version}{path}', data, **extra)
        request.versioning_scheme = (
            api_settings.DEFAULT_VERSIONING_CLASS()
        )
        request.version = api_version
        return request

    @freeze_time('2020-01-01')
    def test_click_url_and_data(self):
        self.addon = addon_factory()
        adzerk_results = {
            str(self.addon.id): {
                'click': 'foobar'
            }
        }
        result = self.serialize(adzerk_results)
        assert result['click_url'] == (
            'http://testserver/api/v5/shelves/sponsored/click/')
        assert result['click_data'] == (
            'foobar:1imRQe:mJEcjX6cM3cvkSbb2qMMPPHWC8o')

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
