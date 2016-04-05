from calendar import timegm
import mock
import json

from django.core.urlresolvers import reverse
from django.test import RequestFactory

import jwt
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from olympia.amo.helpers import absolutify
from olympia.amo.tests import TestCase, WithDynamicEndpoints
from olympia.api.authentication import (
    JSONWebTokenAuthentication, JWTKeyAuthentication)
from olympia.api.tests.test_jwt_auth import JWTAuthKeyTester
from olympia.users.models import UserProfile


class JWTKeyAuthTestView(APIView):
    """
    This is an example of a view that would be protected by
    JWTKeyAuthentication, used in TestJWTKeyAuthProtectedView below.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTKeyAuthentication]

    def get(self, request):
        return Response('some get response')

    def post(self, request):
        return Response({'user_pk': request.user.pk})


class TestJWTKeyAuthentication(JWTAuthKeyTester):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestJWTKeyAuthentication, self).setUp()
        self.factory = RequestFactory()
        self.auth = JWTKeyAuthentication()
        self.user = UserProfile.objects.get(email='del@icio.us')

    def request(self, token):
        return self.factory.get('/', HTTP_AUTHORIZATION='JWT {}'.format(token))

    def _create_token(self):
        api_key = self.create_api_key(self.user)
        return self.create_auth_token(api_key.user, api_key.key,
                                      api_key.secret)

    def test_get_user(self):
        user, _ = self.auth.authenticate(self.request(self._create_token()))
        assert user == self.user

    def test_unknown_issuer(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['iss'] = 'non-existant-issuer'
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request(token))
        assert ctx.exception.detail == 'Unknown JWT iss (issuer).'

    def test_deleted_user(self):
        self.user.update(deleted=True)

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request(self._create_token()))
        assert ctx.exception.detail == 'User account is disabled.'

    def test_user_has_not_read_agreement(self):
        self.user.update(read_dev_agreement=None)

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request(self._create_token()))
        assert ctx.exception.detail == 'User has not read developer agreement.'

    @mock.patch('olympia.api.jwt_auth.jwt_decode_handler')
    def test_decode_authentication_failed(self, jwt_decode_handler):
        jwt_decode_handler.side_effect = AuthenticationFailed

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request('whatever'))

        assert ctx.exception.detail == 'Incorrect authentication credentials.'

    @mock.patch('olympia.api.jwt_auth.jwt_decode_handler')
    def test_decode_expired_signature(self, jwt_decode_handler):
        jwt_decode_handler.side_effect = jwt.ExpiredSignature

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request('whatever'))

        assert ctx.exception.detail == 'Signature has expired.'

    @mock.patch('olympia.api.jwt_auth.jwt_decode_handler')
    def test_decode_decoding_error(self, jwt_decode_handler):
        jwt_decode_handler.side_effect = jwt.DecodeError

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request('whatever'))
        assert ctx.exception.detail == 'Error decoding signature.'

    @mock.patch('olympia.api.jwt_auth.jwt_decode_handler')
    def test_decode_invalid_token(self, jwt_decode_handler):
        jwt_decode_handler.side_effect = jwt.InvalidTokenError

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request('whatever'))
        assert ctx.exception.detail == 'Invalid JWT Token.'

    def test_refuse_refreshable_tokens(self):
        # We should not accept tokens that have an orig_iat field set.
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['orig_iat'] = timegm(payload['iat'].utctimetuple())
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request(token))
        assert ctx.exception.detail == (
            "API key based tokens are not refreshable, don't include "
            "`orig_iat` in their payload.")

    def test_cant_refresh_token(self):
        # Developers generate tokens, not us, they should not be refreshable,
        # the refresh implementation does not even know how to decode them.
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['orig_iat'] = timegm(payload['iat'].utctimetuple())
        token = self.encode_token_payload(payload, api_key.secret)

        refresh_token_url = reverse('frontend-token-refresh')
        response = self.client.post(refresh_token_url, data={'token': token})
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data == {'non_field_errors': ['Error decoding signature.']}


class TestJWTKeyAuthProtectedView(WithDynamicEndpoints, JWTAuthKeyTester):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestJWTKeyAuthProtectedView, self).setUp()
        self.endpoint(JWTKeyAuthTestView)
        self.client.logout_api()  # just to be sure!
        self.user = UserProfile.objects.get(email='del@icio.us')

    def request(self, method, *args, **kw):
        handler = getattr(self.client, method)
        return handler('/en-US/firefox/dynamic-endpoint', *args, **kw)

    def jwt_request(self, token, method, *args, **kw):
        return self.request(method,
                            HTTP_AUTHORIZATION='JWT {}'.format(token),
                            *args, **kw)

    def test_get_requires_auth(self):
        res = self.request('get')
        assert res.status_code == 401, res.content

    def test_post_requires_auth(self):
        res = self.request('post', {})
        assert res.status_code == 401, res.content

    def test_can_post_with_jwt_header(self):
        api_key = self.create_api_key(self.user)
        token = self.create_auth_token(api_key.user, api_key.key,
                                       api_key.secret)
        res = self.jwt_request(token, 'post', {})

        assert res.status_code == 200, res.content
        data = json.loads(res.content)
        assert data['user_pk'] == self.user.pk

    def test_api_key_must_be_active(self):
        api_key = self.create_api_key(self.user, is_active=False)
        token = self.create_auth_token(api_key.user, api_key.key,
                                       api_key.secret)
        res = self.jwt_request(token, 'post', {})
        assert res.status_code == 401, res.content


class TestJSONWebTokenAuthentication(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestJSONWebTokenAuthentication, self).setUp()
        self.auth = JSONWebTokenAuthentication()
        self.factory = RequestFactory()
        self.user = UserProfile.objects.get(email='del@icio.us')

    def _authenticate(self, token):
        url = absolutify('/api/whatever')
        request = self.factory.post(
            url, HTTP_HOST='testserver',
            HTTP_AUTHORIZATION='JWT {0}'.format(token))

        return self.auth.authenticate(request)

    def test_success(self):
        token = self.client.generate_api_token(self.user)
        user, _ = self._authenticate(token)
        assert user == self.user

    def test_refresh(self):
        token = self.client.generate_api_token(
            self.user, iat=self.days_ago(1),
            orig_iat=timegm(self.days_ago(2).utctimetuple()))
        refresh_token_url = reverse('frontend-token-refresh')
        response = self.client.post(refresh_token_url, data={'token': token})
        assert response.status_code == 200, response.content
        data = json.loads(response.content)
        assert data['token'] != token

        # Try new token.
        user, _ = self._authenticate(data['token'])
        assert user == self.user

    def test_refresh_too_old(self):
        token = self.client.generate_api_token(
            self.user, orig_iat=timegm(self.days_ago(8).utctimetuple()))
        refresh_token_url = reverse('frontend-token-refresh')
        response = self.client.post(refresh_token_url, data={'token': token})
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data == {'non_field_errors': ['Refresh has expired.']}

    def test_verify(self):
        token = self.client.generate_api_token(self.user)
        verify_token_url = reverse('frontend-token-verify')
        response = self.client.post(verify_token_url, data={'token': token})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['token'] == token
