from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from users.models import UserProfile


class TestTerms(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.url = reverse('submit.terms')
        self.user = self.get_user()
        assert self.client.login(username=self.user.email, password='password')

    def get_user(self):
        return UserProfile.objects.get(username='regularuser')

    def test_anonymous(self):
        self.client.logout()
        r = self.client.get(self.url, follow=True)
        self.assertLoginRedirects(r, self.url)

    def test_redirect_to_step(self):
        r = self.client.get(reverse('submit'), follow=True)
        self.assertRedirects(r, self.url)

    def test_submit(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#terms').length, 1)

    def test_agree(self):
        r = self.client.post(self.url, {'read_dev_agreement': True})
        self.assertRedirects(r, reverse('submit.describe'))
        eq_(self.get_user().read_dev_agreement, True)

    def test_disagree(self):
        r = self.client.post(self.url)
        eq_(r.status_code, 200)
        eq_(self.user.read_dev_agreement, False)
