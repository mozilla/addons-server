from django.utils.encoding import force_text

from olympia import amo
from olympia.addons.models import Addon, AddonReviewerFlags
from olympia.amo.tests import (
    TestCase, addon_factory, file_factory, version_factory)
from olympia.reviewers.forms import ReviewForm
from olympia.reviewers.models import AutoApprovalSummary, CannedResponse
from olympia.reviewers.utils import ReviewHelper
from olympia.users.models import UserProfile
from olympia.versions.models import Version


class TestReviewForm(TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super(TestReviewForm, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.versions.all()[0]

        class FakeRequest:
            user = UserProfile.objects.get(pk=10482)

        self.request = FakeRequest()
        self.file = self.version.files.all()[0]

    def get_form(self, data=None):
        return ReviewForm(
            data=data,
            helper=ReviewHelper(request=self.request, addon=self.addon,
                                version=self.version))

    def set_statuses_and_get_actions(self, addon_status, file_status):
        self.file.update(status=file_status)
        self.addon.update(status=addon_status)
        # Need to clear self.version.all_files cache since we updated the file.
        if self.version.all_files:
            del self.version.all_files
        form = self.get_form()
        return form.helper.get_actions(self.request)

    def test_actions_reject(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NOMINATED,
            file_status=amo.STATUS_AWAITING_REVIEW)
        action = actions['reject']['details']
        assert force_text(action).startswith('This will reject this version')

    def test_actions_reject_unlisted_unreviewed(self):
        self.grant_permission(self.request.user, 'Addons:ReviewUnlisted')
        self.addon = addon_factory()
        self.version = version_factory(addon=self.addon,
                                       channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.file = self.version.files.all()[0]
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NULL,
            file_status=amo.STATUS_AWAITING_REVIEW)
        action = actions['reject']['details']
        assert force_text(action).startswith('This will reject this version')

    def test_actions_addon_status_null(self):
        # If the add-on is null we only show reply, comment and super review.
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NULL, file_status=amo.STATUS_NULL)
        assert list(actions.keys()) == ['reply', 'super', 'comment']

    def test_actions_addon_status_deleted(self):
        # If the add-on is deleted we only show reply, comment and
        # super review.
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_DELETED, file_status=amo.STATUS_NULL)
        assert list(actions.keys()) == ['reply', 'super', 'comment']

    def test_actions_no_pending_files(self):
        # If the add-on has no pending files we only show
        # reject_multiple_versions, reply, comment and super review.
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED)
        assert list(actions.keys()) == [
            'reject_multiple_versions', 'reply', 'super', 'comment'
        ]

        # The add-on is already disabled so we don't show
        # reject_multiple_versions, but reply/super/comment are still present.
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_DISABLED,
            file_status=amo.STATUS_DISABLED)
        assert list(actions.keys()) == ['reply', 'super', 'comment']

    def test_actions_admin_flagged_addon_actions(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True)
        # Test with an admin reviewer.
        self.grant_permission(self.request.user, 'Reviews:Admin')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NOMINATED,
            file_status=amo.STATUS_AWAITING_REVIEW)
        assert 'public' in actions.keys()
        # Test with an non-admin reviewer.
        self.request.user.groupuser_set.all().delete()
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NOMINATED,
            file_status=amo.STATUS_AWAITING_REVIEW)
        assert 'public' not in actions.keys()

    def test_canned_responses(self):
        self.cr_addon = CannedResponse.objects.create(
            name=u'addon reason', response=u'addon reason body',
            sort_group=u'public', type=amo.CANNED_RESPONSE_TYPE_ADDON)
        self.cr_theme = CannedResponse.objects.create(
            name=u'theme reason', response=u'theme reason body',
            sort_group=u'public', type=amo.CANNED_RESPONSE_TYPE_THEME)
        self.grant_permission(self.request.user, 'Addons:Review')
        self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NOMINATED,
            file_status=amo.STATUS_AWAITING_REVIEW)
        form = self.get_form()
        choices = form.fields['canned_response'].choices[1][1]
        # choices is grouped by the sort_group, where choices[0] is the
        # default "Choose a response..." option.
        # Within that, it's paired by [group, [[response, name],...]].
        # So above, choices[1][1] gets the first real group's list of
        # responses.
        assert len(choices) == 1  # No theme response
        assert self.cr_addon.response in choices[0]

        # Check we get different canned responses for static themes.
        self.grant_permission(self.request.user, 'Addons:ThemeReview')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        form = self.get_form()
        choices = form.fields['canned_response'].choices[1][1]
        assert self.cr_theme.response in choices[0]
        assert len(choices) == 1  # No addon response

    def test_comments_and_action_required_by_default(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        form = self.get_form()
        assert not form.is_bound
        form = self.get_form(data={})
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {
            'action': [u'This field is required.'],
            'comments': [u'This field is required.']
        }

        # Alter the action to make it not require comments to be sent
        # regardless of what the action actually is, what we want to test is
        # the form behaviour.
        form = self.get_form(data={'action': 'reply'})
        form.helper.actions['reply']['comments'] = False
        assert form.is_bound
        assert form.is_valid()
        assert not form.errors

    def test_versions_queryset(self):
        # Add a bunch of extra data that shouldn't be picked up.
        addon_factory()
        file_factory(version=self.addon.current_version)
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        # auto-approve everything (including self.addon.current_version)
        for version in Version.unfiltered.all():
            AutoApprovalSummary.objects.create(
                version=version, verdict=amo.AUTO_APPROVED)

        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == []

        # With post-review permission, the reject_multiple_versions action will
        # be available, resetting the queryset of allowed choices.
        self.grant_permission(self.request.user, 'Addons:PostReview')
        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == [
            self.addon.current_version]

    def test_versions_queryset_contains_pending_files_for_listed(self):
        addon_factory()  # Extra add-on, shouldn't be included.
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
                        file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        # auto-approve everything (including self.addon.current_version)
        for version in Version.unfiltered.all():
            AutoApprovalSummary.objects.create(
                version=version, verdict=amo.AUTO_APPROVED)
        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == []

        # With post-review permission, the reject_multiple_versions action will
        # be available, resetting the queryset of allowed choices.
        self.grant_permission(self.request.user, 'Addons:PostReview')
        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == list(
            self.addon.versions.all().order_by('pk'))
        assert form.fields['versions'].queryset.count() == 2

    def test_versions_queryset_doesnt_contain_pending_files_for_unlisted(self):
        addon_factory()  # Extra add-on, shouldn't be included.
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED,
                        file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        # auto-approve everything (including self.addon.current_version)
        for version in Version.unfiltered.all():
            AutoApprovalSummary.objects.create(
                version=version, verdict=amo.AUTO_APPROVED)
        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == []

        # With Addons:ReviewUnlisted permission, the reject_multiple_versions
        # action will be available, resetting the queryset of allowed choices.
        self.grant_permission(self.request.user, 'Addons:ReviewUnlisted')
        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        # The extra version isn't included, because it's not approved and we're
        # looking at unlisted.
        assert list(form.fields['versions'].queryset) == [self.version]

    def test_versions_required(self):
        # auto-approve everything (including self.addon.current_version)
        for version in Version.unfiltered.all():
            AutoApprovalSummary.objects.create(
                version=version, verdict=amo.AUTO_APPROVED)
        self.grant_permission(self.request.user, 'Addons:PostReview')
        form = self.get_form(data={
            'action': 'reject_multiple_versions', 'comments': 'lol'})
        form.helper.actions['reject_multiple_versions']['versions'] = True
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {
            'versions': [u'This field is required.']
        }
