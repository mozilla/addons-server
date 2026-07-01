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

from ..forms import DecisionField, HeldDecisionReviewForm, ReviewForm, ReviewQueueFilter
from ..models import AutoApprovalSummary, NeedsHumanReview
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

    @override_switch('enable-policy-review-selection', active=True)
    def test_cannot_resolve_jobs_and_override_decision(self):
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
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
        )
        decision = ContentDecision.objects.create(
            addon=self.addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        data = {
            'action': 'review_with_policy',
            'cinder_jobs_to_resolve': [job.id],
            'cinder_policies': [policy.id],
            'override_decision': decision.id,
        }
        form = self.get_form(data=data)
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {
            'cinder_jobs_to_resolve': [
                'Cannot resolve jobs while overriding a previous decision.'
            ]
        }

    def test_override_decision_queryset(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        # A decision for this add-on that hasn't been overridden: included.
        decision = ContentDecision.objects.create(
            addon=self.addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        # A decision for this add-on that has already been overridden: excluded,
        # but the decision overriding it (also for this add-on) is included.
        overridden_decision = ContentDecision.objects.create(
            addon=self.addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        overriding_decision = ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            override_of=overridden_decision,
        )
        # A decision for a different add-on: excluded.
        ContentDecision.objects.create(
            addon=addon_factory(), action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )

        form = self.get_form()
        assert set(form.fields['override_decision'].queryset) == {
            decision,
            overriding_decision,
        }

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
        action_names_and_enforcement_actions = (
            ('public', DECISION_ACTIONS.AMO_APPROVE.api_value),
            ('reject', DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value),
            ('disable_addon', DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value),
        )
        for action_name, enforcement_action in action_names_and_enforcement_actions:
            policy.update(enforcement_actions=[enforcement_action])
            form = self.get_form(
                data={'action': action_name, 'cinder_policies': [policy.id]}
            )
            assert 'comments' not in form.helper.actions[action_name]
            assert form.is_bound
            assert form.is_valid(), form.errors
            assert not form.errors

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

    def test_appeal_action_require_with_appeal_deny(self):
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
            'action': 'appeal_deny',
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

    def test_policy_actions(self):
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
            name='disable',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
        )
        action_policy_b = CinderPolicy.objects.create(
            uuid='b',
            name='disable again',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
        )
        action_policy_c = CinderPolicy.objects.create(
            uuid='c',
            name='reject',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value],
        )
        form = self.get_form()
        assert not form.is_bound
        data = {
            'action': 'reject',
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

        # Fine: those are not positive actions
        data['cinder_policies'] = [action_policy_a.id, action_policy_c.id]
        form = self.get_form(data=data)
        assert form.is_valid()
        assert not form.errors

        # Also fine if the policies have the same action
        data['cinder_policies'] = [action_policy_a.id, action_policy_b.id]
        form = self.get_form(data=data)
        assert form.is_valid(), form.errors
        assert not form.errors

        # or if it's a single policy
        data['cinder_policies'] = [action_policy_c.id]
        form = self.get_form(data=data)
        assert form.is_valid(), form.errors
        assert not form.errors

        # multiple primary enforcement action per policy are prevented if that happens
        action_policy_c.update(
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value,
            ]
        )
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            'cinder_policies': [
                'Invalid policies selected with more than one primary enforcement '
                'action.'
            ]
        }

    def test_policy_actions_multiple_positive(self):
        # Selecting policies that result in multiple positive enforcement
        # actions should raise an error.
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        action_policy_approve = CinderPolicy.objects.create(
            uuid='approve',
            name='approve',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_APPROVE.api_value],
        )
        action_policy_ignore = CinderPolicy.objects.create(
            uuid='ignore',
            name='ignore',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_IGNORE.api_value],
        )
        data = {
            'action': 'resolve_reports_job',
            'cinder_jobs_to_resolve': [job.id],
            'cinder_policies': [action_policy_ignore.id, action_policy_approve.id],
        }
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            'cinder_policies': [
                'Selecting multiple policies with different non-negative '
                'enforcement actions is not supported.'
            ]
        }

    @override_switch('enable-policy-review-selection', active=True)
    def test_policy_actions_with_policy_enforcement(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        no_action_policy = CinderPolicy.objects.create(
            uuid='no', name='no action', expose_in_reviewer_tools=True
        )
        action_policy_disable = CinderPolicy.objects.create(
            uuid='disable',
            name='disable',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
        )
        action_policy_reject = CinderPolicy.objects.create(
            uuid='reject',
            name='reject',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value],
        )
        action_policy_approve = CinderPolicy.objects.create(
            uuid='approve',
            name='approve',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_APPROVE.api_value],
        )
        action_policy_ignore = CinderPolicy.objects.create(
            uuid='ignore',
            name='ignore',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_IGNORE.api_value],
        )
        form = self.get_form()
        assert not form.is_bound

        data = {
            'action': 'review_with_policy',
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

        # multiple policies with different enforcement actions are fine when the action
        # has policy_enforcement=True
        data['cinder_policies'] = [action_policy_disable.id, action_policy_reject.id]
        form = self.get_form(data=data)
        assert form.is_valid(), form.errors
        assert not form.errors
        assert form.cleaned_data['most_important_policy_actions'] == (
            (DECISION_ACTIONS.AMO_DISABLE_ADDON,),
            (),
        )

        # multiple primary enforcement action per policy are prevented if that happens
        action_policy_multiple_primary = CinderPolicy.objects.create(
            uuid='multi',
            name='multi',
            expose_in_reviewer_tools=True,
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value,
            ],
        )
        data['cinder_policies'] = [action_policy_multiple_primary.id]
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            'cinder_policies': [
                'Invalid policies selected with more than one primary enforcement '
                'action.'
            ]
        }

        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=self.addon, appeal_job=job
        )
        data['action'] = 'appeal_override'
        # and multiple enforcement actions only applies to negative policies
        data['cinder_policies'] = [action_policy_ignore.id, action_policy_approve.id]
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            'cinder_policies': [
                'Selecting multiple policies with different non-negative '
                'enforcement actions is not supported.'
            ]
        }

    @override_switch('enable-policy-review-selection', active=True)
    def test_versions_required_when_enforcement_is_on_versions(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        disable_policy = CinderPolicy.objects.create(
            uuid='a',
            name='disable',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
        )
        reject_policy = CinderPolicy.objects.create(
            uuid='c',
            name='reject',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value],
        )

        data = {
            'action': 'review_with_policy',
            'cinder_policies': [disable_policy.id],
        }
        form = self.get_form(data=data)
        # versions isn't required
        assert form.is_valid(), form.errors

        data['cinder_policies'] = [disable_policy.id, reject_policy.id]
        form = self.get_form(data=data)
        # disable action takes priority over reject, so versions isn't required
        assert form.is_valid(), form.errors

        # and versions is cleaned if present
        data['versions'] = [self.version.id]
        form = self.get_form(data=data)
        assert form.is_valid(), form.errors
        assert form.cleaned_data['versions'] == []

        # versions are required for a policy that requires versions
        del data['versions']
        data['cinder_policies'] = [reject_policy.id]
        form = self.get_form(data=data)
        assert not form.is_valid()
        action = form.cleaned_data['action']
        assert action == 'review_with_policy'
        assert form.cleaned_data['cinder_policies'] == [reject_policy]
        assert form.helper.get_actions()[action]['multiple_versions']
        assert form.errors == {'versions': ['This field is required.']}

        data['versions'] = [self.version.id]
        form = self.get_form(data=data)
        assert form.is_valid(), form.errors
        assert not form.errors
        assert list(form.cleaned_data['versions']) == [self.version]

        # test that versions is required when there *aren't* any versions
        self.version.file.update(status=amo.STATUS_DISABLED)
        del data['versions']
        form = self.get_form(data=data)
        assert not form.is_valid()
        action = form.cleaned_data['action']
        assert action == 'review_with_policy'
        assert form.cleaned_data['cinder_policies'] == [reject_policy]
        assert form.helper.get_actions()[action]['multiple_versions']
        assert form.errors == {'versions': ['This field is required.']}

    def test_cinder_jobs_filtered_for_resolve_reports_job_and_appeal_deny(self):
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
            'action': 'appeal_deny',
            'comments': 'lol',
            'appeal_action': ['deny'],
            'cinder_jobs_to_resolve': [report_job.id],
        }
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {'cinder_jobs_to_resolve': ['This field is required.']}

        data['cinder_jobs_to_resolve'] = [report_job, appeal_job]
        form = self.get_form(data=data)
        assert form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [appeal_job]

        data = {
            'action': 'resolve_reports_job',
            'cinder_policies': [policy.id],
            'cinder_jobs_to_resolve': [appeal_job.id],
        }
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {'cinder_jobs_to_resolve': ['This field is required.']}

        data['cinder_jobs_to_resolve'] = [report_job.id, appeal_job.id]
        form = self.get_form(data=data)
        assert form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [report_job]

    def test_cinder_jobs_filtered_for_reject_or_reject_multiple_versions(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        developer_appeal_job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        decision = ContentDecision.objects.create(
            appeal_job=developer_appeal_job,
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        )
        CinderAppeal.objects.create(decision=decision)
        report_job = CinderJob.objects.create(
            job_id='2', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        AbuseReport.objects.create(cinder_job=report_job, guid=self.addon.guid)

        other_report_job = CinderJob.objects.create(
            job_id='3', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        other_report = AbuseReport.objects.create(
            cinder_job=other_report_job, guid=self.addon.guid
        )
        reporter_appeal_other_report_job = CinderJob.objects.create(
            job_id='4', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        other_decision = ContentDecision.objects.create(
            cinder_job=other_report_job,
            appeal_job=reporter_appeal_other_report_job,
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_IGNORE,
        )
        CinderAppeal.objects.create(
            decision=other_decision, reporter_report=other_report
        )
        policy = CinderPolicy.objects.create(
            uuid='a',
            name='ignore',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value],
        )

        data = {
            'action': 'reject_multiple_versions',
            'comments': 'lol',
            'cinder_jobs_to_resolve': [
                reporter_appeal_other_report_job,
                developer_appeal_job,
            ],
            'versions': [self.version.pk],
            'cinder_policies': [policy.id],
            'delayed_rejection': False,
        }
        form = self.get_form(data=data)
        assert form.is_valid(), form.errors
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [
            reporter_appeal_other_report_job
        ]

        data['cinder_jobs_to_resolve'] = [
            reporter_appeal_other_report_job,
            report_job,
            developer_appeal_job,
        ]
        form = self.get_form(data=data)
        assert form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [
            reporter_appeal_other_report_job,
            report_job,
        ]

        data = {
            'action': 'reject',
            'cinder_policies': [policy.id],
            'cinder_jobs_to_resolve': [
                reporter_appeal_other_report_job,
                developer_appeal_job,
            ],
        }
        form = self.get_form(data=data)
        assert form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [
            reporter_appeal_other_report_job
        ]

        data['cinder_jobs_to_resolve'] = [
            reporter_appeal_other_report_job,
            report_job,
            developer_appeal_job,
        ]
        form = self.get_form(data=data)
        assert form.is_valid()
        assert form.cleaned_data['cinder_jobs_to_resolve'] == [
            reporter_appeal_other_report_job,
            report_job,
        ]

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

    def test_action_required_by_default(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        form = self.get_form()
        assert not form.is_bound
        form = self.get_form(
            data={
                'cinder_policies': [
                    CinderPolicy.objects.create(
                        uuid='1',
                        name='policy 1',
                        expose_in_reviewer_tools=True,
                        enforcement_actions=[
                            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value
                        ],
                    )
                ],
                'comments': '.',
            }
        )
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {'action': ['This field is required.']}

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
        assert select.attrib.get('class') == 'data-toggle data-toggle-enforcement'
        assert select.attrib.get('data-value').split(' ') == expected_select_data_value
        assert select.attrib.get('data-value-enforcement') == (
            f"'{DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.value}' "
            f"'{DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON.value}' "
            f"'{DECISION_ACTIONS.AMO_APPROVE_VERSION.value}'"
        )

        # <option>s should as well, and the value depends on which version:
        # the approved one and the pending one should have different values.
        assert len(doc('option')) == 4
        option1 = doc('option[value="%s"]' % self.version.pk)[0]
        assert option1.attrib.get('class') == 'data-toggle'
        assert option1.attrib.get('data-value').split(' ') == [
            # That version is approved.
            'review_with_policy',
            'block_multiple_versions',
            'reject_multiple_versions',
            'reply',
            'set_needs_human_review_multiple_versions',
            'review_with_policy_approve',
        ]
        assert option1.attrib.get('value') == str(self.version.pk)

        option2 = doc('option[value="%s"]' % pending_version.pk)[0]
        assert option2.attrib.get('class') == 'data-toggle'
        assert option2.attrib.get('data-value').split(' ') == [
            # That version is pending.
            'review_with_policy_approve',
            'review_with_policy',
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
            # set_needs_human_review_multiple_version
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
        assert select.attrib.get('class') == 'data-toggle data-toggle-enforcement'
        assert select.attrib.get('data-value').split(' ') == expected_select_data_value
        assert select.attrib.get('data-value-enforcement') == (
            f"'{DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.value}' "
            f"'{DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON.value}' "
            f"'{DECISION_ACTIONS.AMO_APPROVE_VERSION.value}'"
        )

        # <option>s should as well, and the value depends on which version:
        # the approved one and the pending one should have different values.
        assert len(doc('option')) == 5
        option1 = doc('option[value="%s"]' % self.version.pk)[0]
        assert option1.attrib.get('class') == 'data-toggle'
        assert option1.attrib.get('data-value').split(' ') == [
            # That version is approved.
            'review_with_policy_approve',
            'review_with_policy',
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
            'review_with_policy_approve',
            'review_with_policy',
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
                'cinder_policies': [
                    CinderPolicy.objects.create(
                        uuid='1',
                        name='policy 1',
                        expose_in_reviewer_tools=True,
                        enforcement_actions=[
                            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value
                        ],
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
        data = {
            'action': 'reject_multiple_versions',
            'comments': 'foo!',
            'delayed_rejection': 'True',
            'delayed_rejection_date': '2025-01-23T12:52',
            'cinder_policies': [
                CinderPolicy.objects.create(
                    uuid='1',
                    name='policy 1',
                    expose_in_reviewer_tools=True,
                    enforcement_actions=[
                        DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value
                    ],
                )
            ],
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
        data = {
            'action': 'reject_multiple_versions',
            'comments': 'foo!',
            'cinder_policies': [
                CinderPolicy.objects.create(
                    uuid='1',
                    name='policy 1',
                    expose_in_reviewer_tools=True,
                    enforcement_actions=[
                        DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value
                    ],
                )
            ],
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
        cinder_job_appealed.final_decision.update(appeal_job=cinder_job_appeal)
        appeal_obj = CinderAppeal.objects.create(
            text='some justification',
            decision=cinder_job_appealed.final_decision,
        )
        # This wouldn't happen - a reporter can't appeal a disable decision
        # - but we want to test the rendering of reporter vs. developer appeal text
        CinderAppeal.objects.create(
            text='some other justification',
            decision=cinder_job_appealed.final_decision,
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
        assert label_0.attr['data-value'] == 'appeal_deny appeal_override'
        assert label_1.attr['class'] == 'data-toggle-hide'
        assert label_1.attr['data-value'] == ' '.join(
            (
                'review_with_policy_approve',
                'review_with_policy',
                'reject',
                'reject_multiple_versions',
                'resolve_reports_job',
            )
        )
        assert label_2.attr['class'] == 'data-toggle-hide'
        assert label_2.attr['data-value'] == 'appeal_deny appeal_override'

        # If we make the developer appeal a reporter appeal instead, suddenly
        # the widget option is shown for reject/reject_multiple_versions.
        appeal_obj.update(
            reporter_report=AbuseReport.objects.create(
                **abuse_kw, cinder_job=cinder_job_appealed
            )
        )
        form = self.get_form()
        doc = pq(str(form['cinder_jobs_to_resolve']))
        label_1 = doc('label[for="id_cinder_jobs_to_resolve_1"]')
        assert label_1.attr['class'] == 'data-toggle-hide'
        assert label_1.attr['data-value'] == 'appeal_override resolve_reports_job'

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
                'some-invalid-action',
                DECISION_ACTIONS.AMO_FU_DELAY_LONG_SOFT_BLOCK_ADDON.api_value,
                DECISION_ACTIONS.AMO_FU_DELAY_SHORT_HARD_BLOCK_ADDON.api_value,
            ],
        )
        CinderPolicy.objects.create(
            uuid='4-approve',
            name='for approving',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_APPROVE.api_value],
        )
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.grant_permission(self.request.user, 'Addons:Review')
        form = self.get_form()

        content = str(form['cinder_policies'])
        doc = pq(content)
        label_0 = doc('#id_cinder_policies_0')
        label_1 = doc('#id_cinder_policies_1')
        label_2 = doc('#id_cinder_policies_2')

        assert label_0.attr['class'] == 'data-toggle'
        assert label_0.attr['data-value'] == ''
        assert label_0.attr['data-enforcement-primary-actions'] == '[]'
        assert label_0.attr['data-enforcement-followup-actions'] == '[]'
        assert label_0.attr['data-enforcement-actions-order'] == ''

        assert label_1.attr['class'] == 'data-toggle'
        assert label_1.attr['data-value'] == 'reject reject_multiple_versions'
        assert (
            label_1.attr['data-enforcement-primary-actions']
            == f'[{DECISION_ACTIONS.AMO_DISABLE_ADDON.value}]'
        )
        assert label_1.attr['data-enforcement-followup-actions'] == (
            f'[{DECISION_ACTIONS.AMO_FU_DELAY_LONG_SOFT_BLOCK_ADDON.value}, '
            f'{DECISION_ACTIONS.AMO_FU_DELAY_SHORT_HARD_BLOCK_ADDON.value}]'
        )
        assert label_1.attr['data-enforcement-actions-order'] == '090500'

        assert label_2.attr['class'] == 'data-toggle'
        assert label_2.attr['data-value'] == 'public'
        assert (
            label_2.attr['data-enforcement-primary-actions']
            == f'[{DECISION_ACTIONS.AMO_APPROVE.value}]'
        )
        assert label_2.attr['data-enforcement-followup-actions'] == '[]'
        assert label_2.attr['data-enforcement-actions-order'] == ''

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
        (entry.annotation, entry.label) for entry in NeedsHumanReview.REASONS
    ]


class TestDecisionFieldLabel(TestCase):
    def _make_field(self):
        return DecisionField(queryset=ContentDecision.objects.all())

    def test_label_version_specific(self):
        """VERSION_SPECIFIC actions include version info; truncate beyond 5."""
        addon = addon_factory()
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            action_date=datetime.now(),
        )
        field = self._make_field()

        # No versions yet - no version info in label
        assert 'versions' not in field.label_from_instance(decision)

        # Add 2 versions - both shown, no truncation
        v1 = version_factory(addon=addon, version='1.0')
        v2 = version_factory(addon=addon, version='2.0')
        decision.target_versions.add(v1, v2)
        label = field.label_from_instance(decision)
        assert 'versions: ' in label
        assert 'more' not in label

        # Add 5 more (7 total) - truncated with remainder
        decision.target_versions.add(
            *[version_factory(addon=addon, version=f'3.{i}') for i in range(5)]
        )
        assert 'and 2 more' in field.label_from_instance(decision)

    def test_label_non_version_specific_action(self):
        """Non-VERSION_SPECIFIC actions never include version info."""
        addon = addon_factory()
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            action_date=datetime.now(),
        )
        decision.target_versions.add(version_factory(addon=addon))
        assert 'versions' not in self._make_field().label_from_instance(decision)

    def test_label_held_decision(self):
        """Held decisions (no action_date) are prefixed with [HELD]."""
        decision = ContentDecision.objects.create(
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            action_date=None,
        )
        assert self._make_field().label_from_instance(decision).startswith('[HELD] ')
