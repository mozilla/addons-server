# -*- coding: utf-8 -*-
import json

from django.core.urlresolvers import reverse

import waffle

from olympia import amo
from olympia.amo.tests import version_factory
from olympia.addons.utils import generate_addon_guid
from olympia.amo.tests import (
    addon_factory, APITestClient, ESTestCase, TestCase)
from olympia.internal_tools import views
from olympia.users.models import UserProfile

FXA_CONFIG = {
    'oauth_host': 'https://accounts.firefox.com/v1',
    'client_id': '999abc111',
    'redirect_url': 'https://addons-frontend/fxa-authenticate',
    'scope': 'profile',
}


class TestInternalAddonSearchView(ESTestCase):
    client_class = APITestClient
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
        # Just to cache the waffle switch, to avoid polluting the
        # assertNumQueries() call later
        waffle.switch_is_active('boost-webextensions-in-search')
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
        self.client.login(email=user.username)
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 401

    def test_basic(self):
        addon = addon_factory(
            name=u'My Addôn', slug='my-addon', status=amo.STATUS_NULL,
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED},
            weekly_downloads=666)
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn',
                               weekly_downloads=555)
        addon2.delete()
        self.refresh()

        data = self.perform_search_with_senior_editor(self.url)  # No query.
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['status'] == 'incomplete'
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'
        assert result['last_updated'] == addon.last_updated.isoformat() + 'Z'
        assert result['latest_unlisted_version']
        assert (result['latest_unlisted_version']['id'] ==
                addon.latest_unlisted_version.pk)

        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] is None  # Because it was deleted.
        assert result['status'] == 'deleted'
        assert result['latest_unlisted_version'] is None

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


class TestInternalAddonViewSetDetail(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestInternalAddonViewSetDetail, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self._set_tested_url(self.addon.pk)
        user = UserProfile.objects.create(username='reviewer-admin-tools')
        self.grant_permission(user, 'ReviewerAdminTools:View')
        self.client.login_api(user)

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'
        assert result['last_updated'] == (
            self.addon.last_updated.isoformat() + 'Z')
        assert 'latest_unlisted_version' in result
        return result

    def _set_tested_url(self, param):
        self.url = reverse('internal-addon-detail', kwargs={'pk': param})

    def test_get_by_id(self):
        self._test_url()

    def test_get_by_slug(self):
        self._set_tested_url(self.addon.slug)
        self._test_url()

    def test_get_by_guid(self):
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_by_guid_uppercase(self):
        self._set_tested_url(self.addon.guid.upper())
        self._test_url()

    def test_get_by_guid_email_format(self):
        self.addon.update(guid='my-addon@example.tld')
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_by_guid_email_short_format(self):
        self.addon.update(guid='@example.tld')
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_by_guid_email_really_short_format(self):
        self.addon.update(guid='@example')
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_anonymous(self):
        self.client.logout_api()
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_get_no_rights(self):
        self.client.logout_api()
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_no_rights_even_if_reviewer(self):
        self.client.logout_api()
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_no_rights_even_if_author(self):
        self.client.logout_api()
        user = UserProfile.objects.create(username='author')
        self.addon.addonuser_set.create(user=user, addon=self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_not_listed(self):
        self.make_addon_unlisted(self.addon)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_deleted(self):
        self.addon.delete()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_addon_not_found(self):
        self._set_tested_url(self.addon.pk + 42)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_show_latest_unlisted_version_unlisted(self):
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert result['latest_unlisted_version']
        assert result['latest_unlisted_version']['id'] == unlisted_version.pk


class TestLoginStartView(TestCase):

    def test_internal_config_is_used(self):
        assert views.LoginStartView.DEFAULT_FXA_CONFIG_NAME == 'internal'


def has_cors_headers(response, origin='https://addons-frontend'):
    return (
        response['Access-Control-Allow-Origin'] == origin and
        response['Access-Control-Allow-Credentials'] == 'true')


def update_domains(overrides):
    overrides = overrides.copy()
    overrides['CORS_ORIGIN_WHITELIST'] = ['addons-frontend', 'localhost:3000']
    return overrides
