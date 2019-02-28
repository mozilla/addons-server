from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.users import notifications as email
from olympia.users.models import UserNotification, UserProfile
from olympia.users.utils import UnsubscribeCode


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
        r = self.client.get(reverse('home'))
        assert r.status_code == 200
        assert pq(r.content)('#aux-nav li.login').length == 1

    def test_logout_link(self):
        self.test_client_login()
        r = self.client.get(reverse('home'))
        assert r.status_code == 200
        assert pq(r.content)('#aux-nav li.logout').length == 1


class TestUnsubscribe(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestUnsubscribe, self).setUp()
        self.user = UserProfile.objects.get(email='reviewer@mozilla.com')

    def test_correct_url_update_notification(self):
        # Make sure the user is subscribed
        perm_setting = email.NOTIFICATIONS_COMBINED[0]
        un = UserNotification.objects.create(notification_id=perm_setting.id,
                                             user=self.user,
                                             enabled=True)

        # Create a URL
        token, hash = UnsubscribeCode.create(self.user.email)
        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])

        # Load the URL
        r = self.client.get(url)
        doc = pq(r.content)

        # Check that it was successful
        assert doc('#unsubscribe-success').length
        assert doc('#standalone').length
        assert doc('#standalone ul li').length == 1

        # Make sure the user is unsubscribed
        un = UserNotification.objects.filter(notification_id=perm_setting.id,
                                             user=self.user)
        assert un.count() == 1
        assert not un.all()[0].enabled

    def test_correct_url_new_notification(self):
        # Make sure the user is subscribed
        assert not UserNotification.objects.count()

        # Create a URL
        perm_setting = email.NOTIFICATIONS_COMBINED[0]
        token, hash = UnsubscribeCode.create(self.user.email)
        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])

        # Load the URL
        r = self.client.get(url)
        doc = pq(r.content)

        # Check that it was successful
        assert doc('#unsubscribe-success').length
        assert doc('#standalone').length
        assert doc('#standalone ul li').length == 1

        # Make sure the user is unsubscribed
        un = UserNotification.objects.filter(notification_id=perm_setting.id,
                                             user=self.user)
        assert un.count() == 1
        assert not un.all()[0].enabled

    def test_wrong_url(self):
        perm_setting = email.NOTIFICATIONS_COMBINED[0]
        token, hash = UnsubscribeCode.create(self.user.email)
        hash = hash[::-1]  # Reverse the hash, so it's wrong

        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])
        r = self.client.get(url)
        doc = pq(r.content)

        assert doc('#unsubscribe-fail').length == 1
