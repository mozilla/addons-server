from nose.tools import eq_

from amo.urlresolvers import reverse
from amo.tests import TestCase


class TestViews(TestCase):
    fixtures = ['base/users.json']

    def setUp(self):
        assert self.client.login(username='support-staff@mozilla.com',
                                 password='password')

    def test_authorization(self):
        self.client.logout()
        res = self.client.get(reverse('acct_lookup.home'))
        eq_(res.status_code, 302)
