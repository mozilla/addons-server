import json

from datetime import datetime, timedelta

from django.conf import settings
from django.utils.encoding import force_text

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


class TestAjax(UserViewBase):

    def setUp(self):
        super(TestAjax, self).setUp()
        self.client.login(email='jbalogh@mozilla.com')

    def test_ajax_404(self):
        r = self.client.get(reverse('users.ajax'), follow=True)
        assert r.status_code == 404

    def test_ajax_success(self):
        r = self.client.get(reverse('users.ajax'), {'q': 'fligtar@gmail.com'},
                            follow=True)
        data = json.loads(force_text(r.content))
        assert data == {
            'status': 1, 'message': '', 'id': 9945,
            'name': u'Justin Scott \u0627\u0644\u062a\u0637\u0628'}

    def test_ajax_xss(self):
        self.user.display_name = '<script>alert("xss")</script>'
        self.user.save()
        assert '<script>' in self.user.display_name, (
            'Expected <script> to be in display name')
        r = self.client.get(reverse('users.ajax'),
                            {'q': self.user.email, 'dev': 0})
        assert b'<script>' not in r.content
        assert b'&lt;script&gt;' in r.content

    def test_ajax_failure_incorrect_email(self):
        r = self.client.get(reverse('users.ajax'), {'q': 'incorrect'},
                            follow=True)
        data = json.loads(force_text(r.content))
        assert data == (
            {'status': 0,
             'message': 'A user with that email address does not exist.'})

    def test_ajax_failure_no_email(self):
        r = self.client.get(reverse('users.ajax'), {'q': ''}, follow=True)
        data = json.loads(force_text(r.content))
        assert data == (
            {'status': 0,
             'message': 'An email address is required.'})

    def test_forbidden(self):
        self.client.logout()
        r = self.client.get(reverse('users.ajax'))
        assert r.status_code == 401


class TestLogin(UserViewBase):
    fixtures = ['users/test_backends']

    def test_client_login(self):
        """
        This is just here to make sure Test Client's login() works with
        our custom code.
        """
        assert self.client.login(email='jbalogh@mozilla.com')

    def test_login_link(self):
        r = self.client.get(reverse('home'))
        assert r.status_code == 200
        assert pq(r.content)('#aux-nav li.login').length == 1

    def test_logout_link(self):
        self.test_client_login()
        r = self.client.get(reverse('home'))
        assert r.status_code == 200
        assert pq(r.content)('#aux-nav li.logout').length == 1


class TestSessionLength(UserViewBase):

    def test_session_does_not_expire_quickly(self):
        """Make sure no one is overriding our settings and making sessions
        expire at browser session end. See:
        https://github.com/mozilla/addons-server/issues/1789
        """
        self.client.login(email='jbalogh@mozilla.com')
        r = self.client.get('/', follow=True)
        cookie = r.cookies[settings.SESSION_COOKIE_NAME]

        # The user's session should be valid for at least four weeks (near a
        # month).
        four_weeks_from_now = datetime.now() + timedelta(days=28)
        expiry = parse(cookie['expires']).replace(tzinfo=None)

        assert cookie.value != ''
        assert expiry >= four_weeks_from_now
