# -*- coding: utf-8 -*-
import json

from django.core.urlresolvers import reverse

from olympia.amo.tests import addon_factory, ESTestCase
from olympia.users.models import UserProfile


class TestInternalAddonSearchView(ESTestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestInternalAddonSearchView, self).setUp()
        self.url = reverse('internal-addon-search')

    def tearDown(self):
        super(TestInternalAddonSearchView, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def perform_search(
            self, url, data=None, expected_queries_count=0, **headers):
        with self.assertNumQueries(expected_queries_count):
            response = self.client.get(url, data, **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        return data

    def perform_search_with_senior_editor(
            self, url, data=None, expected_queries_count=3, **headers):
        # We are expecting 3 SQL queries by default, because we need
        # to load the user and its groups.
        self.client.login_api(
            UserProfile.objects.get(email='senioreditor@mozilla.com'))
        return self.perform_search(
            url, data=data, expected_queries_count=expected_queries_count,
            **headers)

    def test_not_authenticated(self):
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 401

    def test_no_permissions(self):
        self.client.login_api(
            UserProfile.objects.get(email='regular@mozilla.com'))
        # One for the user, one for its groups. Since this one has none we are
        # skipping the third query to load the groups details.
        with self.assertNumQueries(2):
            response = self.client.get(self.url)
        assert response.status_code == 403

    def test_permissions_but_only_session_cookie(self):
        # A session cookie is not enough, we need a JWT in the headers.
        user = UserProfile.objects.get(email='editor@mozilla.com')
        self.client.login(username=user.username, password='password')
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 401

    def test_basic(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              weekly_downloads=666, is_listed=False)
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn',
                               weekly_downloads=555)
        addon2.delete()
        self.refresh()

        data = self.perform_search_with_senior_editor(self.url)  # No query.
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['is_listed'] == False
        assert result['status'] == 'Fully Reviewed'
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'
        assert result['last_updated'] == addon.last_updated.isoformat()

        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] == None  # Because it was deleted.
        assert result['status'] == 'Deleted'

    def test_empty(self):
        data = self.perform_search_with_senior_editor(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_pagination(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              weekly_downloads=33)
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn',
                               weekly_downloads=22)
        addon_factory(slug='my-third-addon', name=u'My third Addôn',
                      weekly_downloads=11)
        self.refresh()

        data = self.perform_search_with_senior_editor(
            self.url, {'page_size': 1})
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'

        # Search using the second page URL given in return value.
        # Expect 0 SQL queries since they should be cached after the first
        # call above.
        data = self.perform_search_with_senior_editor(
            data['next'], expected_queries_count=0)
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] == 'my-second-addon'

    def test_pagination_sort_and_query(self):
        addon_factory(slug='my-addon', name=u'Cy Addôn')
        addon2 = addon_factory(slug='my-second-addon', name=u'By second Addôn')
        addon1 = addon_factory(slug='my-first-addon', name=u'Ay first Addôn')
        addon_factory(slug='only-happy-when-it-rains', name=u'Garbage')
        self.refresh()

        data = self.perform_search_with_senior_editor(self.url, {
            'page_size': 1, 'q': u'addôn', 'sort': 'name'})
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon1.pk
        assert result['name'] == {'en-US': u'Ay first Addôn'}

        # Search using the second page URL given in return value.
        # Expect 0 SQL queries since they should be cached after the first
        # call above.
        assert 'sort=name' in data['next']
        data = self.perform_search_with_senior_editor(
            data['next'], expected_queries_count=0)
        assert data['count'] == 3
        assert len(data['results']) == 1
        assert 'sort=name' in data['previous']

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'By second Addôn'}
