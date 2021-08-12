from rest_framework.request import Request as DRFRequest
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test.utils import override_settings

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.reverse import reverse
from olympia.amo.tests import (
    addon_factory,
    collection_factory,
    ESTestCase,
    reverse_ns,
    TestCase,
)
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.bandwagon.models import CollectionAddon
from olympia.constants.promoted import RECOMMENDED
from olympia.users.models import UserProfile

from ..models import Shelf
from ..serializers import ShelfSerializer, ShelfEditorialSerializer


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
            tags=('foo',),
        )
        addon_factory(
            name='test addon test02',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=18981,
            weekly_downloads=145,
            summary=None,
            tags=('baa',),
        )
        addon_factory(
            name='test addon test03',
            type=amo.ADDON_EXTENSION,
            average_daily_users=482,
            weekly_downloads=506,
            summary=None,
            promoted=RECOMMENDED,
            tags=('baa',),
        )
        addon_factory(
            name='test addon test04',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=8838,
            weekly_downloads=358,
            summary=None,
            promoted=RECOMMENDED,
            tags=('foo',),
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
            endpoint='search',
            addon_type=amo.ADDON_STATICTHEME,
            criteria='?sort=users&type=statictheme',
            footer_text='See more populâr themes',
            footer_pathname='/themes/',
        )

        self.search_rec_ext = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            addon_type=amo.ADDON_EXTENSION,
            criteria='?promoted=recommended&sort=random&type=extension',
            footer_text='See more recommended extensions',
            footer_pathname='/somewhere',
        )

        self.collections_shelf = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            addon_type=amo.ADDON_EXTENSION,
            criteria='privacy-matters',
            footer_text='See more enhanced privacy extensions',
            footer_pathname='https://blog.mozilla.org/addons',
        )
        self.tag_shelf = Shelf.objects.create(
            title='Random tags',
            endpoint='random-tag',
            addon_type=amo.ADDON_EXTENSION,
            criteria='?',
            footer_text='See similar add-ons?',
            footer_pathname='/',
        )
        self.tag_shelf.tag = 'foo'

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

    def _get_result_url(self, instance, tag=None):
        criteria = instance.criteria
        if instance.endpoint == 'search':
            return reverse_ns('addon-search') + criteria
        elif instance.endpoint == 'collections':
            return reverse_ns(
                'collection-addon-list',
                kwargs={
                    'user_pk': str(settings.TASK_USER_ID),
                    'collection_slug': criteria,
                },
            )
        elif instance.endpoint == 'random-tag':
            return (
                f'{reverse_ns("addon-search")}{criteria}'
                f'{"&" if len(criteria)>1 else ""}tag={tag}'
            )
        else:
            return None

    def test_basic(self):
        data = self.serialize(self.search_rec_ext)
        assert data['title'] == {'en-US': 'Recommended extensions'}
        assert data['endpoint'] == 'search'
        assert data['addon_type'] == 'extension'
        assert data['footer']['text'] == {'en-US': 'See more recommended extensions'}
        assert data['footer']['url'] == 'http://testserver/somewhere'
        assert data['footer']['outgoing'] == 'http://testserver/somewhere'

    def test_basic_themes(self):
        data = self.serialize(self.search_pop_thm)
        assert data['title'] == {'en-US': 'Populâr themes'}
        assert data['endpoint'] == 'search'
        assert data['addon_type'] == 'statictheme'
        assert data['footer']['text'] == {'en-US': 'See more populâr themes'}
        assert data['footer']['url'] == 'http://testserver/themes/'
        assert data['footer']['outgoing'] == 'http://testserver/themes/'

    def test_url_and_addons_search(self):
        pop_data = self.serialize(self.search_pop_thm)
        assert pop_data['url'] == self._get_result_url(self.search_pop_thm)

        assert len(pop_data['addons']) == 3
        assert pop_data['addons'][0]['name'] == {'en-US': 'test addon test02'}
        assert pop_data['addons'][0]['promoted'] is None
        assert pop_data['addons'][0]['type'] == 'statictheme'

        assert pop_data['addons'][1]['name'] == {'en-US': 'test addon test04'}
        assert pop_data['addons'][1]['promoted']['category'] == ('recommended')
        assert pop_data['addons'][1]['type'] == 'statictheme'

        # Test 'Recommended Extensions' shelf - should include 1 addon
        rec_data = self.serialize(self.search_rec_ext)
        assert rec_data['url'] == self._get_result_url(self.search_rec_ext)

        assert len(rec_data['addons']) == 1
        assert rec_data['addons'][0]['name'] == {'en-US': 'test addon test03'}
        assert rec_data['addons'][0]['promoted']['category'] == ('recommended')
        assert rec_data['addons'][0]['type'] == 'extension'

    def test_url_and_addons_collections(self):
        data = self.serialize(self.collections_shelf)
        assert data['url'] == self._get_result_url(self.collections_shelf)
        assert data['addons'][0]['name'] == {'en-US': 'test addon privacy01'}
        assert data['footer']['url'] == 'https://blog.mozilla.org/addons'
        assert data['footer']['outgoing'] == get_outgoing_url(
            'https://blog.mozilla.org/addons'
        )

    def test_footer_url(self):
        wrap_outgoing_settings_override = {
            'DRF_API_GATES': {
                api_settings.DEFAULT_VERSION: ('wrap-outgoing-parameter',)
            }
        }
        # search
        self.search_rec_ext.update(footer_pathname='')
        data = self.serialize(self.search_rec_ext)
        url = (
            'http://testserver'
            + reverse('search.search')
            + '?promoted=recommended&sort=random&type=extension'
        )
        assert data['footer'] == {
            'url': url,
            'outgoing': url,
            'text': {'en-US': 'See more recommended extensions'},
        }
        with override_settings(**wrap_outgoing_settings_override):
            data = self.serialize(self.search_rec_ext)
            assert data['footer'] == {
                'url': url,
                'text': {'en-US': 'See more recommended extensions'},
            }
        # collections
        self.collections_shelf.update(footer_pathname='')
        data = self.serialize(self.collections_shelf)
        url = 'http://testserver' + reverse(
            'collections.detail',
            kwargs={
                'user_id': str(settings.TASK_USER_ID),
                'slug': 'privacy-matters',
            },
        )
        assert data['footer'] == {
            'url': url,
            'outgoing': url,
            'text': {'en-US': 'See more enhanced privacy extensions'},
        }
        with override_settings(**wrap_outgoing_settings_override):
            data = self.serialize(self.collections_shelf)
            assert data['footer'] == {
                'url': url,
                'text': {'en-US': 'See more enhanced privacy extensions'},
            }

        # random-tag
        self.tag_shelf.update(footer_pathname='')
        data = self.serialize(self.tag_shelf)
        url = 'http://testserver' + reverse('search.search') + '?tag=foo'
        assert data['footer'] == {
            'url': url,
            'outgoing': url,
            'text': {'en-US': 'See similar add-ons?'},
        }
        with override_settings(**wrap_outgoing_settings_override):
            data = self.serialize(self.tag_shelf)
            assert data['footer'] == {
                'url': url,
                'text': {'en-US': 'See similar add-ons?'},
            }

    def test_tags_shelf(self):
        data = self.serialize(self.tag_shelf)
        assert data['title'] == {'en-US': 'Random tags'}
        assert data['endpoint'] == 'random-tag'
        assert data['addon_type'] == 'extension'
        assert data['footer']['text'] == {'en-US': 'See similar add-ons?'}
        assert data['footer']['url'] == 'http://testserver/'
        assert data['footer']['outgoing'] == 'http://testserver/'
        assert data['url'] == self._get_result_url(self.tag_shelf, tag='foo')
        assert len(data['addons']) == 2
        assert data['addons'][0]['name'] == {'en-US': 'test addon test04'}
        assert data['addons'][1]['name'] == {'en-US': 'test addon test01'}

    def test_tag_token_substitution(self):
        self.tag_shelf.update(title='Title for {tag}', footer_text='footer with {tag}')
        data = self.serialize(self.tag_shelf)
        assert data['title'] == {'en-US': 'Title for foo'}
        assert data['footer']['text'] == {'en-US': 'footer with foo'}

        # The is only a thing with the random-tag shelf though
        self.tag_shelf.update(endpoint=Shelf.Endpoints.SEARCH)
        data = self.serialize(self.tag_shelf)
        assert data['title'] == {'en-US': 'Title for {tag}'}
        assert data['footer']['text'] == {'en-US': 'footer with {tag}'}

    def test_addon_count(self):
        shelf = Shelf(
            title='Populâr stuff',
            endpoint='search',
            addon_type=amo.ADDON_EXTENSION,
            criteria='?sort=users&type=extension',
        )

        data = self.serialize(shelf)
        # extensions are limited to 4 by default
        assert len(data['addons']) == 4

        shelf.addon_type = amo.ADDON_STATICTHEME
        shelf.criteria = '?sort=users&type=statictheme'
        data = self.serialize(shelf)
        # themes are limited to 3 by default
        assert len(data['addons']) == 3

        # double check by changing the addon_type without changing the criteria
        shelf.addon_type = amo.ADDON_EXTENSION
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

        # override the count with a custom setting
        shelf.update(addon_count=5)
        data = self.serialize(shelf)
        assert len(data['addons']) == 5
        shelf.update(addon_count=2)
        data = self.serialize(shelf)
        assert len(data['addons']) == 2


class TestShelfEditorialSerializer(TestCase):
    def test_basic(self):
        shelf = Shelf(title='the title', footer_text='footer')
        serializer = ShelfEditorialSerializer(shelf)
        assert serializer.data == {
            'title': 'the title',
            'footer_text': 'footer',
        }
