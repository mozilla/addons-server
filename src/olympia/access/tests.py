import mock
import pytest

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import addon_factory, TestCase, req_factory_factory
from olympia.users.models import UserProfile

from .acl import (
    action_allowed, check_addon_ownership, check_addons_reviewer,
    check_ownership, check_personas_reviewer, check_static_theme_reviewer,
    check_unlisted_addons_reviewer,
    is_reviewer, is_user_any_kind_of_reviewer, match_rules)


pytestmark = pytest.mark.django_db


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
        'Users:Edit',
        'None:None',
    )

    for rule in rules:
        assert not match_rules(rule, 'Admin', '%'), \
            "%s == Admin:%% and shouldn't" % rule


def test_anonymous_user():
    fake_request = req_factory_factory('/')
    assert not action_allowed(fake_request, amo.permissions.ANY_ADMIN)


class ACLTestCase(TestCase):
    """Test some basic ACLs by going to various locked pages on AMO."""
    fixtures = ['access/login.json']

    def test_admin_login_anon(self):
        # Login form for anonymous user on the admin page.
        url = '/en-US/admin/'
        self.assertLoginRedirects(self.client.get(url), to=url)


class TestHasPerm(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestHasPerm, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.addon = Addon.objects.get(id=3615)
        self.au = AddonUser.objects.get(addon=self.addon, user=self.user)
        assert self.au.role == amo.AUTHOR_ROLE_OWNER
        self.request = self.fake_request_with_user(self.user)

    def fake_request_with_user(self, user):
        request = mock.Mock()
        request.user = user
        request.user.is_authenticated = mock.Mock(return_value=True)
        return request

    def login_admin(self):
        assert self.client.login(email='admin@mozilla.com')
        return UserProfile.objects.get(email='admin@mozilla.com')

    def test_anonymous(self):
        self.request.user.is_authenticated.return_value = False
        self.client.logout()
        assert not check_addon_ownership(self.request, self.addon)

    def test_admin(self):
        self.request = self.fake_request_with_user(self.login_admin())
        assert check_addon_ownership(self.request, self.addon)
        assert check_addon_ownership(self.request, self.addon, admin=True)
        assert not check_addon_ownership(self.request, self.addon, admin=False)

    def test_require_author(self):
        assert check_ownership(self.request, self.addon, require_author=True)

    def test_require_author_when_admin(self):
        self.request = self.fake_request_with_user(self.login_admin())
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
        self.request.user = self.login_admin()
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

    def test_dev(self):
        assert check_addon_ownership(self.request, self.addon, dev=True)

        self.au.role = amo.AUTHOR_ROLE_DEV
        self.au.save()
        assert check_addon_ownership(self.request, self.addon, dev=True)

    def test_add_and_remove_group(self):
        group = Group.objects.create(name='A Test Group', rules='Test:Group')
        group_user = GroupUser.objects.create(group=group, user=self.user)
        assert self.user.groups_list == [group]

        # The groups_list property already existed. Make sure delete works.
        group_user.delete()
        assert self.user.groups_list == []

        group_user = GroupUser.objects.create(group=group, user=self.user)
        assert self.user.groups_list == [group]
        del self.user.groups_list
        # The groups_list didn't exist. Make sure delete works.
        group_user.delete()
        assert self.user.groups_list == []


class TestCheckReviewer(TestCase):
    fixtures = ['base/addon_3615', 'addons/persona']

    def setUp(self):
        super(TestCheckReviewer, self).setUp()
        self.user = UserProfile.objects.get()
        self.persona = Addon.objects.get(pk=15663)
        self.addon = Addon.objects.get(pk=3615)
        self.statictheme = addon_factory(type=amo.ADDON_STATICTHEME)

    def test_no_perm(self):
        request = req_factory_factory('noop', user=self.user)
        assert not check_addons_reviewer(request)
        assert not check_unlisted_addons_reviewer(request)
        assert not check_personas_reviewer(request)
        assert not is_user_any_kind_of_reviewer(request.user)
        assert not is_reviewer(request, self.addon)
        assert not is_reviewer(request, self.persona)
        assert not is_reviewer(request, self.statictheme)

    def test_perm_addons(self):
        self.grant_permission(self.user, 'Addons:Review')
        request = req_factory_factory('noop', user=self.user)
        assert check_addons_reviewer(request)
        assert not check_unlisted_addons_reviewer(request)
        assert not check_personas_reviewer(request)
        assert not check_static_theme_reviewer(request)
        assert is_user_any_kind_of_reviewer(request.user)

    def test_perm_themes(self):
        self.grant_permission(self.user, 'Personas:Review')
        request = req_factory_factory('noop', user=self.user)
        assert not check_addons_reviewer(request)
        assert not check_unlisted_addons_reviewer(request)
        assert check_personas_reviewer(request)
        assert not check_static_theme_reviewer(request)
        assert is_user_any_kind_of_reviewer(request.user)

    def test_perm_unlisted_addons(self):
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        request = req_factory_factory('noop', user=self.user)
        assert not check_addons_reviewer(request)
        assert check_unlisted_addons_reviewer(request)
        assert not check_personas_reviewer(request)
        assert not check_static_theme_reviewer(request)
        assert is_user_any_kind_of_reviewer(request.user)

    def test_perm_static_themes(self):
        self.grant_permission(self.user, 'Addons:ThemeReview')
        request = req_factory_factory('noop', user=self.user)
        assert not check_addons_reviewer(request)
        assert not check_unlisted_addons_reviewer(request)
        assert not check_personas_reviewer(request)
        assert check_static_theme_reviewer(request)
        assert is_user_any_kind_of_reviewer(request.user)

    def test_is_reviewer_for_addon_reviewer(self):
        """An addon reviewer is also a persona reviewer."""
        self.grant_permission(self.user, 'Addons:Review')
        request = req_factory_factory('noop', user=self.user)
        assert is_reviewer(request, self.persona)
        assert is_reviewer(request, self.addon)
        assert not is_reviewer(request, self.statictheme)
        assert is_user_any_kind_of_reviewer(request.user)

    def test_is_reviewer_for_persona_reviewer(self):
        self.grant_permission(self.user, 'Personas:Review')
        request = req_factory_factory('noop', user=self.user)
        assert is_reviewer(request, self.persona)
        assert not is_reviewer(request, self.addon)
        assert not is_reviewer(request, self.statictheme)
        assert is_user_any_kind_of_reviewer(request.user)

    def test_is_reviewer_for_static_theme_reviewer(self):
        self.grant_permission(self.user, 'Addons:ThemeReview')
        request = req_factory_factory('noop', user=self.user)
        assert not is_reviewer(request, self.persona)
        assert not is_reviewer(request, self.addon)
        assert is_reviewer(request, self.statictheme)
        assert is_user_any_kind_of_reviewer(request.user)

    def test_perm_post_review(self):
        self.grant_permission(self.user, 'Addons:PostReview')
        request = req_factory_factory('noop', user=self.user)
        assert is_user_any_kind_of_reviewer(request.user)

        assert not check_unlisted_addons_reviewer(request)
        assert not check_personas_reviewer(request)
        assert not is_reviewer(request, self.persona)
        assert not is_reviewer(request, self.statictheme)

        # Technically, someone with PostReview has access to reviewer tools,
        # and would be called a reviewer... but those 2 functions predates the
        # introduction of PostReview, so at the moment they don't let you in
        # if you only have that permission.
        assert not check_addons_reviewer(request)
        assert not is_reviewer(request, self.addon)

    def test_perm_content_review(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        request = req_factory_factory('noop', user=self.user)
        assert is_user_any_kind_of_reviewer(request.user)

        assert not check_unlisted_addons_reviewer(request)
        assert not check_personas_reviewer(request)
        assert not is_reviewer(request, self.persona)
        assert not is_reviewer(request, self.statictheme)

        # Technically, someone with ContentReview has access to (some of the)
        # reviewer tools, and could be called a reviewer (though they are more
        # limited than other kind of reviewers...) but those 2 functions
        # predates the introduction of PostReview, so at the moment they don't
        # let you in if you only have that permission.
        assert not check_addons_reviewer(request)
        assert not is_reviewer(request, self.addon)
