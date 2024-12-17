import uuid
from datetime import datetime

from django.core.files.base import ContentFile
from django.utils.encoding import force_str

from pyquery import PyQuery as pq

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
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.reviewers import REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
from olympia.files.models import File
from olympia.reviewers.forms import ReviewForm
from olympia.reviewers.models import (
    AutoApprovalSummary,
    ReviewActionReason,
)
from olympia.reviewers.utils import ReviewHelper
from olympia.users.models import UserProfile
from olympia.versions.models import Version


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
            'comment',
        ]

        # If an admin reviewer we also show unreject_latest_version and clear
        # pending rejection/needs human review (though the versions form would
        # be empty for the last 2 here). And disable addon.
        self.grant_permission(self.request.user, 'Reviews:Admin')
        actions = self.get_form().helper.get_actions()
        assert list(actions.keys()) == [
            'unreject_latest_version',
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'disable_addon',
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
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'disable_addon',
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
            'comment',
        ]

        # Having admin permission gives you some extra actions
        self.grant_permission(self.request.user, 'Reviews:Admin')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_DELETED, file_status=amo.STATUS_DISABLED
        )
        assert list(actions.keys()) == [
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
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
            'comment',
        ]

        # admins have extra permssions though
        self.grant_permission(self.request.user, 'Reviews:Admin')
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
        )
        assert list(actions.keys()) == [
            'reject_multiple_versions',
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'disable_addon',
            'comment',
        ]

        # The add-on is already disabled so we don't show reject_multiple_versions, but
        # reply/comment/disable_addon and clear actions are still present.
        actions = self.set_statuses_and_get_actions(
            addon_status=amo.STATUS_DISABLED, file_status=amo.STATUS_DISABLED
        )
        assert list(actions.keys()) == [
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'reply',
            'enable_addon',
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
            default_cinder_action=DECISION_ACTIONS.AMO_IGNORE,
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
            default_cinder_action=DECISION_ACTIONS.AMO_IGNORE,
        )
        action_policy_b = CinderPolicy.objects.create(
            uuid='b',
            name='ignore again',
            expose_in_reviewer_tools=True,
            default_cinder_action=DECISION_ACTIONS.AMO_IGNORE,
        )
        action_policy_c = CinderPolicy.objects.create(
            uuid='c',
            name='approve',
            expose_in_reviewer_tools=True,
            default_cinder_action=DECISION_ACTIONS.AMO_APPROVE,
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
            '__all__': ['No policies selected with an associated cinder action.']
        }

        data['cinder_policies'] = [action_policy_a.id, action_policy_c.id]
        form = self.get_form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            '__all__': ['Multiple policies selected with different cinder actions.']
        }

        data['cinder_policies'] = [action_policy_a.id, action_policy_b.id]
        form = self.get_form(data=data)
        assert form.is_valid()
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
            default_cinder_action=DECISION_ACTIONS.AMO_IGNORE,
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
                'clear_pending_rejection_multiple_versions',
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
                'clear_pending_rejection_multiple_versions',
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
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self.test_delayed_rejection_days_widget_attributes()

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
            job_id='forwarded',
            resolvable_in_reviewer_tools=True,
            target_addon=self.addon,
        )
        CinderJob.objects.create(
            job_id='forwarded_from',
            forwarded_to_job=cinder_job_forwarded,
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_ESCALATE_ADDON,
                notes='Why o why',
                addon=self.addon,
            ),
        )
        CinderQueueMove.objects.create(
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
                job_id='already resovled',
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
            '[Forwarded] "DSA: It violates Mozilla\'s Add-on Policies"\n'
            'Show detail on 1 reports\n'
            'Reasoning: Why o why; Zee de zee\n\n'
            'v[<script>alert()</script>]: ddd'
        )
        assert '<script>alert()</script>' not in content  # should be escaped
        assert '&lt;script&gt;alert()&lt;/script&gt' in content  # should be escaped
        label_1 = doc('label[for="id_cinder_jobs_to_resolve_1"]')
        assert label_1.text() == (
            '[Appeal] "DSA: It violates Mozilla\'s Add-on Policies"\n'
            'Show detail on 1 reports\n'
            'Developer Appeal: some justification\n'
            'Reporter Appeal: some other justification\n\n'
            'v[1.2]: ccc'
        )
        label_2 = doc('label[for="id_cinder_jobs_to_resolve_2"]')
        assert label_2.text() == (
            '"DSA: It violates Mozilla\'s Add-on Policies"\n'
            'Show detail on 2 reports\n<no message>\nbbb'
        )

        assert label_0.attr['class'] == 'data-toggle-hide'
        assert label_0.attr['data-value'] == 'resolve_appeal_job'
        assert label_1.attr['class'] == 'data-toggle-hide'
        assert label_1.attr['data-value'] == 'resolve_reports_job'
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
        assert form.errors == {'__all__': ['Cannot upload both a file and input.']}
