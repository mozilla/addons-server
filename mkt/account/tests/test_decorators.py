from django import http

import mock
from nose.tools import eq_

import amo.tests
from mkt.account.decorators import profile_view
from users.models import UserProfile


class TestAddonView(amo.tests.TestCase):

    def setUp(self):
        self.user = UserProfile.objects.create(username='foo')
        self.func = mock.Mock()
        self.func.return_value = self.user
        self.func.__name__ = 'mock_function'
        self.view = profile_view(self.func)
        self.request = mock.Mock()

    def test_username(self):
        eq_(self.view(self.request, str(self.user.username)), self.user)

    def test_404(self):
        with self.assertRaises(http.Http404):
            eq_(self.view(self.request, 'nope'), None)
