import ipaddress

from django.urls import reverse

from olympia.amo.tests import TestCase
from olympia.users.models import (
    RESTRICTION_TYPES,
    EmailUserRestriction,
    IPNetworkUserRestriction,
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


class TestEmailUserRestrictionAdminForm(UserFormBase):
    def test_normalized_pattern_raises_validation_error(self):
        EmailUserRestriction.objects.create(
            email_pattern='foo@example.com',
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        )
        self.client.force_login(self.user)
        url = reverse('admin:users_emailuserrestriction_add')
        data = {
            'email_pattern': 'foo+bar@example.com',
            'restriction_type': str(RESTRICTION_TYPES.ADDON_SUBMISSION),
        }
        response = self.client.post(url, data)
        assert response.status_code == 200
        assert b'Email Pattern and Restriction type already exists' in response.content

    def test_record_normalized_pattern(self):
        # Note: this would happen because of the custom save() method in the
        # model anyway.
        self.client.force_login(self.user)
        url = reverse('admin:users_emailuserrestriction_add')
        data = {
            'email_pattern': 'foo+bar@example.com',
            'restriction_type': str(RESTRICTION_TYPES.ADDON_SUBMISSION),
        }
        response = self.client.post(url, data)
        assert response.status_code == 302
        assert EmailUserRestriction.objects.count() == 1
        restriction = EmailUserRestriction.objects.get()
        assert restriction.email_pattern == 'foo@example.com'
        assert restriction.restriction_type == RESTRICTION_TYPES.ADDON_SUBMISSION


class TestIPNetworkUserRestrictionForm(UserFormBase):
    def test_add_converts_ipaddress_to_network(self):
        self.client.force_login(self.user)
        url = reverse('admin:users_ipnetworkuserrestriction_add')
        data = {
            'ip_address': '192.168.1.32',
            'restriction_type': str(RESTRICTION_TYPES.ADDON_SUBMISSION),
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
            'restriction_type': str(RESTRICTION_TYPES.ADDON_SUBMISSION),
        }
        response = self.client.post(url, data)

        assert response.status_code == 200
        assert b'Enter a valid IPv4 or IPv6 address.' in response.content
        assert IPNetworkUserRestriction.objects.first() is None

        data = {
            'ip_address': '192.168.1.1',
            'restriction_type': str(RESTRICTION_TYPES.ADDON_SUBMISSION),
        }
        response = self.client.post(url, data)

        assert response.status_code == 302
        restriction = IPNetworkUserRestriction.objects.get()

        assert restriction.network == ipaddress.IPv4Network('192.168.1.1/32')
