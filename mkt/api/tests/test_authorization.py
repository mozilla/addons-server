from django.contrib.auth.models import AnonymousUser, User

from nose.tools import eq_

from amo.tests import TestCase
from test_utils import RequestFactory

from mkt.api.authorization import AnonymousReadOnlyAuthorization
from mkt.site.fixtures import fixture


class TestAnonymousReadOnlyAuthorization(TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.get = RequestFactory().get('/')
        self.post = RequestFactory().post('/')
        self.auth = AnonymousReadOnlyAuthorization()
        self.anon = AnonymousUser()
        self.user = User.objects.get(pk=2519)

    def test_get_anonymous(self):
        self.get.user = self.anon
        eq_(self.auth.is_authorized(self.get), True)

    def test_get_authenticated(self):
        self.get.user = self.user
        eq_(self.auth.is_authorized(self.get), True)

    def test_post_anonymous(self):
        self.post.user = self.anon
        eq_(self.auth.is_authorized(self.post), False)

    def test_post_authenticated(self):
        self.post.user = self.user
        eq_(self.auth.is_authorized(self.post), True)
