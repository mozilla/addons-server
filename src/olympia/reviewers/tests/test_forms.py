from datetime import datetime

from django.utils.encoding import force_str

import pytest
from pyquery import PyQuery as pq

from olympia import amo
from olympia.addons.models import Addon, AddonReviewerFlags
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.constants.reviewers import REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
from olympia.reviewers.forms import ReviewForm, VersionsChoiceWidget
from olympia.reviewers.models import (
    AutoApprovalSummary,
    CannedResponse,
    ReviewActionReason,
)
from olympia.reviewers.utils import ReviewHelper
from olympia.users.models import UserProfile
from olympia.versions.models import Version, VersionReviewerFlags


class TestReviewForm(TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.versions.all()[0]

        class FakeRequest:
            user = UserProfile.objects.get(pk=10482)

        self.request = FakeRequest()
        self.file = self.version.file

    def get_form(self, data=None):
        return ReviewForm(
            data=data,
            helper=ReviewHelper(
                addon=self.addon, version=self.version, user=self.request.user
            ),
        )

    def set_statuses_and_get_actions(self, addon_status, file_status):
        self.file.update(status=file_status)
        self.addon.update(status=addon_status)
        form = self.get_form()
        return form.helper.get_actions()

    def test_actions_reject(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NOMINATED, file_status=amo.STATUS_AWAITING_REVIEW
        )
        action = actions['reject']['details']
        assert force_str(action).startswith('This will reject this version')

    def test_actions_addon_status_null(self):
        # If the add-on is null we only show reply, comment and super review.
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NULL, file_status=amo.STATUS_NULL
        )
        assert list(actions.keys()) == ['reply', 'super', 'comment']

    def test_actions_addon_status_deleted(self):
        # If the add-on is deleted we only show reply, comment and
        # super review.
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_DELETED, file_status=amo.STATUS_NULL
        )
        assert list(actions.keys()) == ['reply', 'super', 'comment']

    def test_actions_no_pending_files(self):
        # If the add-on has no pending files we only show
        # reject_multiple_versions, reply, comment and super review.
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
        )
        assert list(actions.keys()) == [
            'reject_multiple_versions',
            'reply',
            'super',
            'comment',
        ]

        # The add-on is already disabled so we don't show
        # reject_multiple_versions, but reply/super/comment are still present.
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_DISABLED, file_status=amo.STATUS_DISABLED
        )
        assert list(actions.keys()) == ['reply', 'super', 'comment']

    def test_actions_admin_flagged_addon_actions(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True
        )
        # Test with an admin reviewer.
        self.grant_permission(self.request.user, 'Reviews:Admin')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NOMINATED, file_status=amo.STATUS_AWAITING_REVIEW
        )
        assert 'public' in actions.keys()
        # Test with an non-admin reviewer.
        self.request.user.groupuser_set.all().delete()
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NOMINATED, file_status=amo.STATUS_AWAITING_REVIEW
        )
        assert 'public' not in actions.keys()

    def test_canned_responses(self):
        self.cr_addon = CannedResponse.objects.create(
            name='addon reason',
            response='addon reason body',
            sort_group='public',
            type=amo.CANNED_RESPONSE_TYPE_ADDON,
        )
        self.cr_theme = CannedResponse.objects.create(
            name='theme reason',
            response='theme reason body',
            sort_group='public',
            type=amo.CANNED_RESPONSE_TYPE_THEME,
        )
        self.grant_permission(self.request.user, 'Addons:Review')
        self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NOMINATED, file_status=amo.STATUS_AWAITING_REVIEW
        )
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

    def test_reasons(self):
        self.reason_a = ReviewActionReason.objects.create(
            name='a reason',
            is_active=True,
        )
        self.inactive_reason = ReviewActionReason.objects.create(
            name='b inactive reason',
            is_active=False,
        )
        self.reason_c = ReviewActionReason.objects.create(
            name='c reason',
            is_active=True,
        )
        form = self.get_form()
        choices = form.fields['reasons'].choices
        assert len(choices) == 2  # Only active reasons
        # Reasons are displayed in alphabetical order.
        assert list(choices.queryset)[0] == self.reason_a
        assert list(choices.queryset)[1] == self.reason_c

    def test_reasons_required(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        form = self.get_form()
        assert not form.is_bound
        form = self.get_form(
            data={
                'action': 'reply',
                'comments': 'lol',
            }
        )
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {
            'reasons': ['This field is required.'],
        }

        # Alter the action to make it not require reasons to be sent
        # regardless of what the action actually is, what we want to test is
        # the form behaviour.
        form = self.get_form(
            data={
                'action': 'reply',
                'comments': 'lol',
            }
        )
        form.helper.actions['reply']['requires_reasons'] = False
        assert form.is_bound
        assert form.is_valid()
        assert not form.errors

    def test_reasons_optional_for_public(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        form = self.get_form()
        assert not form.is_bound
        form = self.get_form(
            data={
                'action': 'public',
                'comments': 'lol',
            }
        )
        assert form.is_bound
        assert form.is_valid()
        assert not form.errors

    def test_comments_and_action_required_by_default(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        form = self.get_form()
        assert not form.is_bound
        form = self.get_form(
            data={
                'reasons': [
                    ReviewActionReason.objects.create(
                        name='reason 1',
                        is_active=True,
                    )
                ],
            }
        )
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {
            'action': ['This field is required.'],
            'comments': ['This field is required.'],
        }

        # Alter the action to make it not require comments to be sent
        # regardless of what the action actually is, what we want to test is
        # the form behaviour.
        form = self.get_form(
            data={
                'action': 'reply',
                'reasons': [
                    ReviewActionReason.objects.create(
                        name='reason 1',
                        is_active=True,
                    )
                ],
            }
        )
        form.helper.actions['reply']['comments'] = False
        assert form.is_bound
        assert form.is_valid()
        assert not form.errors

    def test_versions_queryset(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        # Add a bunch of extra data that shouldn't be picked up.
        addon_factory()
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        # auto-approve everything (including self.addon.current_version)
        for version in Version.unfiltered.all():
            AutoApprovalSummary.objects.create(
                version=version, verdict=amo.AUTO_APPROVED
            )

        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == [self.addon.current_version]

    def test_versions_queryset_contains_pending_files_for_listed(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        addon_factory()  # Extra add-on, shouldn't be included.
        version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # auto-approve everything (including self.addon.current_version)
        for version in Version.unfiltered.all():
            AutoApprovalSummary.objects.create(
                version=version, verdict=amo.AUTO_APPROVED
            )
        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == list(
            self.addon.versions.all().order_by('pk')
        )
        assert form.fields['versions'].queryset.count() == 2

        content = str(form['versions'])
        doc = pq(content)
        # <select> should have 'data-toggle' class and data-value attribute to
        # show/hide it depending on action in JavaScript.
        select = doc('select')[0]
        select.attrib.get('class') == 'data-toggle'
        assert select.attrib.get('data-value') == 'reject_multiple_versions|'

        # <option>s shouldn't, because for listed review they will all be
        # shown. They should still have a value attribute however.
        options = doc('option')
        assert len(options) == 2
        for option in options:
            assert option.attrib.get('class') is None
            assert option.attrib.get('data-value') is None
            assert option.attrib.get('value')

    def test_versions_queryset_contains_pending_files_for_unlisted(self):
        # We also return pending versions for unlisted, but hide some of the
        # versions using JavaScript + some data attributes on each <option>.
        # The queryset should contain both pending and approved versions.
        addon_factory()  # Extra add-on, shouldn't be included.
        pending_version = version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        # auto-approve everything
        for version in Version.unfiltered.all():
            AutoApprovalSummary.objects.create(
                version=version, verdict=amo.AUTO_APPROVED
            )
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
        assert list(form.fields['versions'].queryset) == list(
            self.addon.versions.all().order_by('pk')
        )
        assert form.fields['versions'].queryset.count() == 2

        content = str(form['versions'])
        doc = pq(content)
        # <select> should have 'data-toggle' class and data-value attribute to
        # show/hide it depending on action in JavaScript.
        select = doc('select')[0]
        select.attrib.get('class') == 'data-toggle'
        assert select.attrib.get('data-value') == (
            'reject_multiple_versions|block_multiple_versions|'
            'confirm_multiple_versions|'
        )

        # <option>s should as well, and the value depends on which version:
        # the approved one and the pending one should have different values.
        assert len(doc('option')) == 2
        option1 = doc('option[value="%s"]' % self.version.pk)[0]
        assert option1.attrib.get('class') == 'data-toggle'
        assert option1.attrib.get('data-value') == (
            # That version is approved.
            'confirm_multiple_versions|block_multiple_versions|'
        )
        assert option1.attrib.get('value') == str(self.version.pk)

        option2 = doc('option[value="%s"]' % pending_version.pk)[0]
        assert option2.attrib.get('class') == 'data-toggle'
        assert option2.attrib.get('data-value') == (
            # That version is pending.
            'reject_multiple_versions|'
        )
        assert option2.attrib.get('value') == str(pending_version.pk)

    def test_versions_required(self):
        # auto-approve everything (including self.addon.current_version)
        for version in Version.unfiltered.all():
            AutoApprovalSummary.objects.create(
                version=version, verdict=amo.AUTO_APPROVED
            )
        self.grant_permission(self.request.user, 'Addons:Review')
        form = self.get_form(
            data={
                'action': 'reject_multiple_versions',
                'comments': 'lol',
                'reasons': [
                    ReviewActionReason.objects.create(
                        name='reason 1',
                        is_active=True,
                    )
                ],
            }
        )
        form.helper.actions['reject_multiple_versions']['versions'] = True
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {'versions': ['This field is required.']}

    def test_delayed_rejection_days_widget_attributes(self):
        # Regular reviewers can't customize the delayed rejection period.
        form = self.get_form()
        widget = form.fields['delayed_rejection_days'].widget
        assert widget.attrs == {
            'min': REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT,
            'max': REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT,
            'readonly': 'readonly',
        }
        # Admin reviewers can customize the delayed rejection period.
        self.grant_permission(self.request.user, 'Reviews:Admin')
        form = self.get_form()
        widget = form.fields['delayed_rejection_days'].widget
        assert widget.attrs == {
            'min': 1,
            'max': 99,
        }

    def test_delayed_rejection_showing_for_unlisted_awaiting(self):
        self.addon.update(status=amo.STATUS_NULL)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.test_delayed_rejection_days_widget_attributes()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'file_status, pending_rejection, auto_summary, verdict, confirmed, output',
    (
        (
            amo.STATUS_AWAITING_REVIEW,
            datetime(2022, 7, 7, 7, 7, 7),
            True,
            amo.AUTO_APPROVED,
            False,
            'Delay-rejected, scheduled for 2022-07-07',
        ),
        (
            amo.STATUS_APPROVED,
            datetime(2022, 8, 8, 8, 8, 8),
            True,
            amo.AUTO_APPROVED,
            False,
            'Delay-rejected, scheduled for 2022-08-08',
        ),
        (
            amo.STATUS_APPROVED,
            None,
            True,
            amo.AUTO_APPROVED,
            False,
            'Auto-approved, not Confirmed',
        ),
        (
            amo.STATUS_APPROVED,
            None,
            True,
            amo.AUTO_APPROVED,
            True,
            'Auto-approved, Confirmed',
        ),
        (
            amo.STATUS_APPROVED,
            None,
            True,
            amo.NOT_AUTO_APPROVED,
            False,
            'Approved, Manual',
        ),
        (
            amo.STATUS_APPROVED,
            None,
            False,
            amo.NOT_AUTO_APPROVED,
            False,
            'Approved, Manual',
        ),
        (
            amo.STATUS_AWAITING_REVIEW,
            None,
            False,
            amo.NOT_AUTO_APPROVED,
            False,
            'Awaiting Review',
        ),
    ),
)
def test_version_choice_widget_extended_status(
    file_status, pending_rejection, auto_summary, verdict, confirmed, output
):
    version = addon_factory(file_kw={'status': file_status}).find_latest_version(None)
    if pending_rejection:
        VersionReviewerFlags.objects.create(
            version=version, pending_rejection=pending_rejection
        )
    if auto_summary:
        AutoApprovalSummary.objects.create(
            version=version, verdict=verdict, confirmed=confirmed
        )
    assert output == VersionsChoiceWidget().get_extended_status(version)
