from django.http import HttpRequest

import mock
from nose.tools import assert_false, eq_

import amo
from amo.urlresolvers import reverse
from cake.models import Session
from test_utils import TestCase

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


class TestCheckOwnership(TestCase):

    def setUp(self):
        self.request = mock.Mock()
        self.request.groups = ()
        self.addon = mock.Mock()

    def test_unauthenticated(self):
        self.request.user.is_authenticated = lambda: False
        eq_(False, check_addon_ownership(self.request, self.addon))

    @mock.patch('access.acl.action_allowed')
    def test_admin(self, allowed):
        eq_(True, check_addon_ownership(self.request, self.addon))
        eq_(True, check_addon_ownership(self.request, self.addon,
                                  require_owner=True))

    def test_author_roles(self):
        f = self.addon.authors.filter
        roles = (amo.AUTHOR_ROLE_OWNER, amo.AUTHOR_ROLE_DEV)

        check_addon_ownership(self.request, self.addon, True)
        eq_(f.call_args[1]['addonuser__role__in'], roles)

        check_addon_ownership(self.request, self.addon)
        eq_(f.call_args[1]['addonuser__role__in'],
            roles + (amo.AUTHOR_ROLE_VIEWER,))
