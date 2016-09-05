# -*- coding: utf-8 -*-
import base64
import json
import urlparse

from django.conf import settings
from django.core.urlresolvers import reverse
from django.test import override_settings

import mock
from rest_framework_jwt.serializers import VerifyJSONWebTokenSerializer

from olympia.accounts import verify, views
from olympia.accounts.tests.test_views import BaseAuthenticationView
from olympia.amo.tests import (
    addon_factory, APITestClient, ESTestCase, TestCase)
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
        assert result['is_listed'] is False
        assert result['status'] == 'public'
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'
        assert result['last_updated'] == addon.last_updated.isoformat()

        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] is None  # Because it was deleted.
        assert result['status'] == 'deleted'

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


@override_settings(FXA_CONFIG={'internal': FXA_CONFIG})
class TestLoginStartView(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestLoginStartView, self).setUp()
        self.url = reverse('internal-login-start')

    def test_state_is_set(self):
        self.initialize_session({})
        assert 'fxa_state' not in self.client.session
        state = 'somerandomstate'
        with mock.patch('olympia.internal_tools.views.generate_fxa_state',
                        lambda: state):
            self.client.get(self.url)
        assert 'fxa_state' in self.client.session
        assert self.client.session['fxa_state'] == state

    def test_redirect_url_is_correct(self):
        self.initialize_session({})
        with mock.patch('olympia.internal_tools.views.generate_fxa_state',
                        lambda: 'arandomstring'):
            response = self.client.get(self.url)
        assert response.status_code == 302
        url = urlparse.urlparse(response['location'])
        redirect = '{scheme}://{netloc}{path}'.format(
            scheme=url.scheme, netloc=url.netloc, path=url.path)
        assert redirect == 'https://accounts.firefox.com/v1/authorization'
        assert urlparse.parse_qs(url.query) == {
            'action': ['signin'],
            'client_id': ['999abc111'],
            'redirect_url': ['https://addons-frontend/fxa-authenticate'],
            'scope': ['profile'],
            'state': ['arandomstring'],
        }

    def test_state_is_not_overriden(self):
        self.initialize_session({'fxa_state': 'thisisthestate'})
        self.client.get(self.url)
        assert self.client.session['fxa_state'] == 'thisisthestate'

    def test_to_is_included_in_redirect_state(self):
        path = '/addons/unlisted-addon/'
        # The =s will be stripped from the URL.
        assert '=' in base64.urlsafe_b64encode(path)
        state = 'somenewstatestring'
        self.initialize_session({})
        with mock.patch('olympia.internal_tools.views.generate_fxa_state',
                        lambda: state):
            response = self.client.get(
                '{url}?to={path}'.format(path=path, url=self.url))
        assert self.client.session['fxa_state'] == state
        url = urlparse.urlparse(response['location'])
        query = urlparse.parse_qs(url.query)
        state_parts = query['state'][0].split(':')
        assert len(state_parts) == 2
        assert state_parts[0] == state
        assert '=' not in state_parts[1]
        assert base64.urlsafe_b64decode(state_parts[1] + '====') == path

    def test_to_is_excluded_when_unsafe(self):
        path = 'https://www.google.com'
        self.initialize_session({})
        response = self.client.get(
            '{url}?to={path}'.format(path=path, url=self.url))
        url = urlparse.urlparse(response['location'])
        query = urlparse.parse_qs(url.query)
        assert ':' not in query['state'][0]


def has_cors_headers(response, origin='https://addons-frontend'):
    return (
        response['Access-Control-Allow-Origin'] == origin and
        response['Access-Control-Allow-Credentials'] == 'true')


def update_domains(overrides):
    overrides = overrides.copy()
    overrides['CORS_ORIGIN_WHITELIST'] = ['addons-frontend', 'localhost:3000']
    return overrides

endpoint_overrides = [
    (regex, update_domains(overrides))
    for regex, overrides in settings.CORS_ENDPOINT_OVERRIDES]


@override_settings(
    FXA_CONFIG={'internal': FXA_CONFIG},
    CORS_ENDPOINT_OVERRIDES=endpoint_overrides)
class TestLoginView(BaseAuthenticationView):
    client_class = APITestClient
    view_name = 'internal-login'

    def setUp(self):
        super(TestLoginView, self).setUp()
        self.client.defaults['HTTP_ORIGIN'] = 'https://addons-frontend'
        self.state = 'stateaosidoiajsdaagdsasi'
        self.initialize_session({'fxa_state': self.state})
        self.code = 'codeaosidjoiajsdioasjdoa'
        self.update_user = self.patch(
            'olympia.internal_tools.views.update_user')

    def post(self, **kwargs):
        kwargs.setdefault('state', self.state)
        kwargs.setdefault('code', self.code)
        return self.client.post(self.url, kwargs)

    def options(self, url, origin):
        return self.client_class(HTTP_ORIGIN=origin).options(url)

    def test_no_code_provided(self):
        response = self.post(code='')
        assert response.status_code == 422
        assert response.data['error'] == views.ERROR_NO_CODE
        assert not self.update_user.called
        assert has_cors_headers(response)

    def test_wrong_state(self):
        response = self.post(state='a-different-state')
        assert response.status_code == 400
        assert response.data['error'] == views.ERROR_STATE_MISMATCH
        assert not self.update_user.called
        assert has_cors_headers(response)

    def test_no_fxa_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.post()
        assert response.status_code == 401
        assert response.data['error'] == views.ERROR_NO_PROFILE
        self.fxa_identify.assert_called_with(self.code, config=FXA_CONFIG)
        assert not self.update_user.called
        assert has_cors_headers(response)

    def test_no_amo_account_cant_login(self):
        self.fxa_identify.return_value = {'email': 'me@yeahoo.com', 'uid': '5'}
        response = self.post()
        assert response.status_code == 422
        assert response.data['error'] == views.ERROR_NO_USER
        self.fxa_identify.assert_called_with(self.code, config=FXA_CONFIG)
        assert not self.update_user.called
        assert has_cors_headers(response)

    def test_login_success(self):
        user = UserProfile.objects.create(
            username='foobar', email='real@yeahoo.com')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.post()
        assert response.status_code == 200
        assert response.data['email'] == 'real@yeahoo.com'
        assert 'jwt_api_auth_token' not in self.client.cookies
        verify = VerifyJSONWebTokenSerializer().validate(response.data)
        assert verify['user'] == user
        self.update_user.assert_called_with(user, identity)
        assert has_cors_headers(response)

    def test_account_exists_migrated_multiple(self):
        """Test that login fails if the user is logged in but the fxa_id is
        set on a different UserProfile."""
        UserProfile.objects.create(email='real@yeahoo.com', username='foo')
        UserProfile.objects.create(
            email='different@yeahoo.com', fxa_id='9005', username='bar')
        self.fxa_identify.return_value = {'email': 'real@yeahoo.com',
                                          'uid': '9005'}
        with self.assertRaises(UserProfile.MultipleObjectsReturned):
            response = self.post()
            assert has_cors_headers(response)
        assert not self.update_user.called

    def test_cors_addons_frontend(self):
        response = self.options(self.url, origin='https://addons-frontend')
        assert has_cors_headers(response, origin='https://addons-frontend')
        assert response.status_code == 200

    def test_cors_localhost(self):
        response = self.options(self.url, origin='http://localhost:3000')
        assert has_cors_headers(response, origin='http://localhost:3000')
        assert response.status_code == 200

    def test_cors_other(self):
        response = self.options(self.url, origin='https://attacker.com')
        assert 'Access-Control-Allow-Origin' not in response
        assert 'Access-Control-Allow-Methods' not in response
        assert 'Access-Control-Allow-Headers' not in response
        assert 'Access-Control-Allow-Credentials' not in response
        assert response.status_code == 200
