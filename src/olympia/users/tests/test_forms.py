import ipaddress

from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.users.models import UserProfile, IPNetworkUserRestriction


class UserFormBase(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(UserFormBase, self).setUp()
        self.user = self.user_profile = UserProfile.objects.get(id='4043307')


class TestDeniedNameAdminAddForm(UserFormBase):

    def test_no_usernames(self):
        self.client.login(email='testo@example.com')
        url = reverse('admin:users_deniedname_add')
        data = {'names': '\n\n', }
        r = self.client.post(url, data)
        self.assertFormError(r, 'form', 'names', u'This field is required.')

    def test_add(self):
        self.client.login(email='testo@example.com')
        url = reverse('admin:users_deniedname_add')
        data = {'names': 'IE6Fan\nfubar\n\n', }
        r = self.client.post(url, data)
        msg = '1 new values added to the deny list. '
        msg += '1 duplicates were ignored.'
        self.assertContains(r, msg)
        self.assertNotContains(r, 'fubar')


class TestIPNetworkUserRestrictionForm(UserFormBase):
    def test_add_converts_ipaddress_to_network(self):
        self.client.login(email='testo@example.com')
        url = reverse('admin:users_ipnetworkuserrestriction_add')
        data = {'ip_address': '192.168.1.32'}
        response = self.client.post(url, data)

        assert response.status_code == 302
        restriction = IPNetworkUserRestriction.objects.get()

        assert restriction.network == ipaddress.IPv4Network('192.168.1.32/32')

    def test_add_validates_ip_address(self):
        self.client.login(email='testo@example.com')
        url = reverse('admin:users_ipnetworkuserrestriction_add')
        data = {'ip_address': '192.168.1.0/28'}
        response = self.client.post(url, data)

        assert response.status_code == 200
        assert b'Enter a valid IPv4 or IPv6 address.' in response.content
        assert IPNetworkUserRestriction.objects.first() is None

        data = {'ip_address': '192.168.1.1'}
        response = self.client.post(url, data)

        assert response.status_code == 302
        restriction = IPNetworkUserRestriction.objects.get()

        assert restriction.network == ipaddress.IPv4Network('192.168.1.1/32')
