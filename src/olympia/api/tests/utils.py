from datetime import datetime

from rest_framework.test import APITestCase

from olympia.api.authentication import JWTKeyAuthentication
from olympia.api.tests.test_jwt_auth import JWTAuthKeyTester
from olympia.users.models import UserProfile


class APIKeyAuthTestCase(APITestCase, JWTAuthKeyTester):
    def create_api_user(self):
        self.user = UserProfile.objects.create(
            username='amo', email='a@m.o', read_dev_agreement=datetime.today()
        )
        self.api_key = self.create_api_key(self.user, str(self.user.pk) + ':f')

    def authorization(self):
        """
        Creates a suitable JWT auth token.
        """
        token = self.create_auth_token(
            self.api_key.user, self.api_key.key, self.api_key.secret
        )
        return 'JWT {}'.format(token)

    def get(self, url, **client_kwargs):
        return self.client.get(
            url, HTTP_AUTHORIZATION=self.authorization(), **client_kwargs
        )

    def post(self, url, data, **client_kwargs):
        return self.client.post(
            url, data, HTTP_AUTHORIZATION=self.authorization(), **client_kwargs
        )

    def auth_required(self, cls):
        """
        Tests that the JWT Auth class is on the class, without having
        to do a full request response cycle.
        """
        assert cls.authentication_classes == [JWTKeyAuthentication]

    def verbs_allowed(self, cls, verbs):
        """
        Tests that the verbs you expect on the class are present and no more.
        Options is added if you don't pass it.
        """
        verbs = set(v.upper() for v in verbs)
        verbs.add('OPTIONS')
        assert not set(cls._allowed_methods(cls())).difference(verbs)
