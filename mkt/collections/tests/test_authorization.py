from django.contrib.auth.models import User

from nose.tools import eq_

from access.middleware import ACLMiddleware
from amo.tests import TestCase
from mkt.collections.authorization import PublisherAuthorization
from mkt.site.fixtures import fixture
from test_utils import RequestFactory


class TestPublisherAuthorization(TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestPublisherAuthorization, self).setUp()
        self.auth = PublisherAuthorization()
        self.get = RequestFactory().get('/')
        self.post = RequestFactory().post('/')
        self.user = User.objects.get(pk=2519)

    def setup_request(self, request, grant_permission=False):
        request.user = self.user
        if grant_permission:
            self.grant_permission(self.user.get_profile(), 'Apps:Publisher')
        ACLMiddleware().process_request(request)

    def test_get_no_perms(self):
        self.setup_request(self.get)
        eq_(self.auth.has_permission(self.get, None), True)

    def test_get_with_perms(self):
        self.setup_request(self.get, grant_permission=True)
        eq_(self.auth.has_permission(self.get, None), True)

    def test_post_no_perms(self):
        self.setup_request(self.post)
        eq_(self.auth.has_permission(self.post, None), False)

    def test_post_with_perms(self):
        self.setup_request(self.post, grant_permission=True)
        eq_(self.auth.has_permission(self.post, None), True)
