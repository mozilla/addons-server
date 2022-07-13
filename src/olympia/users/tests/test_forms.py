import ipaddress

from django.urls import reverse

from olympia.amo.tests import TestCase
from olympia.users.models import (
    IPNetworkUserRestriction,
    RESTRICTION_TYPES,
    UserProfile,
)


class UserFormBase(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get(pk=4043307)


class TestDeniedNameAdminAddForm(UserFormBase):
    def test_no_usernames(self):
        self.client.force_login(self.user)
        url = reverse('admin:users_deniedname_add')
        data = {
            'names': '\n\n',
        }
        r = self.client.post(url, data)
        self.assertFormError(r, 'form', 'names', 'This field is required.')

    def test_add(self):
        self.client.force_login(self.user)
        url = reverse('admin:users_deniedname_add')
        data = {
            'names': 'IE6Fan\nfubar\n\n',
        }
        r = self.client.post(url, data)
        msg = '1 new values added to the deny list. '
        msg += '1 duplicates were ignored.'
        self.assertContains(r, msg)
        self.assertNotContains(r, 'fubar')


class TestIPNetworkUserRestrictionForm(UserFormBase):
    def test_add_converts_ipaddress_to_network(self):
        self.client.force_login(self.user)
        url = reverse('admin:users_ipnetworkuserrestriction_add')
        data = {
            'ip_address': '192.168.1.32',
            'restriction_type': str(RESTRICTION_TYPES.SUBMISSION),
        }
        response = self.client.post(url, data)

        assert response.status_code == 302
        restriction = IPNetworkUserRestriction.objects.get()

        assert restriction.network == ipaddress.IPv4Network('192.168.1.32/32')

    def test_add_validates_ip_address(self):
        self.client.force_login(self.user)
        url = reverse('admin:users_ipnetworkuserrestriction_add')
        data = {
            'ip_address': '192.168.1.0/28',
            'restriction_type': str(RESTRICTION_TYPES.SUBMISSION),
        }
        response = self.client.post(url, data)

        assert response.status_code == 200
        assert b'Enter a valid IPv4 or IPv6 address.' in response.content
        assert IPNetworkUserRestriction.objects.first() is None

        data = {
            'ip_address': '192.168.1.1',
            'restriction_type': str(RESTRICTION_TYPES.SUBMISSION),
        }
        response = self.client.post(url, data)

        assert response.status_code == 302
        restriction = IPNetworkUserRestriction.objects.get()

        assert restriction.network == ipaddress.IPv4Network('192.168.1.1/32')
