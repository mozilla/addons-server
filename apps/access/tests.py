from django.http import HttpRequest

import mock
from nose.tools import assert_false, eq_
from test_utils import TestCase

import amo
from amo.urlresolvers import reverse
from addons.models import Addon, AddonUser
from cake.models import Session
from users.models import UserProfile

from .acl import match_rules, action_allowed, check_addon_ownership


def test_match_rules():
    """
    Unit tests for the match_rules method.
    """

    rules = ('*:*',
        'Editors:*,Admin:EditAnyAddon,Admin:flagged,Admin:addons,'
        'Admin:EditAnyCollection',
        'Tests:*,Admin:serverstatus,Admin:users',
        'Admin:EditAnyAddon,Admin:EditAnyLocale,Editors:*,'
        'Admin:lists,Admin:applications,Admin:addons,Localizers:*',
        'Admin:EditAnyAddon',
        'Admin:ViewAnyStats,Admin:ViewAnyCollectionStats',
        'Admin:ViewAnyStats',
        'Editors:*,Admin:features',
        'Admin:Statistics',
        'Admin:Features,Editors:*',
        'Admin:%',
        'Admin:*',
        'Admin:Foo',
        'Admin:Bar',
        )

    for rule in rules:
        assert match_rules(rule, 'Admin', '%'), "%s != Admin:%%" % rule

    rules = ('Doctors:*',)

    for rule in rules:
        assert not match_rules(rule, 'Admin', '%'), \
            "%s == Admin:%% and shouldn't" % rule


def test_anonymous_user():
    # Fake request must not have .groups, just like an anonymous user.
    fake_request = HttpRequest()
    assert_false(action_allowed(fake_request, amo.FIREFOX, 'Admin:%'))


class ACLTestCase(TestCase):
    """
    Test some basic ACLs by going to various locked pages on AMO.
    """

    fixtures = ['access/login.json']

    def test_admin_login_anon(self):
        """
        Login form for anonymous user on the admin page.
        """
        url = '/en-US/admin/models/'
        r = self.client.get(url)
        self.assertRedirects(r, '%s?to=%s' % (reverse('users.login'), url))

    def test_admin_login_adminuser(self):
        """
        No form should be present for an admin
        """
        c = self.client
        session = Session.objects.get(pk='1234')
        c.login(session=session)
        response = c.get('/en-US/admin/models/')
        assert response.context['user'].is_authenticated()
        self.assertNotContains(response, 'login-form')

    def test_admin_login(self):
        """
        Non admin user should see a login form.
        """
        session = Session.objects.get(pk='4567')
        self.client.login(session=session)
        url = '/en-US/admin/models/'
        r = self.client.get(url)
        self.assertRedirects(r, '%s?to=%s' % (reverse('users.login'), url))


class TestHasPerm(TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.addon = Addon.objects.get(id=3615)
        self.au = AddonUser.objects.get(addon=self.addon, user=self.user)
        assert self.au.role == amo.AUTHOR_ROLE_OWNER
        self.request = mock.Mock()
        self.request.groups = ()
        self.request.amo_user = self.user
        self.request.user.is_authenticated.return_value = True

    def login_admin(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        return UserProfile.objects.get(email='admin@mozilla.com')

    def test_anonymous(self):
        self.request.user.is_authenticated.return_value = False
        self.client.logout()
        assert not check_addon_ownership(self.request, self.addon)

    def test_admin(self):
        self.request.amo_user = self.login_admin()
        self.request.groups = self.request.amo_user.groups.all()
        assert check_addon_ownership(self.request, self.addon)

    def test_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert not check_addon_ownership(self.request, self.addon)
        self.test_admin()

    def test_ignore_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert check_addon_ownership(self.request, self.addon, ignore_disabled=True)

    def test_owner(self):
        assert check_addon_ownership(self.request, self.addon)

        self.au.role = amo.AUTHOR_ROLE_DEV
        self.au.save()
        assert not check_addon_ownership(self.request, self.addon)

        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        assert not check_addon_ownership(self.request, self.addon)

    def test_dev(self):
        assert check_addon_ownership(self.request, self.addon, dev=True)

        self.au.role = amo.AUTHOR_ROLE_DEV
        self.au.save()
        assert check_addon_ownership(self.request, self.addon, dev=True)

        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        assert not check_addon_ownership(self.request, self.addon, dev=True)

    def test_viewer(self):
        assert check_addon_ownership(self.request, self.addon, viewer=True)

        self.au.role = amo.AUTHOR_ROLE_DEV
        self.au.save()
        assert check_addon_ownership(self.request, self.addon, viewer=True)

        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        assert check_addon_ownership(self.request, self.addon, viewer=True)
