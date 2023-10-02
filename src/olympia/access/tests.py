from django.contrib.auth.models import AnonymousUser

import pytest

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.users.models import UserProfile

from .acl import (
    action_allowed_for,
    check_addon_ownership,
    is_listed_addons_reviewer,
    is_reviewer,
    is_static_theme_reviewer,
    is_unlisted_addons_reviewer,
    is_unlisted_addons_viewer_or_reviewer,
    is_user_any_kind_of_reviewer,
    match_rules,
    reserved_guid_addon_submission_allowed,
)


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
        'Admin:lists,Admin:applications,Admin:addons',
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
        assert match_rules(rule, 'Admin', '%'), '%s != Admin:%%' % rule

    rules = (
        'Doctors:*',
        'Stats:View',
        'CollectionStats:View',
        'Addons:Review',
        'Users:Edit',
        'None:None',
    )

    for rule in rules:
        assert not match_rules(rule, 'Admin', '%'), (
            "%s == Admin:%% and shouldn't" % rule
        )


def test_anonymous_user():
    # This should not cause an exception (and obviously not return True either)
    assert not action_allowed_for(None, amo.permissions.ANY_ADMIN)


class ACLTestCase(TestCase):
    """Test some basic ACLs by going to various locked pages on AMO."""

    fixtures = ['access/login.json']

    def test_admin_login_anon(self):
        # Login form for anonymous user on the admin page.
        url = '/en-US/admin/models/'
        self.assert3xx(
            self.client.get(url), '/en-US/admin/models/login/?next=/en-US/admin/models/'
        )


class TestCheckAddonOwnership(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.addon = Addon.objects.get(id=3615)
        self.au = AddonUser.objects.get(addon=self.addon, user=self.user)
        assert self.au.role == amo.AUTHOR_ROLE_OWNER

        # Extra kwargs to self.check_addon_ownership in all tests. Override in child
        # test classes to run all the tests with a different set of base
        # kwargs.
        self.extra_kwargs = {}

    def check_addon_ownership(self, *args, **kwargs):
        _kwargs = self.extra_kwargs.copy()
        _kwargs.update(kwargs)
        return check_addon_ownership(*args, **_kwargs)

    def test_anonymous(self):
        self.user = AnonymousUser()
        assert not self.check_addon_ownership(self.user, self.addon)

    def test_allow_addons_edit_permission(self):
        self.user = UserProfile.objects.get(email='admin@mozilla.com')
        assert self.check_addon_ownership(self.user, self.addon)
        assert self.check_addon_ownership(
            self.user, self.addon, allow_addons_edit_permission=True
        )
        assert not self.check_addon_ownership(
            self.user, self.addon, allow_addons_edit_permission=False
        )

    def test_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert not self.check_addon_ownership(self.user, self.addon)
        self.test_allow_addons_edit_permission()

    def test_deleted(self):
        self.addon.update(status=amo.STATUS_DELETED)
        assert not self.check_addon_ownership(self.user, self.addon)
        self.user = UserProfile.objects.get(email='admin@mozilla.com')
        assert not self.check_addon_ownership(self.user, self.addon)

    def test_allow_mozilla_disabled_addon(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.check_addon_ownership(
            self.user, self.addon, allow_mozilla_disabled_addon=True
        )

    def test_owner(self):
        assert self.check_addon_ownership(self.user, self.addon)

        self.au.role = amo.AUTHOR_ROLE_DEV
        self.au.save()
        assert not self.check_addon_ownership(self.user, self.addon)

    def test_allow_developer(self):
        assert self.check_addon_ownership(self.user, self.addon, allow_developer=True)

        self.au.role = amo.AUTHOR_ROLE_DEV
        self.au.save()
        assert self.check_addon_ownership(self.user, self.addon, allow_developer=True)

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

    def test_owner_of_a_different_addon(self):
        user_dev = user_factory()
        addon_factory(users=[user_dev])
        # At this point, `user_dev` is an owner of `addon_for_user_dev`.

        # Let's add `user_dev` as a developer of `self.addon`.
        self.addon.addonuser_set.create(user=user_dev, role=amo.AUTHOR_ROLE_DEV)
        # Now, let's make sure `user_dev` is not an owner.
        self.user = user_dev

        assert not self.check_addon_ownership(self.user, self.addon)
        # `user_dev` is a developer of `self.addon`.
        assert self.check_addon_ownership(self.user, self.addon, allow_developer=True)


class TestCheckReviewer(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get()
        self.addon = Addon.objects.get(pk=3615)
        self.statictheme = addon_factory(type=amo.ADDON_STATICTHEME)

    def test_no_perm(self):
        assert not is_listed_addons_reviewer(self.user)
        assert not is_unlisted_addons_reviewer(self.user)
        assert not is_unlisted_addons_viewer_or_reviewer(self.user)
        assert not is_static_theme_reviewer(self.user)
        assert not is_user_any_kind_of_reviewer(self.user)
        assert not is_reviewer(self.user, self.addon)
        assert not is_reviewer(self.user, self.addon, allow_content_reviewers=False)
        assert not is_reviewer(self.user, self.statictheme)

    def test_perm_addons(self):
        self.grant_permission(self.user, 'Addons:Review')
        assert is_listed_addons_reviewer(self.user)
        assert not is_unlisted_addons_reviewer(self.user)
        assert not is_unlisted_addons_viewer_or_reviewer(self.user)
        assert not is_static_theme_reviewer(self.user)
        assert is_user_any_kind_of_reviewer(self.user)

    def test_perm_unlisted_addons(self):
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        assert not is_listed_addons_reviewer(self.user)
        assert is_unlisted_addons_reviewer(self.user)
        assert is_unlisted_addons_viewer_or_reviewer(self.user)
        assert not is_static_theme_reviewer(self.user)
        assert is_user_any_kind_of_reviewer(self.user)

    def test_perm_static_themes(self):
        self.grant_permission(self.user, 'Addons:ThemeReview')
        assert not is_listed_addons_reviewer(self.user)
        assert not is_unlisted_addons_reviewer(self.user)
        assert not is_unlisted_addons_viewer_or_reviewer(self.user)
        assert is_static_theme_reviewer(self.user)
        assert is_user_any_kind_of_reviewer(self.user)

    def test_is_reviewer_for_addon_reviewer(self):
        """An addon reviewer is not necessarily a theme reviewer."""
        self.grant_permission(self.user, 'Addons:Review')
        assert is_reviewer(self.user, self.addon)
        assert not is_reviewer(self.user, self.statictheme)
        assert is_user_any_kind_of_reviewer(self.user)
        assert is_reviewer(self.user, self.addon, allow_content_reviewers=False)

    def test_is_reviewer_for_static_theme_reviewer(self):
        self.grant_permission(self.user, 'Addons:ThemeReview')
        assert not is_reviewer(self.user, self.addon)
        assert not is_reviewer(self.user, self.addon, allow_content_reviewers=False)
        assert is_reviewer(self.user, self.statictheme)
        assert is_reviewer(self.user, self.statictheme, allow_content_reviewers=False)
        assert is_static_theme_reviewer(self.user)
        assert is_user_any_kind_of_reviewer(self.user)

    def test_perm_content_review(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        assert is_user_any_kind_of_reviewer(self.user)

        assert not is_unlisted_addons_reviewer(self.user)
        assert not is_unlisted_addons_viewer_or_reviewer(self.user)
        assert not is_static_theme_reviewer(self.user)
        assert not is_reviewer(self.user, self.statictheme)
        assert not is_reviewer(
            self.user, self.statictheme, allow_content_reviewers=False
        )

        assert is_listed_addons_reviewer(self.user)
        assert is_reviewer(self.user, self.addon)
        assert not is_reviewer(self.user, self.addon, allow_content_reviewers=False)

    def test_perm_reviewertools_view(self):
        self.grant_permission(self.user, 'ReviewerTools:View')
        assert is_user_any_kind_of_reviewer(self.user, allow_viewers=True)
        assert not is_user_any_kind_of_reviewer(self.user)
        assert not is_unlisted_addons_reviewer(self.user)
        assert not is_static_theme_reviewer(self.user)
        assert not is_reviewer(self.user, self.statictheme)
        assert not is_listed_addons_reviewer(self.user)
        assert not is_reviewer(self.user, self.addon)
        assert not is_reviewer(self.user, self.addon, allow_content_reviewers=False)

    def test_perm_reviewertools_unlisted_view(self):
        self.make_addon_unlisted(self.addon)
        self.make_addon_unlisted(self.statictheme)
        self.grant_permission(self.user, 'ReviewerTools:ViewUnlisted')
        assert is_user_any_kind_of_reviewer(self.user, allow_viewers=True)
        assert not is_user_any_kind_of_reviewer(self.user)
        assert is_unlisted_addons_viewer_or_reviewer(self.user)
        assert not is_unlisted_addons_reviewer(self.user)
        assert is_unlisted_addons_viewer_or_reviewer(self.user)
        assert not is_static_theme_reviewer(self.user)
        assert not is_reviewer(self.user, self.statictheme)
        assert not is_listed_addons_reviewer(self.user)
        assert not is_reviewer(self.user, self.addon)
        assert not is_reviewer(self.user, self.addon, allow_content_reviewers=False)


system_guids = pytest.mark.parametrize(
    'guid',
    [
        'foø@mozilla.org',
        'baa@shield.mozilla.org',
        'moo@pioneer.mozilla.org',
        'blâh@mozilla.com',
        'foø@Mozilla.Org',
        'addon@shield.moZilla.com',
        'baa@ShielD.MozillA.OrG',
        'moo@PIONEER.mozilla.org',
        'blâh@MOZILLA.COM',
        'flop@search.mozilla.org',
        'user@mozillaonline.com',
        'tester@MoZiLlAoNlInE.CoM',
    ],
)


@system_guids
@pytest.mark.django_db
def test_reserved_guid_addon_submission_allowed_mozilla_allowed(guid):
    user = user_factory()
    group = Group.objects.create(name='Blah', rules='SystemAddon:Submit')
    GroupUser.objects.create(group=group, user=user)
    data = {'guid': guid}
    assert reserved_guid_addon_submission_allowed(user, data)


@system_guids
@pytest.mark.django_db
def test_reserved_guid_addon_submission_allowed_not_mozilla_not_allowed(guid):
    user = user_factory()
    data = {'guid': guid}
    assert not reserved_guid_addon_submission_allowed(user, data)
