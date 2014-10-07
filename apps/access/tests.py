from django.http import HttpRequest

import mock
from nose.tools import assert_false

import amo
from amo.tests import TestCase, req_factory_factory
from amo.urlresolvers import reverse
from addons.models import Addon, AddonUser
from users.models import UserProfile

from .acl import (action_allowed, check_addon_ownership, check_ownership,
                  check_addons_reviewer, check_personas_reviewer, is_editor,
                  match_rules)


def test_match_rules():
    """
    Unit tests for the match_rules method.
    """

    rules = (
        '*:*',
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

    rules = (
        'Doctors:*',
        'Stats:View',
        'CollectionStats:View',
        'Addons:Review',
        'Personas:Review',
        'Locales:Edit',
        'Locale.de:Edit',
        'Reviews:Edit',
        'None:None',
    )

    for rule in rules:
        assert not match_rules(rule, 'Admin', '%'), \
            "%s == Admin:%% and shouldn't" % rule


def test_anonymous_user():
    # Fake request must not have .groups, just like an anonymous user.
    fake_request = HttpRequest()
    assert_false(action_allowed(fake_request, amo.FIREFOX, 'Admin:%'))


class ACLTestCase(TestCase):
    """Test some basic ACLs by going to various locked pages on AMO."""
    fixtures = ['access/login.json']

    def test_admin_login_anon(self):
        # Login form for anonymous user on the admin page.
        url = '/en-US/admin/models/'
        r = self.client.get(url)
        self.assertRedirects(r, '%s?to=%s' % (reverse('users.login'), url))


class TestHasPerm(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

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
        assert check_addon_ownership(self.request, self.addon, admin=True)
        assert not check_addon_ownership(self.request, self.addon, admin=False)

    def test_require_author(self):
        assert check_ownership(self.request, self.addon, require_author=True)

    def test_require_author_when_admin(self):
        self.request.amo_user = self.login_admin()
        self.request.groups = self.request.amo_user.groups.all()
        assert check_ownership(self.request, self.addon, require_author=False)

        assert not check_ownership(self.request, self.addon,
                                   require_author=True)

    def test_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert not check_addon_ownership(self.request, self.addon)
        self.test_admin()

    def test_deleted(self):
        self.addon.update(status=amo.STATUS_DELETED)
        assert not check_addon_ownership(self.request, self.addon)
        self.request.amo_user = self.login_admin()
        self.request.groups = self.request.amo_user.groups.all()
        assert not check_addon_ownership(self.request, self.addon)

    def test_ignore_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert check_addon_ownership(self.request, self.addon,
                                     ignore_disabled=True)

    def test_owner(self):
        assert check_addon_ownership(self.request, self.addon)

        self.au.role = amo.AUTHOR_ROLE_DEV
        self.au.save()
        assert not check_addon_ownership(self.request, self.addon)

        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        assert not check_addon_ownership(self.request, self.addon)

        self.au.role = amo.AUTHOR_ROLE_SUPPORT
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

        self.au.role = amo.AUTHOR_ROLE_SUPPORT
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

        self.au.role = amo.AUTHOR_ROLE_SUPPORT
        self.au.save()
        assert check_addon_ownership(self.request, self.addon, viewer=True)

    def test_support(self):
        assert check_addon_ownership(self.request, self.addon, viewer=True)

        self.au.role = amo.AUTHOR_ROLE_DEV
        self.au.save()
        assert not check_addon_ownership(self.request, self.addon,
                                         support=True)

        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        assert not check_addon_ownership(self.request, self.addon,
                                         support=True)

        self.au.role = amo.AUTHOR_ROLE_SUPPORT
        self.au.save()
        assert check_addon_ownership(self.request, self.addon, support=True)


class TestCheckReviewer(TestCase):
    fixtures = ['base/addon_3615', 'addons/persona']

    def setUp(self):
        self.user = UserProfile.objects.get()
        self.persona = Addon.objects.get(pk=15663)
        self.addon = Addon.objects.get(pk=3615)

    def test_no_perm(self):
        req = req_factory_factory('noop', user=self.user)
        assert not check_addons_reviewer(req)
        assert not check_personas_reviewer(req)

    def test_perm_addons(self):
        self.grant_permission(self.user, 'Addons:Review')
        req = req_factory_factory('noop', user=self.user)
        assert check_addons_reviewer(req)
        assert not check_personas_reviewer(req)

    def test_perm_themes(self):
        self.grant_permission(self.user, 'Personas:Review')
        req = req_factory_factory('noop', user=self.user)
        assert not check_addons_reviewer(req)
        assert check_personas_reviewer(req)

    def test_is_editor_for_addon_reviewer(self):
        """An addon editor is also a persona editor."""
        self.grant_permission(self.user, 'Addons:Review')
        req = req_factory_factory('noop', user=self.user)
        assert is_editor(req, self.persona)
        assert is_editor(req, self.addon)

    def test_is_editor_for_persona_reviewer(self):
        self.grant_permission(self.user, 'Personas:Review')
        req = req_factory_factory('noop', user=self.user)
        assert is_editor(req, self.persona)
        assert not is_editor(req, self.addon)
