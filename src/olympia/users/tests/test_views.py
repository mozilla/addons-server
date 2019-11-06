from datetime import datetime, timedelta

from django.conf import settings

from dateutil.parser import parse
from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.users.models import UserProfile


class UserViewBase(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(UserViewBase, self).setUp()
        self.client = amo.tests.TestClient()
        self.client.get('/')
        self.user = UserProfile.objects.get(id='4043307')

    def get_profile(self):
        return UserProfile.objects.get(id=self.user.id)


class TestLogin(UserViewBase):
    fixtures = ['users/test_backends']

    def test_client_login(self):
        """
        This is just here to make sure Test Client's login() works with
        our custom code.
        """
        assert self.client.login(email='jbalogh@mozilla.com')

    def test_login_link(self):
        r = self.client.get(reverse('apps.appversions'))
        assert r.status_code == 200
        assert pq(r.content)('#aux-nav li.login').length == 1

    def test_logout_link(self):
        self.test_client_login()
        r = self.client.get(reverse('apps.appversions'))
        assert r.status_code == 200
        assert pq(r.content)('#aux-nav li.logout').length == 1


class TestSessionLength(UserViewBase):
    def test_session_does_not_expire_quickly(self):
        """Make sure no one is overriding our settings and making sessions
        expire at browser session end. See:
        https://github.com/mozilla/addons-server/issues/1789
        """
        self.client.login(email='jbalogh@mozilla.com')
        r = self.client.get('/developers/', follow=True)
        cookie = r.cookies[settings.SESSION_COOKIE_NAME]

        # The user's session should be valid for at least four weeks (near a
        # month).
        four_weeks_from_now = datetime.now() + timedelta(days=28)
        expiry = parse(cookie['expires']).replace(tzinfo=None)

        assert cookie.value != ''
        assert expiry >= four_weeks_from_now
