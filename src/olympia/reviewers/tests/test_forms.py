import uuid
from datetime import datetime, timedelta

from django.core.files.base import ContentFile
from django.utils.encoding import force_str

import time_machine
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.abuse.models import (
    AbuseReport,
    CinderAppeal,
    CinderJob,
    CinderPolicy,
    CinderQueueMove,
    ContentDecision,
)
from olympia.addons.models import Addon
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)
from olympia.bandwagon.models import Collection
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.files.models import File
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile
from olympia.versions.models import Version, VersionReviewerFlags

from ..forms import HeldDecisionReviewForm, ReviewForm, ReviewQueueFilter
from ..models import (
    AutoApprovalSummary,
    NeedsHumanReview,
    ReviewActionReason,
)
from ..utils import ReviewHelper


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

    def get_form(self, data=None, files=None):
        return ReviewForm(
            data=data,
            files=files,
            helper=ReviewHelper(
                addon=self.addon,
                version=self.version,
                user=self.request.user,
                channel=self.version.channel,
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
        # If the add-on is null we only show set needs human review, reply,
        # comment.
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NULL, file_status=amo.STATUS_DISABLED
        )
        self.version.update(human_review_date=datetime.now())
        assert list(actions.keys()) == [
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]

        # If an admin reviewer we also show unreject_latest_version and clear
        # pending rejection/needs human review (though the versions form would
        # be empty for the last 2 here). And disable addon.
        self.grant_permission(self.request.user, 'Reviews:Admin')
        actions = self.get_form().helper.get_actions()
        assert list(actions.keys()) == [
            'unreject_latest_version',
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
            'comment',
        ]

    def test_actions_addon_status_null_unlisted(self):
        self.make_addon_unlisted(self.addon)
        self.version.reload()
        self.version.update(human_review_date=datetime.now())
        self.grant_permission(self.request.user, 'Addons:Review')
        self.grant_permission(self.request.user, 'Addons:ReviewUnlisted')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_NULL, file_status=amo.STATUS_DISABLED
        )
        assert list(actions.keys()) == [
            'approve_multiple_versions',
            'reject_multiple_versions',
            'block_multiple_versions',
            'confirm_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]

        # If an admin reviewer we also show unreject_multiple_versions,
        # clear pending rejections/clear needs human review, disable addon.
        self.grant_permission(self.request.user, 'Reviews:Admin')
        actions = self.get_form().helper.get_actions()
        assert list(actions.keys()) == [
            'approve_multiple_versions',
            'reject_multiple_versions',
            'unreject_multiple_versions',
            'block_multiple_versions',
            'confirm_multiple_versions',
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
            'comment',
        ]

    def test_actions_addon_status_deleted(self):
        # If the add-on is deleted we only show reply, comment and
        # super review.
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_DELETED, file_status=amo.STATUS_DISABLED
        )
        assert list(actions.keys()) == [
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]

        # Having admin permission gives you some extra actions
        self.grant_permission(self.request.user, 'Reviews:Admin')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_DELETED, file_status=amo.STATUS_DISABLED
        )
        assert list(actions.keys()) == [
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'request_legal_review',
            'comment',
        ]

    def test_actions_no_pending_files(self):
        # If the add-on has no pending files we only show
        # reject_multiple_versions, reply, comment and super review.
        self.grant_permission(self.request.user, 'Addons:Review')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
        )
        assert list(actions.keys()) == [
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]

        # admins have extra permssions though
        self.grant_permission(self.request.user, 'Reviews:Admin')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
        )
        assert list(actions.keys()) == [
            'reject_multiple_versions',
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
            'comment',
        ]

        # The add-on is already disabled so we don't show reject_multiple_versions, but
        # reply/comment/disable_addon and clear actions are still present.
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_DISABLED, file_status=amo.STATUS_DISABLED
        )
        assert list(actions.keys()) == [
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'enable_addon',
            'request_legal_review',
            'comment',
        ]

    def test_reasons(self):
        self.reason_a = ReviewActionReason.objects.create(
            name='a reason',
            is_active=True,
            canned_response='Canned response for A',
        )
        self.inactive_reason = ReviewActionReason.objects.create(
            name='b inactive reason',
            is_active=False,
            canned_response='Canned response for B',
        )
        self.reason_c = ReviewActionReason.objects.create(
            name='c reason',
            is_active=True,
            canned_response='Canned response for C',
        )
        self.reason_d = ReviewActionReason.objects.create(
            name='d reason',
            is_active=True,
            canned_response='Canned response for D',
            cinder_policy=CinderPolicy.objects.create(
                uuid=uuid.uuid4(), name='Lone Policy', text='Lone Policy Description'
            ),
        )
        self.reason_e = ReviewActionReason.objects.create(
            name='e reason',
            is_active=True,
            canned_response='Canned response for E',
            cinder_policy=CinderPolicy.objects.create(
                uuid=uuid.uuid4(),
                name='Nested Policy',
                text='Nested Policy Description',
                parent=CinderPolicy.objects.create(
                    uuid=uuid.uuid4(),
                    name='Parent Policy',
                    text='Parent Policy Description',
                ),
            ),
        )
        self.empty_reason = ReviewActionReason.objects.create(
            name='d reason',
            is_active=True,
            canned_block_reason='block',
        )
        form = self.get_form()
        choices = form.fields['reasons'].choices
        assert len(choices) == 4  # Only active reasons
        # Reasons are displayed in alphabetical order.
        assert list(choices.queryset)[0] == self.reason_a
        assert list(choices.queryset)[1] == self.reason_c
        assert list(choices.queryset)[2] == self.reason_d
        assert list(choices.queryset)[3] == self.reason_e

        # Assert that the canned_response is written to data-value of the
        # checkboxes.
        doc = pq(str(form['reasons']))
        assert doc('input')[0].attrib.get('data-value') == '- Canned response for A\n'
        assert doc('input')[1].attrib.get('data-value') == '- Canned response for C\n'
        assert (
            doc('input')[2].attrib.get('data-value')
            == '- Lone Policy: Canned response for D\n'
        )
        assert (
            doc('input')[3].attrib.get('data-value')
            == '- Parent Policy, specifically Nested Policy: Canned response for E\n'
        )

    def test_reasons_by_type(self):
        self.reason_all = ReviewActionReason.objects.create(
            name='A reason for all add-on types',
            is_active=True,
            addon_type=amo.ADDON_ANY,
            canned_response='all',
        )
        self.reason_extension = ReviewActionReason.objects.create(
            name='An extension only reason',
            is_active=True,
            addon_type=amo.ADDON_EXTENSION,
            canned_response='extension',
        )
        self.reason_theme = ReviewActionReason.objects.create(
            name='A theme only reason',
            is_active=True,
            addon_type=amo.ADDON_STATICTHEME,
            canned_response='theme',
        )
        form = self.get_form()
        choices = form.fields['reasons'].choices
        # By default the addon is an extension.
        assert self.addon.type == amo.ADDON_EXTENSION
        assert len(choices) == 2
        assert list(choices.queryset)[0] == self.reason_all
        assert list(choices.queryset)[1] == self.reason_extension

        # Change the addon to a theme.
        self.addon.update(type=amo.ADDON_STATICTHEME)
        form = self.get_form()
        choices = form.fields['reasons'].choices
        assert len(choices) == 2
        assert list(choices.queryset)[0] == self.reason_all
        assert list(choices.queryset)[1] == self.reason_theme

    def test_reasons_not_required_for_reply_but_versions_is(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        form = self.get_form()
        assert not form.is_bound
        form = self.get_form(
            data={
                'action': 'reply',
                'comments': 'lol',
                'versions': [self.version.pk],
            }
        )
        assert form.helper.actions['reply']['requires_reasons'] is False
        assert form.is_bound
        assert form.is_valid()
        assert not form.errors

        form = self.get_form(
            data={
                'action': 'reply',
                'comments': 'lol',
            }
        )
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {
            'versions': ['This field is required.'],
        }

    def test_reasons_required_for_reject_multiple_versions(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        form = self.get_form()
        assert not form.is_bound
        form = self.get_form(
            data={
                'action': 'reject_multiple_versions',
                'comments': 'lol',
                'versions': self.addon.versions.all(),
                'delayed_rejection': 'False',
            }
        )
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {'reasons': ['This field is required.']}

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

    def test_reasons_required_with_cinder_jobs(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        reason = ReviewActionReason.objects.create(name='A reason', canned_response='a')
        form = self.get_form()
        assert not form.is_bound
        data = {'action': 'reject', 'comments': 'lol', 'cinder_jobs_to_resolve': [job]}
        form = self.get_form(data=data)
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {'reasons': ['This field is required.']}

        data['reasons'] = [reason]
        form = self.get_form(data=data)
        assert form.is_bound
        assert form.is_valid()
        assert not form.errors

    def test_reasons_required_with_cinder_jobs_theme_too(self):
        self.grant_permission(self.request.user, 'Addons:ThemeReview')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.test_reasons_required_with_cinder_jobs()

    def test_policies_required_with_cinder_jobs(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        policy = CinderPolicy.objects.create(
            uuid='x',
            name='ok',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_IGNORE.api_value],
        )
        form = self.get_form()
        assert not form.is_bound
        data = {
            'action': 'resolve_reports_job',
            'cinder_jobs_to_resolve': [job.id],
        }
        form = self.get_form(data=data)
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {'cinder_policies': ['This field is required.']}

        data['cinder_policies'] = [policy.id]
        form = self.get_form(data=data)
        assert form.is_bound
        assert form.is_valid(), form.errors
        assert not form.errors

    @override_switch('cinder_policy_review_reasons_enabled', active=True)
    def test_comments_optional_for_actions_with_enforcement_actions(self):
        policy = CinderPolicy.objects.create(
            uuid='xxx',
            name='ok',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
        )
        self.grant_permission(self.request.user, 'Addons:Review')
        self.grant_permission(self.request.user, 'Reviews:Admin')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        for action_name in ('public', 'reject', 'disable_addon'):
            form = self.get_form(
                data={'action': action_name, 'cinder_policies': [policy.id]}
            )
            assert 'comments' not in form.helper.actions[action_name]
            assert form.is_bound
            assert form.is_valid(), form.errors
            assert not form.errors

    @override_switch('cinder_policy_review_reasons_enabled', active=True)
    def test_policy_values_parsed(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        policy = CinderPolicy.objects.create(
            uuid='xxx',
            name='ok',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
            text='Blah blah {SOME-PLACEHOLDER} blah blah.',
        )
        unselected_policy = CinderPolicy.objects.create(
            uuid='yyy',
            name='not okay',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
            text='policy text {UNSELECTED}',
        )
        form = self.get_form()
        assert not form.is_bound
        data = {
            'action': 'reject',
            'cinder_policies': [policy.id],
        }
        form = self.get_form(data=data)
        assert form.is_bound
        assert form.is_valid(), form.errors
        assert 'policy_values' in form.cleaned_data
        assert form.cleaned_data['policy_values'] == {
            'xxx': {'SOME-PLACEHOLDER': None},
            'yyy': {'UNSELECTED': None},
        }

        data = {
            'action': 'reject',
            'cinder_policies': [policy.id],
            f'policy_values_{policy.id}_SOME-PLACEHOLDER': 'some value?',
            # Include some data that will be ignored
            f'policy_values_{unselected_policy.id}_UNSELECTED': 'not selected',
            f'policy_values_{policy.id}': 'does-not-exist',
        }
        form = self.get_form(data=data)
        assert form.is_bound
        assert form.is_valid(), form.errors
        assert 'policy_values' in form.cleaned_data
        assert form.cleaned_data['policy_values'] == {
            'xxx': {'SOME-PLACEHOLDER': 'some value?'},
            'yyy': {'UNSELECTED': None},
        }

    def test_appeal_action_require_with_resolve_appeal_job(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        ContentDecision.objects.create(
            appeal_job=job, addon=self.addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        form = self.get_form()
        assert not form.is_bound
        data = {
            'action': 'resolve_appeal_job',
            'comments': 'lol',
            'cinder_jobs_to_resolve': [job.id],
        }
        form = self.get_form(data=data)
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {'appeal_action': ['This field is required.']}

        data['appeal_action'] = ['deny']
        form = self.get_form(data=data)
        assert form.is_bound
        assert form.is_valid(), form.errors
        assert not form.errors

    def test_only_one_cinder_action_selected(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        no_action_policy = CinderPolicy.objects.create(
            uuid='no', name='no action', expose_in_reviewer_tools=True
        )
        action_policy_a = CinderPolicy.objects.create(
            uuid='a',
            name='ignore',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_IGNORE.api_value],
        )
        action_policy_b = CinderPolicy.objects.create(
            uuid='b',
            name='ignore again',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_IGNORE.api_value],
        )
        action_policy_c = CinderPolicy.objects.create(
            uuid='c',
            name='approve',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_APPROVE.api_value],
        )
        action_policy_d = CinderPolicy.objects.create(
            uuid='d',
            name='closed already',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_CLOSED_NO_ACTION.api_value],
        )
        form = self.get_form()
        assert not form.is_bound
        data = {
            'action': 'resolve_reports_job',
            'cinder_jobs_to_resolve': [job.id],
            'cinder_policies': [no_action_policy.id],
        }
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            'cinder_policies': [
                'No policies selected with an associated cinder action.'
            ]
        }

        data['cinder_policies'] = [action_policy_a.id, action_policy_c.id]
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            'cinder_policies': [
                'Multiple policies selected with different cinder actions.'
            ]
        }

        data['cinder_policies'] = [action_policy_a.id, action_policy_b.id]
        form = self.get_form(data=data)
        assert form.is_valid()
        assert not form.errors

        data['cinder_policies'] = [action_policy_d.id]
        form = self.get_form(data=data)
        assert form.is_valid(), form.errors
        assert not form.errors

    def test_cinder_jobs_filtered_for_resolve_reports_job_and_resolve_appeal_job(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        appeal_job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job,
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        )
        report_job = CinderJob.objects.create(
            job_id='2', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        AbuseReport.objects.create(cinder_job=report_job, guid=self.addon.guid)
        policy = CinderPolicy.objects.create(
            uuid='a',
            name='ignore',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_IGNORE.api_value],
        )

        data = {
            'action': 'resolve_appeal_job',
            'comments': 'lol',
            'appeal_action': ['deny'],
            'cinder_jobs_to_resolve': [report_job.id],
        }
        form = self.get_form(data=data)
        form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == []

        data['cinder_jobs_to_resolve'] = [report_job, appeal_job]
        form = self.get_form(data=data)
        form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [appeal_job]

        data = {
            'action': 'resolve_reports_job',
            'cinder_policies': [policy.id],
            'cinder_jobs_to_resolve': [appeal_job.id],
        }
        form = self.get_form(data=data)
        form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == []

        data['cinder_jobs_to_resolve'] = [report_job.id, appeal_job.id]
        form = self.get_form(data=data)
        form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [report_job]

    def test_cinder_jobs_filtered_for_reject_or_reject_multiple_versions(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        appeal_job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job,
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        )
        report_job = CinderJob.objects.create(
            job_id='2', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        AbuseReport.objects.create(cinder_job=report_job, guid=self.addon.guid)
        policy = CinderPolicy.objects.create(
            uuid='a',
            name='ignore',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_IGNORE.api_value],
        )

        data = {
            'action': 'reject_multiple_versions',
            'comments': 'lol',
            'cinder_jobs_to_resolve': [appeal_job.id],
            'versions': [self.version.pk],
        }
        form = self.get_form(data=data)
        form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == []

        data['cinder_jobs_to_resolve'] = [report_job, appeal_job]
        form = self.get_form(data=data)
        form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [report_job]

        data = {
            'action': 'reject',
            'cinder_policies': [policy.id],
            'cinder_jobs_to_resolve': [appeal_job.id],
        }
        form = self.get_form(data=data)
        form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == []

        data['cinder_jobs_to_resolve'] = [report_job.id, appeal_job.id]
        form = self.get_form(data=data)
        form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [report_job]

    def test_boilerplate(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        form = self.get_form()
        doc = pq(str(form['action']))
        assert (
            doc('input')[0].attrib.get('data-value')
            == 'Thank you for your contribution.'
        )
        assert doc('input')[1].attrib.get('data-value') is None
        assert doc('input')[2].attrib.get('data-value') is None
        assert doc('input')[3].attrib.get('data-value') is None
        assert doc('input')[4].attrib.get('data-value') is None

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
                        canned_response='reason 1',
                    )
                ],
                'cinder_policies': [
                    CinderPolicy.objects.create(
                        uuid='1',
                        name='policy 1',
                        expose_in_reviewer_tools=True,
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
                        canned_response='reason 1',
                    )
                ],
                'versions': [self.version.pk],
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
        version_factory(addon=self.addon, channel=amo.CHANNEL_UNLISTED)
        # auto-approve everything (including self.addon.current_version)
        for version in Version.unfiltered.all():
            AutoApprovalSummary.objects.create(
                version=version, verdict=amo.AUTO_APPROVED
            )

        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == [self.addon.current_version]

    def test_versions_queryset_contains_pending_files_for_listed(
        self, expected_select_data_value=None
    ):
        if expected_select_data_value is None:
            expected_select_data_value = [
                'reject_multiple_versions',
                'set_needs_human_review_multiple_versions',
                'reply',
            ]
        # We hide some of the versions using JavaScript + some data attributes on each
        # <option>.
        # The queryset should contain both pending, rejected, and approved versions.
        self.grant_permission(self.request.user, 'Addons:Review')
        addon_factory()  # Extra add-on, shouldn't be included.
        pending_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        rejected_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        blocked_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        block_factory(
            addon=blocked_version.addon,
            version_ids=[blocked_version.id],
            updated_by=user_factory(),
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
        assert form.fields['versions'].queryset.count() == 4

        content = str(form['versions'])
        doc = pq(content)

        # <select> should have 'data-toggle' class and data-value attribute to
        # show/hide it depending on action in JavaScript.
        select = doc('select')[0]
        assert select.attrib.get('class') == 'data-toggle'
        assert select.attrib.get('data-value').split(' ') == expected_select_data_value

        # <option>s should as well, and the value depends on which version:
        # the approved one and the pending one should have different values.
        assert len(doc('option')) == 4
        option1 = doc('option[value="%s"]' % self.version.pk)[0]
        assert option1.attrib.get('class') == 'data-toggle'
        assert option1.attrib.get('data-value').split(' ') == [
            # That version is approved.
            'block_multiple_versions',
            'reject_multiple_versions',
            'reply',
            'set_needs_human_review_multiple_versions',
        ]
        assert option1.attrib.get('value') == str(self.version.pk)

        option2 = doc('option[value="%s"]' % pending_version.pk)[0]
        assert option2.attrib.get('class') == 'data-toggle'
        assert option2.attrib.get('data-value').split(' ') == [
            # That version is pending.
            'approve_multiple_versions',
            'reject_multiple_versions',
            'reply',
            'set_needs_human_review_multiple_versions',
        ]
        assert option2.attrib.get('value') == str(pending_version.pk)

        option3 = doc('option[value="%s"]' % rejected_version.pk)[0]
        assert option3.attrib.get('class') == 'data-toggle'
        assert option3.attrib.get('data-value').split(' ') == [
            # That version is rejected, so it has unreject_multiple_versions,
            # but it was never signed so it doesn't get
            # set_needs_human_review_multiple_versions
            'unreject_multiple_versions',
            'reply',
        ]
        assert option3.attrib.get('value') == str(rejected_version.pk)

        option4 = doc('option[value="%s"]' % blocked_version.pk)[0]
        assert option4.attrib.get('class') == 'data-toggle'
        # That version is blocked, so the only action available is reply,
        # unreject_multiple_versions and
        # set_needs_human_review_multiple_versions should be absent.
        assert option4.attrib.get('data-value') == 'reply'
        assert option4.attrib.get('value') == str(blocked_version.pk)

    def test_versions_queryset_contains_pending_files_for_listed_admin_reviewer(self):
        self.grant_permission(self.request.user, 'Reviews:Admin')
        # No change
        self.test_versions_queryset_contains_pending_files_for_listed(
            expected_select_data_value=[
                'reject_multiple_versions',
                'change_or_clear_pending_rejection_multiple_versions',
                'clear_needs_human_review_multiple_versions',
                'set_needs_human_review_multiple_versions',
                'reply',
            ]
        )

    def test_versions_queryset_contains_pending_files_for_unlisted(
        self,
        expected_select_data_value=None,
    ):
        if expected_select_data_value is None:
            expected_select_data_value = [
                'approve_multiple_versions',
                'reject_multiple_versions',
                'block_multiple_versions',
                'confirm_multiple_versions',
                'set_needs_human_review_multiple_versions',
            ]
        # We hide some of the versions using JavaScript + some data attributes on each
        # <option>.
        # The queryset should contain both pending, rejected, and approved versions.
        addon_factory()  # Extra add-on, shouldn't be included.
        pending_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        rejected_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        blocked_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        block_factory(
            addon=blocked_version.addon,
            version_ids=[blocked_version.id],
            updated_by=user_factory(),
        )
        deleted_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        deleted_version.delete()

        self.version.update(channel=amo.CHANNEL_UNLISTED)
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
            Version.unfiltered_for_relations.filter(addon=self.addon).order_by('pk')
        )
        assert form.fields['versions'].queryset.count() == 5

        content = str(form['versions'])
        doc = pq(content)

        # <select> should have 'data-toggle' class and data-value attribute to
        # show/hide it depending on action in JavaScript.
        select = doc('select')[0]
        assert select.attrib.get('class') == 'data-toggle'
        assert select.attrib.get('data-value').split(' ') == expected_select_data_value

        # <option>s should as well, and the value depends on which version:
        # the approved one and the pending one should have different values.
        assert len(doc('option')) == 5
        option1 = doc('option[value="%s"]' % self.version.pk)[0]
        assert option1.attrib.get('class') == 'data-toggle'
        assert option1.attrib.get('data-value').split(' ') == [
            # That version is approved.
            'block_multiple_versions',
            'confirm_multiple_versions',
            'reject_multiple_versions',
            'reply',
            'set_needs_human_review_multiple_versions',
        ]
        assert option1.attrib.get('value') == str(self.version.pk)

        option2 = doc('option[value="%s"]' % pending_version.pk)[0]
        assert option2.attrib.get('class') == 'data-toggle'
        assert option2.attrib.get('data-value').split(' ') == [
            # That version is pending.
            'approve_multiple_versions',
            'reject_multiple_versions',
            'reply',
            'set_needs_human_review_multiple_versions',
        ]
        assert option2.attrib.get('value') == str(pending_version.pk)

        option3 = doc('option[value="%s"]' % rejected_version.pk)[0]
        assert option3.attrib.get('class') == 'data-toggle'
        assert option3.attrib.get('data-value').split(' ') == [
            # That version is rejected, so it has unreject_multiple_versions,
            # but it was never signed so it doesn't get
            # set_needs_human_review_multiple_versions
            'unreject_multiple_versions',
            'reply',
        ]
        assert option3.attrib.get('value') == str(rejected_version.pk)

        option4 = doc('option[value="%s"]' % blocked_version.pk)[0]
        assert option4.attrib.get('class') == 'data-toggle'
        # That version is blocked, so the only action available is reply,
        # unreject_multiple_versions and
        # set_needs_human_review_multiple_versions should be absent.
        assert option4.attrib.get('data-value') == 'reply'
        assert option4.attrib.get('value') == str(blocked_version.pk)

        option5 = doc('option[value="%s"]' % deleted_version.pk)[0]
        assert option5.attrib.get('class') == 'data-toggle'
        assert option5.attrib.get('data-value').split(' ') == [
            'unreject_multiple_versions',
            'reply',
            # The deleted auto-approved version can still have
            # its auto-approval confirmed.
            'confirm_multiple_versions',
        ]
        assert option5.attrib.get('value') == str(deleted_version.pk)

    def test_set_needs_human_review_presence(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        deleted_but_signed = version_factory(
            addon=self.addon,
            file_kw={
                'status': amo.STATUS_APPROVED,
                'is_signed': True,
            },
        )
        deleted_but_signed.delete()
        deleted_but_unsigned = version_factory(
            addon=self.addon,
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_signed': False,
            },
        )
        deleted_but_unsigned.delete()
        user_disabled_version_but_signed = version_factory(
            addon=self.addon,
            file_kw={
                'status': amo.STATUS_DISABLED,
                'original_status': amo.STATUS_APPROVED,
                'status_disabled_reason': File.STATUS_DISABLED_REASONS.DEVELOPER,
                'is_signed': True,
            },
        )
        user_disabled_version_but_unsigned = version_factory(
            addon=self.addon,
            file_kw={
                'status': amo.STATUS_DISABLED,
                'original_status': amo.STATUS_AWAITING_REVIEW,
                'status_disabled_reason': File.STATUS_DISABLED_REASONS.DEVELOPER,
                'is_signed': False,
            },
        )
        pending_version = version_factory(
            addon=self.addon,
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
            },
        )
        approved_signed_version = version_factory(
            addon=self.addon,
            file_kw={
                'is_signed': True,
            },
        )
        form = self.get_form()
        assert not form.is_bound
        assert list(form.fields['versions'].queryset) == list(
            self.addon.versions(manager='unfiltered_for_relations').all().order_by('pk')
        )
        assert form.fields['versions'].queryset.count() == 7

        content = str(form['versions'])
        doc = pq(content)

        assert len(doc('option')) == 7

        for version in [
            self.version,
            deleted_but_signed,
            user_disabled_version_but_signed,
            pending_version,
            approved_signed_version,
        ]:
            option = doc('option[value="%s"]' % version.pk)[0]
            assert 'set_needs_human_review_multiple_versions' in option.attrib.get(
                'data-value'
            ).split(' '), version
        for version in [deleted_but_unsigned, user_disabled_version_but_unsigned]:
            option = doc('option[value="%s"]' % version.pk)[0]
            assert 'set_needs_human_review_multiple_versions' not in option.attrib.get(
                'data-value'
            ).split(' '), version

    def test_versions_queryset_contains_pending_files_for_unlisted_admin_reviewer(self):
        self.grant_permission(self.request.user, 'Reviews:Admin')
        self.test_versions_queryset_contains_pending_files_for_unlisted(
            expected_select_data_value=[
                'approve_multiple_versions',
                'reject_multiple_versions',
                'unreject_multiple_versions',
                'block_multiple_versions',
                'confirm_multiple_versions',
                'change_or_clear_pending_rejection_multiple_versions',
                'clear_needs_human_review_multiple_versions',
                'set_needs_human_review_multiple_versions',
            ]
        )

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
                        canned_response='reason 1',
                    )
                ],
                'delayed_rejection': 'False',
            }
        )
        form.helper.actions['reject_multiple_versions']['versions'] = True
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {'versions': ['This field is required.']}

    @time_machine.travel('2025-02-10 12:09', tick=False)
    def test_delayed_rejection_date_is_readonly_for_regular_reviewers(self):
        # Regular reviewers can't customize the delayed rejection period.
        self.grant_permission(self.request.user, 'Addons:Review')
        form = self.get_form()
        assert 'delayed_rejection_date' in form.fields
        assert 'delayed_rejection' in form.fields
        assert form.fields['delayed_rejection_date'].widget.attrs == {
            'min': '2025-02-11T12:09',
            'readonly': 'readonly',
        }
        assert form.fields['delayed_rejection_date'].initial == datetime(
            2025, 3, 12, 13, 9
        )
        content = str(form['delayed_rejection'])
        doc = pq(content)
        inputs = doc('input[type=radio]')
        assert (
            inputs[0].label.text_content().strip()
            == 'Delay rejection, requiring developer to correct before…'
        )
        assert inputs[0].attrib['value'] == 'True'
        assert inputs[1].label.text_content().strip() == 'Reject immediately.'
        assert inputs[1].attrib['value'] == 'False'
        assert inputs[1].attrib['checked'] == 'checked'
        assert inputs[1].attrib['class'] == 'data-toggle'
        assert inputs[1].attrib['data-value'] == 'reject_multiple_versions'
        assert inputs[2].label.text_content().strip() == 'Clear pending rejection.'
        assert inputs[2].attrib['value'] == ''
        assert inputs[2].attrib['class'] == 'data-toggle'
        assert (
            inputs[2].attrib['data-value']
            == 'change_or_clear_pending_rejection_multiple_versions'
        )

    @time_machine.travel('2025-01-23 12:52', tick=False)
    def test_delayed_rejection_days_shows_up_for_admin_reviewers(self):
        # Admin reviewers can customize the delayed rejection period.
        self.grant_permission(self.request.user, 'Addons:Review')
        self.grant_permission(self.request.user, 'Reviews:Admin')
        form = self.get_form()
        assert 'delayed_rejection_date' in form.fields
        assert 'delayed_rejection' in form.fields
        assert form.fields['delayed_rejection_date'].widget.attrs == {
            'min': '2025-01-24T12:52',
        }
        assert form.fields['delayed_rejection_date'].initial == datetime(
            2025, 2, 22, 13, 52
        )
        content = str(form['delayed_rejection'])
        doc = pq(content)
        inputs = doc('input[type=radio]')
        assert (
            inputs[0].label.text_content().strip()
            == 'Delay rejection, requiring developer to correct before…'
        )
        assert inputs[0].attrib['value'] == 'True'
        assert inputs[1].label.text_content().strip() == 'Reject immediately.'
        assert inputs[1].attrib['value'] == 'False'
        assert inputs[1].attrib['checked'] == 'checked'
        assert inputs[1].attrib['class'] == 'data-toggle'
        assert inputs[1].attrib['data-value'] == 'reject_multiple_versions'
        assert inputs[2].label.text_content().strip() == 'Clear pending rejection.'
        assert inputs[2].attrib['value'] == ''
        assert inputs[2].attrib['class'] == 'data-toggle'
        assert (
            inputs[2].attrib['data-value']
            == 'change_or_clear_pending_rejection_multiple_versions'
        )

    @time_machine.travel('2025-01-23 12:52', tick=False)
    def test_delayed_rejection_days_value_not_in_the_future(self):
        self.grant_permission(self.request.user, 'Addons:Review,Reviews:Admin')
        self.reason_a = ReviewActionReason.objects.create(
            name='a reason',
            is_active=True,
            canned_response='Canned response for A',
        )
        data = {
            'action': 'reject_multiple_versions',
            'comments': 'foo!',
            'delayed_rejection': 'True',
            'delayed_rejection_date': '2025-01-23T12:52',
            'reasons': [self.reason_a.pk],
            'versions': [self.version.pk],
        }
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors['delayed_rejection_date'] == [
            'Delayed rejection date should be at least one day in the future'
        ]

        data['delayed_rejection_date'] = '2025-01-24T12:52'
        form = self.get_form(data=data)
        assert form.is_valid(), form.errors

    def test_delayable_action_missing_fields(self):
        self.grant_permission(self.request.user, 'Addons:Review,Reviews:Admin')
        self.reason_a = ReviewActionReason.objects.create(
            name='a reason',
            is_active=True,
            canned_response='Canned response for A',
        )
        data = {
            'action': 'reject_multiple_versions',
            'comments': 'foo!',
            'reasons': [self.reason_a.pk],
            'versions': [self.version.pk],
        }
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors['delayed_rejection'] == ['This field is required.']

        # 'False' or '' works, we just want to ensure the field was submitted.
        form = self.get_form(data=data)
        data['delayed_rejection'] = ''
        assert form.is_valid()
        form = self.get_form(data=data)
        data['delayed_rejection'] = 'False'
        assert form.is_valid()

        # If 'True', we need a date.
        data['delayed_rejection'] = 'True'
        data['delayed_rejection_date'] = ''
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors['delayed_rejection_date'] == ['This field is required.']

    def test_change_pending_rejection_multiple_versions_different_dates(self):
        self.grant_permission(self.request.user, 'Addons:Review,Reviews:Admin')
        in_the_future = datetime.now() + timedelta(days=15)
        in_the_future2 = datetime.now() + timedelta(days=55)
        VersionReviewerFlags.objects.create(
            version=self.version,
            pending_rejection=in_the_future,
            pending_rejection_by=self.request.user,
            pending_content_rejection=False,
        )
        new_version = version_factory(addon=self.addon)
        VersionReviewerFlags.objects.create(
            version=new_version,
            pending_rejection=in_the_future2,
            pending_rejection_by=self.request.user,
            pending_content_rejection=False,
        )

        data = {
            'action': 'change_or_clear_pending_rejection_multiple_versions',
            'delayed_rejection': 'True',
            'delayed_rejection_date': in_the_future.isoformat()[:16],
            'versions': [self.version.pk, new_version.pk],
        }
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            'versions': [
                'Can only change the delayed rejection date of multiple '
                'versions at once if their pending rejection dates are all '
                'the same.'
            ]
        }

    def test_version_pk(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        data = {'action': 'comment', 'comments': 'lol'}
        form = self.get_form(data=data)
        assert form.is_valid(), form.errors

        form = self.get_form(data={**data, 'version_pk': 99999})
        assert not form.is_valid()
        assert form.errors == {
            'version_pk': ['Version mismatch - the latest version has changed!']
        }

        form = self.get_form(data={**data, 'version_pk': self.version.pk})
        assert form.is_valid(), form.errors

    def test_cinder_jobs_to_resolve_choices(self):
        abuse_kw = {
            'guid': self.addon.guid,
            'location': AbuseReport.LOCATION.ADDON,
            'reason': AbuseReport.REASONS.POLICY_VIOLATION,
        }
        cinder_job_2_reports = CinderJob.objects.create(
            created=datetime(2025, 5, 22, 11, 27, 42, 123456),
            job_id='2 reports',
            resolvable_in_reviewer_tools=True,
            target_addon=self.addon,
        )
        AbuseReport.objects.create(
            **abuse_kw,
            cinder_job=cinder_job_2_reports,  # no message
        )
        AbuseReport.objects.create(
            **abuse_kw, cinder_job=cinder_job_2_reports, message='bbb'
        )

        cinder_job_appealed = CinderJob.objects.create(
            job_id='appealed',
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                addon=self.addon,
            ),
            resolvable_in_reviewer_tools=True,
            target_addon=self.addon,
        )
        appealed_abuse_report = AbuseReport.objects.create(
            **abuse_kw,
            cinder_job=cinder_job_appealed,
            message='ccc',
            addon_version='1.2',
        )
        cinder_job_appeal = CinderJob.objects.create(
            created=datetime(2025, 5, 6, 1, 24, 2, 194875),
            job_id='appeal',
            resolvable_in_reviewer_tools=True,
            target_addon=self.addon,
        )
        cinder_job_appealed.decision.update(appeal_job=cinder_job_appeal)
        CinderAppeal.objects.create(
            text='some justification',
            decision=cinder_job_appealed.decision,
        )
        # This wouldn't happen - a reporter can't appeal a disable decision
        # - but we want to test the rendering of reporter vs. developer appeal text
        CinderAppeal.objects.create(
            text='some other justification',
            decision=cinder_job_appealed.decision,
            reporter_report=appealed_abuse_report,
        )

        cinder_job_forwarded = CinderJob.objects.create(
            created=datetime(2025, 4, 8, 15, 16, 3, 550090),
            job_id='forwarded',
            resolvable_in_reviewer_tools=True,
            target_addon=self.addon,
        )
        ContentDecision.objects.create(
            created=datetime(2025, 5, 23, 22, 54, 4, 270060),
            action=DECISION_ACTIONS.AMO_REQUEUE,
            private_notes='Why o why',
            addon=self.addon,
            cinder_job=cinder_job_forwarded,
        )
        CinderQueueMove.objects.create(
            created=datetime(2025, 5, 22, 11, 42, 5, 541216),
            cinder_job=cinder_job_forwarded,
            notes='Zee de zee',
            to_queue='amo-env-content-infringment',
        )
        AbuseReport.objects.create(
            **{**abuse_kw, 'location': AbuseReport.LOCATION.AMO},
            message='ddd',
            cinder_job=cinder_job_forwarded,
            addon_version='<script>alert()</script>',
        )

        AbuseReport.objects.create(
            **{**abuse_kw, 'location': AbuseReport.LOCATION.AMO},
            message='eee',
            cinder_job=CinderJob.objects.create(
                job_id='not reviewer handled',
                resolvable_in_reviewer_tools=False,
                target_addon=self.addon,
            ),
        )
        AbuseReport.objects.create(
            **{**abuse_kw},
            message='fff',
            cinder_job=CinderJob.objects.create(
                job_id='already resolved',
                decision=ContentDecision.objects.create(
                    action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                    addon=self.addon,
                ),
                resolvable_in_reviewer_tools=True,
            ),
        )

        form = self.get_form()
        choices = form.fields['cinder_jobs_to_resolve'].choices
        qs_list = list(choices.queryset)
        assert qs_list == [
            # Only unresolved, reviewer handled, jobs are shown
            cinder_job_forwarded,
            cinder_job_appeal,
            cinder_job_2_reports,
        ]

        content = str(form['cinder_jobs_to_resolve'])
        doc = pq(content)
        label_0 = doc('label[for="id_cinder_jobs_to_resolve_0"]')
        assert label_0.text() == (
            '(Created on April 8, 2025, 3:16 p.m.) '
            '[Forwarded on May 22, 2025, 11:42 a.m.] '
            '[Requeued on May 23, 2025, 10:54 p.m.] '
            '"DSA: It violates Mozilla\'s Add-on Policies"\n'
            'Reasoning: Zee de zee; Why o why\n\n'
            'Show detail on 1 reports\n'
            'v[<script>alert()</script>]: ddd'
        )
        assert '<script>alert()</script>' not in content  # should be escaped
        assert '&lt;script&gt;alert()&lt;/script&gt' in content  # should be escaped
        label_1 = doc('label[for="id_cinder_jobs_to_resolve_1"]')
        assert label_1.text() == (
            '(Created on May 6, 2025, 1:24 a.m.) '
            '[Appeal] "DSA: It violates Mozilla\'s Add-on Policies"\n'
            'Developer Appeal: some justification\n'
            'Reporter Appeal: some other justification\n\n'
            'Show detail on 1 reports\n'
            'v[1.2]: ccc'
        )
        label_2 = doc('label[for="id_cinder_jobs_to_resolve_2"]')
        assert label_2.text() == (
            '(Created on May 22, 2025, 11:27 a.m.) '
            '"DSA: It violates Mozilla\'s Add-on Policies"\n\n'
            'Show detail on 2 reports\n<no message>\nbbb'
        )

        assert label_0.attr['class'] == 'data-toggle-hide'
        assert label_0.attr['data-value'] == 'resolve_appeal_job'
        assert label_1.attr['class'] == 'data-toggle-hide'
        assert label_1.attr['data-value'] == ' '.join(
            ('resolve_reports_job', 'reject', 'reject_multiple_versions')
        )
        assert label_2.attr['class'] == 'data-toggle-hide'
        assert label_2.attr['data-value'] == 'resolve_appeal_job'

    def test_cinder_policies_choices(self):
        policy_exposed = CinderPolicy.objects.create(
            uuid='1', name='foo', expose_in_reviewer_tools=True
        )
        CinderPolicy.objects.create(
            uuid='2', name='baa', expose_in_reviewer_tools=False
        )

        form = self.get_form()
        choices = form.fields['cinder_policies'].choices
        qs_list = list(choices.queryset)
        assert qs_list == [
            # only policies that are expose_in_reviewer_tools=True should be included
            policy_exposed
        ]

    def test_upload_attachment(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        attachment = ContentFile('Pseudo File', name='attachment.txt')
        data = {
            'action': 'reply',
            'comments': 'lol',
            'versions': [self.version.pk],
        }
        files = {'attachment_file': attachment}

        form = self.get_form(data=data, files=files)
        assert form.is_valid()
        assert not form.errors

        data['attachment_input'] = 'whee'
        form = self.get_form(data=data)
        assert form.is_valid()
        assert not form.errors

        form = self.get_form(data=data, files=files)
        assert not form.is_valid()
        assert form.errors == {
            'attachment_input': ['Cannot upload both a file and input.']
        }

    def test_cinder_policy_choices(self):
        CinderPolicy.objects.create(uuid='not-exposed', name='not exposed')
        CinderPolicy.objects.create(
            uuid='no-enforcement', name='no enforcement', expose_in_reviewer_tools=True
        )
        CinderPolicy.objects.create(
            uuid='4-rejections',
            name='for rejections',
            expose_in_reviewer_tools=True,
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'some-other-action',
            ],
        )
        CinderPolicy.objects.create(
            uuid='4-approve',
            name='for approving',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_APPROVE.api_value],
        )
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        with override_switch('cinder_policy_review_reasons_enabled', active=True):
            self.grant_permission(self.request.user, 'Addons:Review')
            form = self.get_form()

        content = str(form['cinder_policies'])
        doc = pq(content)
        label_0 = doc('#id_cinder_policies_0')
        label_1 = doc('#id_cinder_policies_1')
        label_2 = doc('#id_cinder_policies_2')

        assert label_0.attr['class'] == 'data-toggle'
        assert label_0.attr['data-value'] == ''
        assert label_1.attr['class'] == 'data-toggle'
        assert label_1.attr['data-value'] == 'reject reject_multiple_versions'
        assert label_2.attr['class'] == 'data-toggle'
        assert label_2.attr['data-value'] == 'public'

    def test_policy_values_fields(self):
        policy_0 = CinderPolicy.objects.create(
            uuid='4-rejections',
            name='for rejections',
            expose_in_reviewer_tools=True,
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'some-other-action',
            ],
            text='Something {THIS} and {<THAT_"}?',
        )
        policy_1 = CinderPolicy.objects.create(
            uuid='4-approve',
            name='for approving',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_APPROVE.api_value],
            text='No placeholders here',
        )
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        with override_switch('cinder_policy_review_reasons_enabled', active=True):
            self.grant_permission(self.request.user, 'Addons:Review')
            form = self.get_form()

        content = str(form['policy_values'])
        doc = pq(content)
        div_0 = doc(f'#policy-text-{policy_0.id}')
        div_1 = doc(f'#policy-text-{policy_1.id}')

        assert 'hidden' in div_0[0].attrib
        assert div_0.html() == (
            f'Something <input type="text" name="policy_values_{policy_0.id}_THIS"'
            ' placeholder="THIS" id="id_policy_values_0"/>\n\n '
            f'and <input type="text" name="policy_values_{policy_0.id}_&lt;THAT_&quot;"'
            ' placeholder="&lt;THAT_&quot;" id="id_policy_values_1"/>\n\n'
            '?'
        )
        assert 'hidden' in div_1[0].attrib
        assert div_1.html() == ('No placeholders here')


class TestHeldDecisionReviewForm(TestCase):
    def test_pending_decision(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            action_date=None,
        )
        form = HeldDecisionReviewForm({'choice': 'yes'}, decision=decision)
        assert form.is_valid()

        decision.update(action_date=datetime.now())
        form = HeldDecisionReviewForm({'choice': 'yes'}, decision=decision)
        assert not form.is_valid()

        decision.update(action_date=None)
        ContentDecision.objects.create(
            addon=decision.addon, action=decision.action, override_of=decision
        )
        form = HeldDecisionReviewForm({'choice': 'yes'}, decision=decision)
        assert not form.is_valid()

    def test_choices_addon(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            action_date=None,
        )
        form = HeldDecisionReviewForm(decision=decision)
        assert form.fields['choice'].choices == [
            ('yes', 'Proceed with action'),
            ('cancel', 'Cancel and enqueue in Reviewer Tools'),
        ]

    def test_choices_user(self):
        decision = ContentDecision.objects.create(
            user=user_factory(),
            action=DECISION_ACTIONS.AMO_BAN_USER,
            action_date=None,
        )
        form = HeldDecisionReviewForm(decision=decision)
        assert form.fields['choice'].choices == [
            ('yes', 'Proceed with action'),
            ('no', 'Approve content instead'),
        ]

    def test_choices_rating(self):
        decision = ContentDecision.objects.create(
            rating=Rating.objects.create(user=user_factory(), addon=addon_factory()),
            action=DECISION_ACTIONS.AMO_DELETE_RATING,
            action_date=None,
        )
        form = HeldDecisionReviewForm(decision=decision)
        assert form.fields['choice'].choices == [
            ('yes', 'Proceed with action'),
            ('no', 'Approve content instead'),
        ]

    def test_choices_collection(self):
        decision = ContentDecision.objects.create(
            collection=Collection.objects.create(),
            action=DECISION_ACTIONS.AMO_DELETE_COLLECTION,
            action_date=None,
        )
        form = HeldDecisionReviewForm(decision=decision)
        assert form.fields['choice'].choices == [
            ('yes', 'Proceed with action'),
            ('no', 'Approve content instead'),
        ]


def test_review_queue_filter_form_due_date_reasons():
    form = ReviewQueueFilter(data=None)
    assert form.fields['due_date_reasons'].choices == [
        (entry.annotation, entry.display) for entry in NeedsHumanReview.REASONS.entries
    ]
