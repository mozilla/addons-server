import json
from datetime import datetime
from unittest import mock
from urllib import parse

from django.conf import settings
from django.core import mail
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db.utils import IntegrityError

import pytest
import responses

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    user_factory,
    version_review_flags_factory,
)
from olympia.constants.abuse import APPEAL_EXPIRATION_DAYS, DECISION_ACTIONS
from olympia.ratings.models import Rating
from olympia.reviewers.models import NeedsHumanReview
from olympia.versions.models import VersionReviewerFlags

from ..cinder import (
    CinderAddon,
    CinderAddonHandledByReviewers,
    CinderCollection,
    CinderRating,
    CinderUnauthenticatedReporter,
    CinderUser,
)
from ..models import AbuseReport, CinderDecision, CinderJob, CinderPolicy
from ..utils import (
    CinderActionApproveInitialDecision,
    CinderActionApproveNoAction,
    CinderActionBanUser,
    CinderActionDeleteCollection,
    CinderActionDeleteRating,
    CinderActionDisableAddon,
    CinderActionEscalateAddon,
    CinderActionIgnore,
    CinderActionOverrideApprove,
    CinderActionRejectVersion,
    CinderActionRejectVersionDelayed,
    CinderActionTargetAppealApprove,
    CinderActionTargetAppealRemovalAffirmation,
)


class TestAbuse(TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def test_choices(self):
        assert AbuseReport.ADDON_SIGNATURES.choices == (
            (None, 'None'),
            (1, 'Curated and partner'),
            (2, 'Curated'),
            (3, 'Partner'),
            (4, 'Non-curated'),
            (5, 'Unsigned'),
            (6, 'Broken'),
            (7, 'Unknown'),
            (8, 'Missing'),
            (9, 'Preliminary'),
            (10, 'Signed'),
            (11, 'System'),
            (12, 'Privileged'),
        )
        assert AbuseReport.ADDON_SIGNATURES.api_choices == (
            (None, None),
            (1, 'curated_and_partner'),
            (2, 'curated'),
            (3, 'partner'),
            (4, 'non_curated'),
            (5, 'unsigned'),
            (6, 'broken'),
            (7, 'unknown'),
            (8, 'missing'),
            (9, 'preliminary'),
            (10, 'signed'),
            (11, 'system'),
            (12, 'privileged'),
        )

        assert AbuseReport.REASONS.choices == (
            (None, 'None'),
            (1, 'Damages computer and/or data'),
            (2, 'Creates spam or advertising'),
            (3, 'Changes search / homepage / new tab page without informing user'),
            (5, 'Doesn’t work, breaks websites, or slows Firefox down'),
            (6, 'Hateful, violent, or illegal content'),
            (7, 'Pretends to be something it’s not'),
            (9, "Wasn't wanted / impossible to get rid of"),
            (
                11,
                'DSA: It contains hateful, violent, deceptive, or other inappropriate '
                'content',
            ),
            (12, 'DSA: It violates the law or contains content that violates the law'),
            (13, "DSA: It violates Mozilla's Add-on Policies"),
            (14, 'DSA: Something else'),
            (20, 'Feedback: It does not work, breaks websites, or slows down Firefox'),
            (21, "Feedback: It's spam"),
            (127, 'Other'),
        )
        assert AbuseReport.REASONS.api_choices == (
            (None, None),
            (1, 'damage'),
            (2, 'spam'),
            (3, 'settings'),
            (5, 'broken'),
            (6, 'policy'),
            (7, 'deceptive'),
            (9, 'unwanted'),
            (11, 'hateful_violent_deceptive'),
            (12, 'illegal'),
            (13, 'policy_violation'),
            (14, 'something_else'),
            (20, 'does_not_work'),
            (21, 'feedback_spam'),
            (127, 'other'),
        )

        assert AbuseReport.ADDON_INSTALL_METHODS.choices == (
            (None, 'None'),
            (1, 'Add-on Manager Web API'),
            (2, 'Direct link'),
            (3, 'Install Trigger'),
            (4, 'From File'),
            (5, 'Webext management API'),
            (6, 'Drag & Drop'),
            (7, 'Sideload'),
            (8, 'File URL'),
            (9, 'Enterprise Policy'),
            (10, 'Included in build'),
            (11, 'System Add-on'),
            (12, 'Temporary Add-on'),
            (13, 'Sync'),
            (14, 'URL'),
            (127, 'Other'),
        )

        assert AbuseReport.ADDON_INSTALL_METHODS.api_choices == (
            (None, None),
            (1, 'amwebapi'),
            (2, 'link'),
            (3, 'installtrigger'),
            (4, 'install_from_file'),
            (5, 'management_webext_api'),
            (6, 'drag_and_drop'),
            (7, 'sideload'),
            (8, 'file_url'),
            (9, 'enterprise_policy'),
            (10, 'distribution'),
            (11, 'system_addon'),
            (12, 'temporary_addon'),
            (13, 'sync'),
            (14, 'url'),
            (127, 'other'),
        )

        assert AbuseReport.ADDON_INSTALL_SOURCES.choices == (
            (None, 'None'),
            (1, 'Add-ons Manager'),
            (2, 'Add-ons Debugging'),
            (3, 'Preferences'),
            (4, 'AMO'),
            (5, 'App Profile'),
            (6, 'Disco Pane'),
            (7, 'Included in build'),
            (8, 'Extension'),
            (9, 'Enterprise Policy'),
            (10, 'File URL'),
            (11, 'GMP Plugin'),
            (12, 'Internal'),
            (13, 'Plugin'),
            (14, 'Return to AMO'),
            (15, 'Sync'),
            (16, 'System Add-on'),
            (17, 'Temporary Add-on'),
            (18, 'Unknown'),
            (19, 'Windows Registry (User)'),
            (20, 'Windows Registry (Global)'),
            (21, 'System Add-on (Profile)'),
            (22, 'System Add-on (Update)'),
            (23, 'System Add-on (Bundled)'),
            (24, 'Built-in Add-on'),
            (25, 'System-wide Add-on (User)'),
            (26, 'Application Add-on'),
            (27, 'System-wide Add-on (OS Share)'),
            (28, 'System-wide Add-on (OS Local)'),
            (127, 'Other'),
        )

        assert AbuseReport.ADDON_INSTALL_SOURCES.api_choices == (
            (None, None),
            (1, 'about_addons'),
            (2, 'about_debugging'),
            (3, 'about_preferences'),
            (4, 'amo'),
            (5, 'app_profile'),
            (6, 'disco'),
            (7, 'distribution'),
            (8, 'extension'),
            (9, 'enterprise_policy'),
            (10, 'file_url'),
            (11, 'gmp_plugin'),
            (12, 'internal'),
            (13, 'plugin'),
            (14, 'rtamo'),
            (15, 'sync'),
            (16, 'system_addon'),
            (17, 'temporary_addon'),
            (18, 'unknown'),
            (19, 'winreg_app_user'),
            (20, 'winreg_app_global'),
            (21, 'app_system_profile'),
            (22, 'app_system_addons'),
            (23, 'app_system_defaults'),
            (24, 'app_builtin'),
            (25, 'app_system_user'),
            (26, 'app_global'),
            (27, 'app_system_share'),
            (28, 'app_system_local'),
            (127, 'other'),
        )

        assert AbuseReport.REPORT_ENTRY_POINTS.choices == (
            (None, 'None'),
            (1, 'Uninstall'),
            (2, 'Menu'),
            (3, 'Toolbar context menu'),
            (4, 'AMO'),
            (5, 'Unified extensions context menu'),
        )
        assert AbuseReport.REPORT_ENTRY_POINTS.api_choices == (
            (None, None),
            (1, 'uninstall'),
            (2, 'menu'),
            (3, 'toolbar_context_menu'),
            (4, 'amo'),
            (5, 'unified_context_menu'),
        )

        assert AbuseReport.LOCATION.choices == (
            (None, 'None'),
            (1, 'Add-on page on AMO'),
            (2, 'Inside Add-on'),
            (3, 'Both on AMO and inside Add-on'),
        )
        assert AbuseReport.LOCATION.api_choices == (
            (None, None),
            (1, 'amo'),
            (2, 'addon'),
            (3, 'both'),
        )

    def test_type(self):
        addon = addon_factory(guid='@lol')
        report = AbuseReport.objects.create(guid=addon.guid)
        assert report.type == 'Addon'

        user = user_factory()
        report = AbuseReport.objects.create(user=user)
        assert report.type == 'User'

        report = AbuseReport.objects.create(
            rating=Rating.objects.create(user=user, addon=addon, rating=5)
        )
        assert report.type == 'Rating'

        report = AbuseReport.objects.create(collection=collection_factory())
        assert report.type == 'Collection'

    def test_save_soft_deleted(self):
        report = AbuseReport.objects.create(guid='@foo')
        report.delete()
        report.reason = AbuseReport.REASONS.SPAM
        report.save()
        assert report.reason == AbuseReport.REASONS.SPAM

    def test_target(self):
        report = AbuseReport.objects.create(guid='@lol')
        assert report.target is None

        addon = addon_factory(guid='@lol')
        del report.addon
        assert report.target == addon

        user = user_factory()
        report.update(guid=None, user=user)
        assert report.target == user

        rating = Rating.objects.create(user=user, addon=addon, rating=5)
        report.update(user=None, rating=rating)
        assert report.target == rating

        collection = collection_factory()
        report.update(rating=None, collection=collection)
        assert report.target == collection

    def test_is_handled_by_reviewers(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            location=AbuseReport.LOCATION.BOTH,
        )
        # location is in REVIEWER_HANDLED (BOTH) but reason is not (ILLEGAL)
        assert not abuse_report.is_handled_by_reviewers

        abuse_report.update(reason=AbuseReport.REASONS.POLICY_VIOLATION)
        # now reason is in REVIEWER_HANDLED it will be reported differently
        assert abuse_report.is_handled_by_reviewers

        abuse_report.update(location=AbuseReport.LOCATION.AMO)
        # but not if the location is not in REVIEWER_HANDLED (i.e. AMO)
        assert not abuse_report.is_handled_by_reviewers

        # test non-addons are False regardless
        abuse_report.update(location=AbuseReport.LOCATION.ADDON)
        assert abuse_report.is_handled_by_reviewers
        abuse_report.update(user=user_factory(), guid=None)
        assert not abuse_report.is_handled_by_reviewers

    def test_constraint(self):
        report = AbuseReport()
        constraints = report.get_constraints()
        assert len(constraints) == 1
        constraint = constraints[0][1][0]

        # ooooh addon is wrong.

        with self.assertRaises(ValidationError):
            constraint.validate(AbuseReport, report)

        report.user_id = 48151
        constraint.validate(AbuseReport, report)

        report.guid = '@guid'
        with self.assertRaises(ValidationError):
            constraint.validate(AbuseReport, report)

        report.guid = None
        report.rating_id = 62342
        with self.assertRaises(ValidationError):
            constraint.validate(AbuseReport, report)

        report.user_id = None
        constraint.validate(AbuseReport, report)


class TestAbuseManager(TestCase):
    def test_for_addon_finds_by_author(self):
        addon = addon_factory(users=[user_factory()])
        report = AbuseReport.objects.create(user=addon.listed_authors[0])
        assert list(AbuseReport.objects.for_addon(addon)) == [report]

    def test_for_addon_finds_by_guid(self):
        addon = addon_factory()
        report = AbuseReport.objects.create(guid=addon.guid)
        assert list(AbuseReport.objects.for_addon(addon)) == [report]

    def test_for_addon_finds_by_original_guid(self):
        addon = addon_factory(guid='foo@bar')
        addon.update(guid='guid-reused-by-pk-42')
        report = AbuseReport.objects.create(guid='foo@bar')
        assert list(AbuseReport.objects.for_addon(addon)) == [report]


class TestCinderJobManager(TestCase):
    def test_for_addon(self):
        addon = addon_factory()
        job = CinderJob.objects.create()
        assert list(CinderJob.objects.for_addon(addon)) == []
        job.update(target_addon=addon)
        assert list(CinderJob.objects.for_addon(addon)) == [job]

    def test_for_addon_appealed(self):
        addon = addon_factory()
        appeal_job = CinderJob.objects.create(job_id='appeal', target_addon=addon)
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=CinderDecision.objects.create(
                appeal_job=appeal_job,
                addon=addon,
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            ),
            target_addon=addon,
        )
        AbuseReport.objects.create(guid=addon.guid, cinder_job=original_job)
        assert list(CinderJob.objects.for_addon(addon)) == [original_job, appeal_job]

    def test_unresolved(self):
        job = CinderJob.objects.create(job_id='1')
        addon = addon_factory()
        CinderJob.objects.create(
            job_id='2',
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon
            ),
        )
        escalated_job = CinderJob.objects.create(
            job_id='3',
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_ESCALATE_ADDON, addon=addon
            ),
        )
        qs = CinderJob.objects.unresolved()
        assert len(qs) == 2
        assert list(qs) == [job, escalated_job]

    def test_reviewer_handled(self):
        not_policy_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            location=AbuseReport.LOCATION.BOTH,
            cinder_job=CinderJob.objects.create(job_id=1),
        )
        job = CinderJob.objects.create(
            job_id=2,
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon_factory()
            ),
        )
        AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            cinder_job=job,
        )
        AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.AMO,
            cinder_job=CinderJob.objects.create(job_id=3),
        )
        qs = CinderJob.objects.resolvable_in_reviewer_tools()
        assert list(qs) == []
        job.update(resolvable_in_reviewer_tools=True)
        qs = CinderJob.objects.resolvable_in_reviewer_tools()
        assert list(qs) == [job]

        appeal_job = CinderJob.objects.create(
            job_id=4, resolvable_in_reviewer_tools=True
        )
        job.decision.update(appeal_job=appeal_job)
        qs = CinderJob.objects.resolvable_in_reviewer_tools()
        assert list(qs) == [job, appeal_job]

        not_policy_report.cinder_job.update(
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_ESCALATE_ADDON,
                addon=not_policy_report.target,
            ),
            resolvable_in_reviewer_tools=True,
        )
        qs = CinderJob.objects.resolvable_in_reviewer_tools()
        assert list(qs) == [not_policy_report.cinder_job, job, appeal_job]


class TestCinderJob(TestCase):
    def setUp(self):
        user_factory(id=settings.TASK_USER_ID)

    def test_target(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        # edge case, but handle having no associated abuse_reports, decisions or appeals
        assert cinder_job.target is None

        # case when CinderJob.target_addon is set
        addon = addon_factory()
        cinder_job.update(target_addon=addon)
        assert cinder_job.target_addon == cinder_job.target == addon

        # case when there is already a decision
        cinder_job.update(
            target_addon=None,
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE, addon=addon
            ),
        )
        assert cinder_job.decision.target == cinder_job.target == addon

        # case when this is an appeal job (no decision), but the appeal had a decision
        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        cinder_job.decision.update(appeal_job=appeal_job)
        assert cinder_job.decision.target == appeal_job.target == addon

        # case when there is no appeal, no decision yet, no target_addon,
        # but an initial abuse report
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            location=AbuseReport.LOCATION.BOTH,
            cinder_job=CinderJob.objects.create(job_id='from abuse report'),
        )
        assert abuse_report.target == abuse_report.cinder_job.target == addon

    def test_get_entity_helper(self):
        addon = addon_factory()
        user = user_factory()
        helper = CinderJob.get_entity_helper(addon, resolved_in_reviewer_tools=False)
        # e.g. location is in REVIEWER_HANDLED (BOTH) but reason is not (ILLEGAL)
        assert isinstance(helper, CinderAddon)
        assert not isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version is None

        helper = CinderJob.get_entity_helper(
            addon,
            resolved_in_reviewer_tools=False,
            addon_version_string=addon.current_version.version,
        )
        # but not if the location is not in REVIEWER_HANDLED (i.e. AMO)
        assert isinstance(helper, CinderAddon)
        assert not isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version == addon.current_version

        helper = CinderJob.get_entity_helper(addon, resolved_in_reviewer_tools=True)
        # if now reason is in REVIEWER_HANDLED it will be reported differently
        assert isinstance(helper, CinderAddon)
        assert isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version is None

        helper = CinderJob.get_entity_helper(
            addon,
            resolved_in_reviewer_tools=True,
            addon_version_string=addon.current_version.version,
        )
        # if we got a version too we pass it on to the helper
        assert isinstance(helper, CinderAddon)
        assert isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version == addon.current_version

        helper = CinderJob.get_entity_helper(user, resolved_in_reviewer_tools=False)
        assert isinstance(helper, CinderUser)
        assert helper.user == user

        rating = Rating.objects.create(addon=addon, user=user, rating=4)
        helper = CinderJob.get_entity_helper(rating, resolved_in_reviewer_tools=False)
        assert isinstance(helper, CinderRating)
        assert helper.rating == rating

        collection = collection_factory()
        helper = CinderJob.get_entity_helper(
            collection, resolved_in_reviewer_tools=False
        )
        assert isinstance(helper, CinderCollection)
        assert helper.collection == collection

    def test_get_cinder_reporter(self):
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid, reason=AbuseReport.REASONS.ILLEGAL
        )
        assert CinderJob.get_cinder_reporter(abuse_report) is None

        abuse_report.update(reporter_email='mr@mr')
        entity = CinderJob.get_cinder_reporter(abuse_report)
        assert isinstance(entity, CinderUnauthenticatedReporter)
        assert entity.email == 'mr@mr'
        assert entity.name is None

        authenticated_user = user_factory()
        abuse_report.update(reporter=authenticated_user)
        entity = CinderJob.get_cinder_reporter(abuse_report)
        assert isinstance(entity, CinderUser)
        assert entity.user == authenticated_user

    def test_report(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )

        CinderJob.report(abuse_report)

        cinder_job = CinderJob.objects.get()
        assert cinder_job.job_id == '1234-xyz'
        assert cinder_job.abusereport_set.get() == abuse_report
        assert cinder_job.target_addon == abuse_report.target
        assert not cinder_job.resolvable_in_reviewer_tools

        # And check if we get back the same job_id for a subsequent report we update

        another_report = AbuseReport.objects.create(
            guid=addon.guid, reason=AbuseReport.REASONS.ILLEGAL
        )
        CinderJob.report(another_report)
        cinder_job.reload()
        assert CinderJob.objects.count() == 1
        assert list(cinder_job.abusereport_set.all()) == [abuse_report, another_report]
        assert cinder_job.target_addon == abuse_report.target
        assert not cinder_job.resolvable_in_reviewer_tools

    def test_report_with_outstanding_rejection(self):
        self.test_report()
        assert len(mail.outbox) == 0
        addon = Addon.objects.get()
        CinderJob.objects.get().update(
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON, addon=addon
            )
        )
        report_after_delayed_rejection = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='email@domain.com',
        )
        CinderJob.report(report_after_delayed_rejection)
        assert CinderJob.objects.count() == 1

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['email@domain.com']

    def test_report_resolvable_in_reviewer_tools(self):
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )

        CinderJob.report(abuse_report)

        cinder_job = CinderJob.objects.get()
        assert cinder_job.job_id == '1234-xyz'
        assert cinder_job.abusereport_set.get() == abuse_report
        assert cinder_job.target_addon == abuse_report.target
        assert cinder_job.resolvable_in_reviewer_tools

        # And check if we get back the same job_id for a subsequent report we update

        another_report = AbuseReport.objects.create(
            guid=addon_factory().guid, reason=AbuseReport.REASONS.ILLEGAL
        )
        CinderJob.report(another_report)
        cinder_job.reload()
        assert CinderJob.objects.count() == 1
        assert list(cinder_job.abusereport_set.all()) == [abuse_report, another_report]
        assert cinder_job.target_addon == abuse_report.target
        assert cinder_job.resolvable_in_reviewer_tools

    def test_process_decision(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        target = user_factory()
        AbuseReport.objects.create(user=target, cinder_job=cinder_job)
        new_date = datetime(2023, 1, 1)
        policy_a = CinderPolicy.objects.create(uuid='123-45', name='aaa', text='AAA')
        policy_b = CinderPolicy.objects.create(uuid='678-90', name='bbb', text='BBB')

        with mock.patch.object(
            CinderActionBanUser, 'process_action'
        ) as action_mock, mock.patch.object(
            CinderActionBanUser, 'notify_owners'
        ) as notify_mock:
            action_mock.return_value = (True, mock.Mock(id=999))
            cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_date=new_date,
                decision_action=DECISION_ACTIONS.AMO_BAN_USER.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
            )
        assert cinder_job.decision.cinder_id == '12345'
        assert cinder_job.decision.date == new_date
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_BAN_USER
        assert cinder_job.decision.notes == 'teh notes'
        assert cinder_job.decision.user == target
        assert action_mock.call_count == 1
        assert notify_mock.call_count == 1
        assert list(cinder_job.decision.policies.all()) == [policy_a, policy_b]

    def test_process_decision_with_duplicate_parent(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        target = user_factory()
        AbuseReport.objects.create(user=target, cinder_job=cinder_job)
        new_date = datetime(2023, 1, 1)
        parent_policy = CinderPolicy.objects.create(
            uuid='678-90', name='bbb', text='BBB'
        )
        policy = CinderPolicy.objects.create(
            uuid='123-45', name='aaa', text='AAA', parent=parent_policy
        )

        with mock.patch.object(
            CinderActionBanUser, 'process_action'
        ) as action_mock, mock.patch.object(
            CinderActionBanUser, 'notify_owners'
        ) as notify_mock:
            action_mock.return_value = (True, None)
            cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_date=new_date,
                decision_action=DECISION_ACTIONS.AMO_BAN_USER.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
            )
        assert cinder_job.decision.cinder_id == '12345'
        assert cinder_job.decision.date == new_date
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_BAN_USER
        assert cinder_job.decision.notes == 'teh notes'
        assert cinder_job.decision.user == target
        assert action_mock.call_count == 1
        assert notify_mock.call_count == 1
        assert list(cinder_job.decision.policies.all()) == [policy]

    def test_process_decision_escalate_addon(self):
        addon = addon_factory()
        cinder_job = CinderJob.objects.create(job_id='1234', target_addon=addon)
        AbuseReport.objects.create(guid=addon.guid, cinder_job=cinder_job)
        assert not cinder_job.resolvable_in_reviewer_tools
        new_date = datetime(2024, 1, 1)
        cinder_job.process_decision(
            decision_cinder_id='12345',
            decision_date=new_date,
            decision_action=DECISION_ACTIONS.AMO_ESCALATE_ADDON,
            decision_notes='blah',
            policy_ids=[],
        )
        assert cinder_job.decision.cinder_id == '12345'
        assert cinder_job.decision.date == new_date
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_ESCALATE_ADDON
        assert cinder_job.decision.notes == 'blah'
        assert cinder_job.decision.addon == addon
        assert cinder_job.resolvable_in_reviewer_tools
        assert cinder_job.target_addon == addon

    def _test_resolve_job(self, activity_action, cinder_action, *, expect_target_email):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        cinder_job = CinderJob.objects.create(
            job_id='999',
            decision=CinderDecision.objects.create(
                addon=addon, action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON
            ),
        )
        flags = version_review_flags_factory(
            version=addon.current_version,
            pending_rejection=self.days_ago(1),
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        # pretend there is a pending rejection that's resolving this job
        cinder_job.pending_rejections.add(flags)
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            cinder_job=cinder_job,
            reporter=user_factory(),
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{cinder_job.job_id}/decision',
            json={'uuid': '123'},
            status=201,
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]

        log_entry = ActivityLog.objects.create(
            activity_action,
            abuse_report.target,
            abuse_report.target.current_version,
            *policies,
            details={
                'comments': 'some review text',
                'cinder_action': cinder_action.constant,
            },
            user=user_factory(),
        )

        cinder_job.resolve_job(log_entry=log_entry)

        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['policy_uuids'] == ['12345678']
        assert request_body['reasoning'] == 'some review text'
        assert 'entity' not in request_body
        cinder_job.reload()
        assert cinder_job.decision.action == cinder_action
        self.assertCloseToNow(cinder_job.decision.date)
        assert list(cinder_job.decision.policies.all()) == policies
        assert len(mail.outbox) == (2 if expect_target_email else 1)
        assert mail.outbox[0].to == [abuse_report.reporter.email]
        assert 'requested the developer' not in mail.outbox[0].body
        if expect_target_email:
            assert mail.outbox[1].to == [addon_developer.email]
            assert str(log_entry.id) in mail.outbox[1].extra_headers['Message-ID']
            assert 'some review text' in mail.outbox[1].body
            assert (
                str(abuse_report.target.current_version.version) in mail.outbox[1].body
            )
            assert 'days' not in mail.outbox[1].body
        assert cinder_job.pending_rejections.count() == 0
        assert not NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        ).exists()
        assert NeedsHumanReview.objects.filter(is_active=True).count() == 2

    def test_resolve_job_notify_owner(self):
        self._test_resolve_job(
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            expect_target_email=True,
        )

    def test_resolve_job_no_email_to_owner(self):
        self._test_resolve_job(
            amo.LOG.CONFIRM_AUTO_APPROVED,
            DECISION_ACTIONS.AMO_APPROVE,
            expect_target_email=False,
        )

    def test_resolve_job_delayed(self):
        cinder_job = CinderJob.objects.create(job_id='999')
        addon_developer = user_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory(users=[addon_developer]).guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            cinder_job=cinder_job,
            reporter=user_factory(),
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{cinder_job.job_id}/decision',
            json={'uuid': '123'},
            status=201,
        )
        log_entry = ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION_DELAYED,
            abuse_report.target,
            abuse_report.target.current_version,
            *policies,
            details={
                'comments': 'some review text',
                'delayed_rejection_days': '14',
                'cinder_action': 'AMO_REJECT_VERSION_WARNING_ADDON',
            },
            user=user_factory(),
        )
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
            version=abuse_report.target.current_version,
        )
        assert abuse_report.target.current_version.due_date

        cinder_job.resolve_job(log_entry=log_entry)

        cinder_job.reload()
        assert cinder_job.decision.action == (
            DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON
        )
        self.assertCloseToNow(cinder_job.decision.date)
        assert list(cinder_job.decision.policies.all()) == policies
        assert set(cinder_job.pending_rejections.all()) == set(
            VersionReviewerFlags.objects.filter(
                version=abuse_report.target.current_version
            )
        )
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [abuse_report.reporter.email]
        assert 'requested the developer' in mail.outbox[0].body
        assert mail.outbox[1].to == [addon_developer.email]
        assert str(log_entry.id) in mail.outbox[1].extra_headers['Message-ID']
        assert 'some review text' in mail.outbox[1].body
        assert str(abuse_report.target.current_version.version) in mail.outbox[1].body
        assert '14 day(s)' in mail.outbox[1].body
        assert not NeedsHumanReview.objects.filter(is_active=True).exists()
        abuse_report.target.current_version.reload()
        assert not abuse_report.target.current_version.due_date

    def test_resolve_job_appeal_not_third_party(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        appeal_job = CinderJob.objects.create(
            job_id='999',
        )
        CinderJob.objects.create(
            job_id='998',
            decision=CinderDecision.objects.create(
                addon=addon, action=DECISION_ACTIONS.AMO_APPROVE, appeal_job=appeal_job
            ),
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{appeal_job.job_id}/decision',
            json={'uuid': '123'},
            status=201,
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]
        log_entry = ActivityLog.objects.create(
            amo.LOG.FORCE_DISABLE,
            addon,
            addon.current_version,
            *policies,
            details={
                'comments': 'some review text',
                'cinder_action': 'AMO_DISABLE_ADDON',
            },
            user=user_factory(),
        )

        appeal_job.resolve_job(log_entry=log_entry)

        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['policy_uuids'] == ['12345678']
        assert request_body['reasoning'] == 'some review text'
        assert 'entity' not in request_body
        appeal_job.reload()
        assert appeal_job.decision.action == DECISION_ACTIONS.AMO_DISABLE_ADDON
        self.assertCloseToNow(appeal_job.decision.date)
        assert list(appeal_job.decision.policies.all()) == policies
        assert len(mail.outbox) == 1

        assert mail.outbox[0].to == [addon_developer.email]
        assert str(log_entry.id) in mail.outbox[0].extra_headers['Message-ID']
        assert 'some review text' in mail.outbox[0].body
        assert 'days' not in mail.outbox[0].body
        assert 'in an assessment performed on our own initiative' in mail.outbox[0].body
        assert appeal_job.pending_rejections.count() == 0
        assert not NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL
        ).exists()
        assert NeedsHumanReview.objects.filter(is_active=True).count() == 2

    def test_resolve_job_appeal_with_new_report(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        appeal_job = CinderJob.objects.create(
            job_id='999',
        )
        AbuseReport.objects.create(
            reporter_email='reporter@email.com', cinder_job=appeal_job, guid=addon.guid
        )
        CinderJob.objects.create(
            job_id='998',
            decision=CinderDecision.objects.create(
                addon=addon, action=DECISION_ACTIONS.AMO_APPROVE, appeal_job=appeal_job
            ),
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{appeal_job.job_id}/decision',
            json={'uuid': '123'},
            status=201,
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]
        log_entry = ActivityLog.objects.create(
            amo.LOG.FORCE_DISABLE,
            addon,
            addon.current_version,
            *policies,
            details={
                'comments': 'some review text',
                'cinder_action': 'AMO_DISABLE_ADDON',
            },
            user=user_factory(),
        )

        appeal_job.resolve_job(log_entry=log_entry)

        appeal_job.reload()
        assert appeal_job.decision.action == DECISION_ACTIONS.AMO_DISABLE_ADDON
        assert len(mail.outbox) == 2

        assert mail.outbox[1].to == [addon_developer.email]
        assert str(log_entry.id) in mail.outbox[1].extra_headers['Message-ID']
        assert 'assessment performed on our own initiative' not in mail.outbox[1].body
        assert mail.outbox[0].to == ['reporter@email.com']
        assert not NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL
        ).exists()
        assert not NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        ).exists()
        assert NeedsHumanReview.objects.filter(is_active=True).count() == 1

    def test_resolve_job_escalation(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        cinder_job = CinderJob.objects.create(
            job_id='999',
            decision=CinderDecision.objects.create(
                addon=addon, action=DECISION_ACTIONS.AMO_ESCALATE_ADDON
            ),
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            cinder_job=cinder_job,
            reporter=user_factory(),
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{cinder_job.job_id}/decision',
            json={'uuid': '123'},
            status=201,
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]

        log_entry = ActivityLog.objects.create(
            amo.LOG.FORCE_DISABLE,
            abuse_report.target,
            abuse_report.target.current_version,
            *policies,
            details={
                'comments': 'some review text',
                'cinder_action': 'AMO_DISABLE_ADDON',
            },
            user=user_factory(),
        )

        cinder_job.resolve_job(log_entry=log_entry)

        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['policy_uuids'] == ['12345678']
        assert request_body['reasoning'] == 'some review text'
        assert 'entity' not in request_body
        cinder_job.reload()
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_DISABLE_ADDON
        self.assertCloseToNow(cinder_job.decision.date)
        assert list(cinder_job.decision.policies.all()) == policies
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [abuse_report.reporter.email]
        assert 'requested the developer' not in mail.outbox[0].body
        assert mail.outbox[1].to == [addon_developer.email]
        assert str(log_entry.id) in mail.outbox[1].extra_headers['Message-ID']
        assert 'some review text' in mail.outbox[1].body
        assert not NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.CINDER_ESCALATION
        ).exists()
        assert NeedsHumanReview.objects.filter(is_active=True).count() == 2

    def test_abuse_reports(self):
        job = CinderJob.objects.create(job_id='fake_job_id')
        assert list(job.all_abuse_reports) == []

        addon = addon_factory()
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)
        assert list(job.all_abuse_reports) == [report]

        report2 = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)
        assert list(job.all_abuse_reports) == [report, report2]

        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        job.update(
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                addon=addon,
                appeal_job=appeal_job,
            )
        )

        assert appeal_job.all_abuse_reports == [report, report2]
        assert list(job.all_abuse_reports) == [report, report2]

        appeal_appeal_job = CinderJob.objects.create(job_id='fake_appeal_appeal_job_id')
        appeal_job.update(
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                addon=addon,
                appeal_job=appeal_appeal_job,
            )
        )

        assert list(appeal_appeal_job.all_abuse_reports) == [report, report2]
        assert list(appeal_job.all_abuse_reports) == [report, report2]
        assert list(job.all_abuse_reports) == [report, report2]

        report3 = AbuseReport.objects.create(guid=addon.guid, cinder_job=appeal_job)
        report4 = AbuseReport.objects.create(
            guid=addon.guid, cinder_job=appeal_appeal_job
        )
        assert list(appeal_appeal_job.all_abuse_reports) == [
            report,
            report2,
            report3,
            report4,
        ]
        assert list(appeal_job.all_abuse_reports) == [report, report2, report3]
        assert list(job.all_abuse_reports) == [report, report2]

    def test_is_appeal(self):
        job = CinderJob.objects.create(job_id='fake_job_id')
        assert not job.is_appeal

        appeal = CinderJob.objects.create(job_id='an appeal job')
        job.update(
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                addon=addon_factory(),
                appeal_job=appeal,
            )
        )
        job.reload()
        assert not job.is_appeal
        assert appeal.is_appeal


class TestCinderDecisionCanBeAppealed(TestCase):
    def setUp(self):
        self.reporter = user_factory()
        self.author = user_factory()
        self.addon = addon_factory(users=[self.author])
        self.decision = CinderDecision.objects.create(
            cinder_id='fake_decision_id',
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=self.addon,
        )

    def test_appealed_decision_already_made(self):
        assert not self.decision.appealed_decision_already_made()

        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
        )
        self.decision.update(appeal_job=appeal_job)
        assert not self.decision.appealed_decision_already_made()

        appeal_job.update(
            decision=CinderDecision.objects.create(
                cinder_id='appeal decision id',
                addon=self.addon,
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            )
        )
        assert self.decision.appealed_decision_already_made()

    def test_reporter_can_appeal_approve_decision(self):
        initial_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )

    def test_reporter_cant_appeal_approve_decision_if_abuse_report_is_not_passed(self):
        AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert not self.decision.can_be_appealed(is_reporter=True)

    def test_reporter_cant_appeal_non_approve_decision(self):
        initial_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )
        for decision_action in (
            action
            for action, _ in DECISION_ACTIONS
            if action not in DECISION_ACTIONS.APPROVING
        ):
            self.decision.update(
                action=decision_action,
                addon=self.addon,
            )
            assert not self.decision.can_be_appealed(
                is_reporter=True, abuse_report=initial_report
            )

    def test_reporter_cant_appeal_approve_decision_already_appealed(self):
        initial_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
        )
        self.decision.update(appeal_job=appeal_job)
        initial_report.update(
            reporter_appeal_date=datetime.now(), appellant_job=appeal_job
        )
        assert not self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )

    def test_reporter_can_appeal_approve_decision_already_appealed_someone_else(self):
        initial_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
        )
        self.decision.update(appeal_job=appeal_job)
        AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=initial_report.cinder_job,
            reporter=user_factory(),
            reporter_appeal_date=datetime.now(),
            appellant_job=appeal_job,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )

    def test_reporter_cant_appeal_approve_decision_already_appealed_and_decided(self):
        initial_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
            decision=CinderDecision.objects.create(
                cinder_id='fake_appeal_decision_id',
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=self.addon,
            ),
        )
        self.decision.update(appeal_job=appeal_job)
        AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=initial_report.cinder_job,
            appellant_job=appeal_job,
            reporter=user_factory(),
            reporter_appeal_date=datetime.now(),
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert not self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )

    def test_reporter_can_appeal_appealed_decision(self):
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
            decision=CinderDecision.objects.create(
                cinder_id='fake_appeal_decision_id',
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=self.addon,
            ),
        )
        AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_appeal_date=datetime.now(),
            appellant_job=appeal_job,
        )
        self.decision.update(appeal_job=appeal_job)
        # We can end up in this situation where an AbuseReport is tied
        # to a CinderJob from an appeal, and if that somehow happens we want to
        # make sure it's ossible for a reporter to appeal an appeal.
        new_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=appeal_job,
            reporter=user_factory(),
            reporter_appeal_date=datetime.now(),
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert appeal_job.decision.can_be_appealed(
            is_reporter=True, abuse_report=new_report
        )

    def test_reporter_cant_appeal_past_expiration_delay(self):
        initial_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )
        self.decision.update(date=self.days_ago(APPEAL_EXPIRATION_DAYS + 1))
        assert not self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )

    def test_author_can_appeal_disable_decision(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        assert self.decision.can_be_appealed(is_reporter=False)

    def test_author_can_appeal_delete_decision_rating(self):
        rating = Rating.objects.create(
            addon=self.addon, user=self.author, rating=1, body='blah'
        )
        self.decision.update(
            action=DECISION_ACTIONS.AMO_DELETE_RATING, addon=None, rating=rating
        )
        self.decision.can_be_appealed(is_reporter=False)

    def test_author_can_appeal_delete_decision_collection(self):
        collection = collection_factory(author=self.author)
        self.decision.update(
            action=DECISION_ACTIONS.AMO_DELETE_COLLECTION,
            addon=None,
            collection=collection,
        )
        self.decision.can_be_appealed(is_reporter=False)

    def test_author_can_appeal_ban_user(self):
        self.decision.update(
            action=DECISION_ACTIONS.AMO_BAN_USER, addon=None, user=self.author
        )
        self.decision.can_be_appealed(is_reporter=False)

    def test_author_cant_appeal_approve_or_escalation_decision(self):
        for decision_action in (
            DECISION_ACTIONS.AMO_ESCALATE_ADDON,
            DECISION_ACTIONS.AMO_APPROVE,
        ):
            self.decision.update(action=decision_action)
            assert not self.decision.can_be_appealed(is_reporter=False)

    def test_author_cant_appeal_disable_decision_already_appealed(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        assert self.decision.can_be_appealed(is_reporter=False)
        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        self.decision.update(appeal_job=appeal_job)
        assert not self.decision.can_be_appealed(is_reporter=False)

    def test_author_can_appeal_appealed_decision(self):
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
            decision=CinderDecision.objects.create(
                cinder_id='fake_appeal_decision_id',
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                addon=self.addon,
            ),
        )
        self.decision.update(appeal_job=appeal_job)
        assert appeal_job.decision.can_be_appealed(is_reporter=False)


class TestCinderPolicy(TestCase):
    def test_create_cinder_policy_with_required_fields(self):
        policy = CinderPolicy.objects.create(
            name='Test Policy',
            text='Test Policy Description',
            uuid='test-uuid',
        )
        self.assertEqual(policy.name, 'Test Policy')
        self.assertEqual(policy.text, 'Test Policy Description')
        self.assertEqual(policy.uuid, 'test-uuid')

    def test_create_cinder_policy_with_child_policy(self):
        parent_policy = CinderPolicy.objects.create(
            name='Parent Policy',
            text='Parent Policy Description',
            uuid='parent-uuid',
        )
        child_policy = CinderPolicy.objects.create(
            name='Child Policy',
            text='Child Policy Description',
            uuid='child-uuid',
            parent=parent_policy,
        )
        self.assertEqual(child_policy.name, 'Child Policy')
        self.assertEqual(child_policy.text, 'Child Policy Description')
        self.assertEqual(child_policy.uuid, 'child-uuid')
        self.assertEqual(child_policy.parent, parent_policy)

    def test_create_cinder_policy_with_duplicate_uuid(self):
        existing_policy = CinderPolicy.objects.create(
            name='Policy 1',
            text='Policy 1 Description',
            uuid='duplicate-uuid',
        )
        with pytest.raises(IntegrityError):
            CinderPolicy.objects.create(
                name='Policy 2',
                text='Policy 2 Description',
                uuid=existing_policy.uuid,
            )

    def test_str(self):
        parent_policy = CinderPolicy.objects.create(
            name='Parent Policy',
            text='Parent Policy Description',
            uuid='parent-uuid',
        )
        child_policy = CinderPolicy.objects.create(
            name='Child Policy',
            text='Child Policy Description',
            uuid='child-uuid',
            parent=parent_policy,
        )
        assert str(parent_policy) == 'Parent Policy'
        assert str(child_policy) == 'Parent Policy, specifically Child Policy'

    def test_full_text(self):
        parent_policy = CinderPolicy.objects.create(
            name='Parent Policy',
            text='Parent Policy Description',
            uuid='parent-uuid',
        )
        child_policy = CinderPolicy.objects.create(
            name='Child Policy',
            text='Child Policy Description',
            uuid='child-uuid',
            parent=parent_policy,
        )
        assert parent_policy.full_text('') == 'Parent Policy'
        assert parent_policy.full_text() == 'Parent Policy: Parent Policy Description'
        assert (
            parent_policy.full_text('Some Canned Response')
            == 'Parent Policy: Some Canned Response'
        )
        assert child_policy.full_text('') == 'Parent Policy, specifically Child Policy'
        assert (
            child_policy.full_text()
            == 'Parent Policy, specifically Child Policy: Child Policy Description'
        )
        assert (
            child_policy.full_text('Some Canned Response')
            == 'Parent Policy, specifically Child Policy: Some Canned Response'
        )

    def test_without_parents_if_their_children_are_present(self):
        parent_policy = CinderPolicy.objects.create(
            name='Parent of Policy 1',
            text='Policy Parent 1 Description',
            uuid='some-parent-uuid',
        )
        child_policy = CinderPolicy.objects.create(
            name='Policy 1',
            text='Policy 1 Description',
            uuid='some-child-uuid',
            parent=parent_policy,
        )
        lone_policy = CinderPolicy.objects.create(
            name='Policy 2',
            text='Policy 2 Description',
            uuid='some-uuid',
        )
        qs = CinderPolicy.objects.all()
        assert set(qs) == {parent_policy, child_policy, lone_policy}
        assert isinstance(qs.without_parents_if_their_children_are_present(), list)
        assert set(qs.without_parents_if_their_children_are_present()) == {
            child_policy,
            lone_policy,
        }
        assert set(
            qs.exclude(
                pk=child_policy.pk
            ).without_parents_if_their_children_are_present()
        ) == {
            parent_policy,
            lone_policy,
        }


class TestCinderDecision(TestCase):
    def test_get_reference_id(self):
        decision = CinderDecision()
        assert decision.get_reference_id() == 'NoClass#None'
        assert decision.get_reference_id(short=False) == 'Decision "" for NoClass #None'

        decision.addon = addon_factory()
        assert decision.get_reference_id() == f'Addon#{decision.addon.id}'
        assert (
            decision.get_reference_id(short=False)
            == f'Decision "" for Addon #{decision.addon.id}'
        )

        decision.cinder_id = '1234'
        assert decision.get_reference_id() == '1234'
        assert (
            decision.get_reference_id(short=False)
            == f'Decision "1234" for Addon #{decision.addon.id}'
        )

    def test_target(self):
        addon = addon_factory(guid='@lol')
        decision = CinderDecision.objects.create(
            action=DECISION_ACTIONS.AMO_APPROVE, addon=addon
        )
        assert decision.target == addon

        user = user_factory()
        decision.update(addon=None, user=user)
        assert decision.target == user

        rating = Rating.objects.create(user=user, addon=addon, rating=5)
        decision.update(user=None, rating=rating)
        assert decision.target == rating

        collection = collection_factory()
        decision.update(rating=None, collection=collection)
        assert decision.target == collection

    def test_is_third_party_initiated(self):
        addon = addon_factory()
        current_decision = CinderDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon
        )
        assert not current_decision.is_third_party_initiated

        current_job = CinderJob.objects.create(decision=current_decision, job_id='123')
        current_decision.refresh_from_db()
        assert not current_decision.is_third_party_initiated

        AbuseReport.objects.create(guid=addon.guid, cinder_job=current_job)
        current_decision.refresh_from_db()
        assert current_decision.is_third_party_initiated

    def test_is_third_party_initiated_appeal(self):
        addon = addon_factory()
        current_decision = CinderDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
        )
        current_job = CinderJob.objects.create(decision=current_decision, job_id='123')
        original_job = CinderJob.objects.create(
            job_id='456',
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE, addon=addon, appeal_job=current_job
            ),
        )
        assert not current_decision.is_third_party_initiated

        AbuseReport.objects.create(guid=addon.guid, cinder_job=original_job)
        assert current_decision.is_third_party_initiated

    def test_get_action_helper(self):
        addon = addon_factory()
        decision = CinderDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon
        )
        targets = {
            CinderActionBanUser: {'user': user_factory()},
            CinderActionDisableAddon: {'addon': addon},
            CinderActionRejectVersion: {'addon': addon},
            CinderActionRejectVersionDelayed: {'addon': addon},
            CinderActionEscalateAddon: {'addon': addon},
            CinderActionDeleteCollection: {'collection': collection_factory()},
            CinderActionDeleteRating: {
                'rating': Rating.objects.create(addon=addon, user=user_factory())
            },
            CinderActionApproveInitialDecision: {'addon': addon},
            CinderActionApproveNoAction: {'addon': addon},
            CinderActionOverrideApprove: {'addon': addon},
            CinderActionTargetAppealApprove: {'addon': addon},
            CinderActionTargetAppealRemovalAffirmation: {'addon': addon},
            CinderActionIgnore: {'addon': addon},
        }
        action_to_class = [
            (decision_action, CinderDecision.get_action_helper_class(decision_action))
            for decision_action in DECISION_ACTIONS.values
        ]
        # base cases, where it's a decision without an override or appeal involved
        action_existing_to_class = {
            (new_action, None, None): ActionClass
            for new_action, ActionClass in action_to_class
        }

        for action in DECISION_ACTIONS.REMOVING.values:
            # add appeal success cases
            action_existing_to_class[(DECISION_ACTIONS.AMO_APPROVE, None, action)] = (
                CinderActionTargetAppealApprove
            )
            action_existing_to_class[
                (DECISION_ACTIONS.AMO_APPROVE_VERSION, None, action)
            ] = CinderActionTargetAppealApprove
            # add appeal denial cases
            action_existing_to_class[(action, None, action)] = (
                CinderActionTargetAppealRemovalAffirmation
            )
            # add override from takedown to approve cases
            action_existing_to_class[(DECISION_ACTIONS.AMO_APPROVE, action, None)] = (
                CinderActionOverrideApprove
            )
            action_existing_to_class[
                (DECISION_ACTIONS.AMO_APPROVE_VERSION, action, None)
            ] = CinderActionOverrideApprove

        for (
            new_action,
            overridden_action,
            appealed_action,
        ), ActionClass in action_existing_to_class.items():
            decision.update(
                **{
                    'action': new_action,
                    'addon': None,
                    'rating': None,
                    'collection': None,
                    'user': None,
                    **targets[ActionClass],
                }
            )
            helper = decision.get_action_helper(
                appealed_action=appealed_action, overriden_action=overridden_action
            )
            assert helper.__class__ == ActionClass
            assert helper.decision == decision
            assert helper.reporter_template_path == ActionClass.reporter_template_path
            assert (
                helper.reporter_appeal_template_path
                == ActionClass.reporter_appeal_template_path
            )

        action_existing_to_class_no_reporter_emails = {
            (action, action): CinderDecision.get_action_helper_class(action)
            for action in DECISION_ACTIONS.REMOVING.values
        }
        for (
            new_action,
            overridden_action,
        ), ActionClass in action_existing_to_class_no_reporter_emails.items():
            decision.update(
                **{
                    'action': new_action,
                    'addon': None,
                    'rating': None,
                    'collection': None,
                    'user': None,
                    **targets[ActionClass],
                }
            )
            helper = decision.get_action_helper(
                appealed_action=None, overriden_action=overridden_action
            )
            assert helper.reporter_template_path is None
            assert helper.reporter_appeal_template_path is None
            assert ActionClass.reporter_template_path is not None
            assert ActionClass.reporter_appeal_template_path is not None

    def _test_appeal_as_target(self, *, resolvable_in_reviewer_tools):
        user_factory(id=settings.TASK_USER_ID)
        addon = addon_factory(
            status=amo.STATUS_DISABLED,
            file_kw={'is_signed': True, 'status': amo.STATUS_DISABLED},
        )
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            cinder_job=CinderJob.objects.create(
                target_addon=addon,
                resolvable_in_reviewer_tools=resolvable_in_reviewer_tools,
                decision=CinderDecision.objects.create(
                    cinder_id='4815162342-lost',
                    date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                    addon=addon,
                ),
            ),
        )
        assert not abuse_report.reporter_appeal_date
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )

        abuse_report.cinder_job.decision.appeal(
            abuse_report=abuse_report,
            appeal_text='appeal text',
            user=user_factory(),
            is_reporter=False,
        )

        abuse_report.cinder_job.reload()
        assert abuse_report.cinder_job.decision.appeal_job_id
        assert abuse_report.cinder_job.decision.appeal_job.job_id == '2432615184-tsol'
        assert abuse_report.cinder_job.decision.appeal_job.target_addon == addon
        abuse_report.reload()
        assert not abuse_report.reporter_appeal_date
        assert not abuse_report.appellant_job
        return abuse_report.cinder_job.decision.appeal_job.reload()

    def test_appeal_as_target_from_resolved_in_cinder(self):
        appeal_job = self._test_appeal_as_target(resolvable_in_reviewer_tools=False)
        assert not appeal_job.resolvable_in_reviewer_tools
        assert not NeedsHumanReview.objects.all().exists()

    def test_appeal_as_target_from_resolved_in_amo(self):
        appeal_job = self._test_appeal_as_target(resolvable_in_reviewer_tools=True)
        assert appeal_job.resolvable_in_reviewer_tools
        assert NeedsHumanReview.objects.all().exists()
        addon = Addon.unfiltered.get()
        assert addon in Addon.unfiltered.get_queryset_for_pending_queues()

    def test_appeal_as_target_improperly_configured(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            cinder_job=CinderJob.objects.create(
                decision=CinderDecision.objects.create(
                    cinder_id='4815162342-lost',
                    date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                    addon=addon,
                ),
                target_addon=addon,
            ),
        )
        assert not abuse_report.reporter_appeal_date
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )

        with self.assertRaises(ImproperlyConfigured):
            abuse_report.cinder_job.decision.appeal(
                abuse_report=abuse_report,
                appeal_text='appeal text',
                # Can't pass user=None for a target appeal, unless it's
                # specifically a user ban (see test_appeal_as_target_banned()).
                user=None,
                is_reporter=False,
            )

        abuse_report.cinder_job.reload()
        assert not abuse_report.cinder_job.decision.appeal_job_id
        abuse_report.reload()
        assert not abuse_report.reporter_appeal_date
        assert not abuse_report.appellant_job

    def test_appeal_as_target_ban_improperly_configured(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            cinder_job=CinderJob.objects.create(
                decision=CinderDecision.objects.create(
                    cinder_id='4815162342-lost',
                    date=self.days_ago(179),
                    # This (target is an add-on, decision is a user ban) shouldn't
                    # be possible but we want to make sure this is handled
                    # explicitly.
                    action=DECISION_ACTIONS.AMO_BAN_USER,
                    addon=addon,
                ),
                target_addon=addon,
            ),
        )
        assert not abuse_report.reporter_appeal_date
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )

        with self.assertRaises(ImproperlyConfigured):
            abuse_report.cinder_job.decision.appeal(
                abuse_report=abuse_report,
                appeal_text='appeal text',
                # user=None is allowed here since the original decision was a
                # ban, the target user can no longer log in but should be
                # allowed to appeal. In this instance though, the target of the
                # abuse report was not a user so this shouldn't be possible and
                # we should raise an error.
                user=None,
                is_reporter=False,
            )

        abuse_report.cinder_job.reload()
        assert not abuse_report.cinder_job.decision.appeal_job_id
        abuse_report.reload()
        assert not abuse_report.reporter_appeal_date
        assert not abuse_report.appellant_job

    def test_appeal_as_target_banned(self):
        target = user_factory()
        abuse_report = AbuseReport.objects.create(
            user=target,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            cinder_job=CinderJob.objects.create(
                decision=CinderDecision.objects.create(
                    cinder_id='4815162342-lost',
                    date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_BAN_USER,
                    user=target,
                )
            ),
        )
        assert not abuse_report.reporter_appeal_date
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )

        abuse_report.cinder_job.decision.appeal(
            abuse_report=abuse_report,
            appeal_text='appeal text',
            # user=None is allowed here since the original decision was a ban,
            # the target user can no longer log in but should be allowed to
            # appeal.
            user=None,
            is_reporter=False,
        )

        abuse_report.cinder_job.reload()
        assert abuse_report.cinder_job.decision.appeal_job_id
        assert abuse_report.cinder_job.decision.appeal_job.job_id == '2432615184-tsol'
        abuse_report.reload()
        assert not abuse_report.reporter_appeal_date
        assert not abuse_report.appellant_job

    def test_appeal_as_reporter(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
        )
        abuse_report.update(
            cinder_job=CinderJob.objects.create(
                target_addon=addon,
                decision=CinderDecision.objects.create(
                    cinder_id='4815162342-lost',
                    date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_APPROVE,
                    addon=addon,
                ),
            )
        )
        assert not abuse_report.reporter_appeal_date
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )

        abuse_report.cinder_job.decision.appeal(
            abuse_report=abuse_report,
            appeal_text='appeal text',
            user=abuse_report.reporter,
            is_reporter=True,
        )

        abuse_report.cinder_job.reload()
        assert abuse_report.cinder_job.decision.appeal_job
        assert abuse_report.cinder_job.decision.appeal_job.job_id == '2432615184-tsol'
        assert abuse_report.cinder_job.decision.appeal_job.target_addon == addon
        abuse_report.reload()
        assert abuse_report.appellant_job.job_id == '2432615184-tsol'
        assert abuse_report.reporter_appeal_date

    def test_appeal_as_reporter_already_appealed(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
        )
        abuse_report.update(
            cinder_job=CinderJob.objects.create(
                target_addon=addon,
                decision=CinderDecision.objects.create(
                    cinder_id='4815162342-lost',
                    date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_APPROVE,
                    addon=addon,
                ),
            )
        )
        # Pretend there was already an appeal job from a different reporter.
        # Make that resolvable in reviewer tools as if it had been escalated,
        # to ensure the get_or_create() call that we make can't trigger an
        # IntegrityError because of the additional parameters (job_id must
        # be the only field we use to retrieve the job).
        abuse_report.cinder_job.decision.update(
            appeal_job=CinderJob.objects.create(
                job_id='2432615184-tsol',
                target_addon=addon,
                resolvable_in_reviewer_tools=True,
            )
        )
        assert not abuse_report.reporter_appeal_date
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )

        abuse_report.cinder_job.decision.appeal(
            abuse_report=abuse_report,
            appeal_text='appeal text',
            user=abuse_report.reporter,
            is_reporter=True,
        )

        abuse_report.cinder_job.reload()
        assert abuse_report.cinder_job.decision.appeal_job
        assert abuse_report.cinder_job.decision.appeal_job.job_id == '2432615184-tsol'
        assert abuse_report.cinder_job.decision.appeal_job.target_addon == addon
        abuse_report.reload()
        assert abuse_report.appellant_job.job_id == '2432615184-tsol'
        assert abuse_report.reporter_appeal_date

    def test_appeal_improperly_configured_reporter(self):
        cinder_job = CinderJob.objects.create(
            decision=CinderDecision.objects.create(
                cinder_id='4815162342-lost',
                date=self.days_ago(179),
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=addon_factory(),
            )
        )
        with self.assertRaises(ImproperlyConfigured):
            cinder_job.decision.appeal(
                abuse_report=None,
                appeal_text='No abuse_report but is_reporter is True',
                user=user_factory(),
                is_reporter=True,
            )

    def test_appeal_improperly_configured_author(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
        )
        cinder_job = CinderJob.objects.create(
            decision=CinderDecision.objects.create(
                cinder_id='4815162342-lost',
                date=self.days_ago(179),
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=addon,
            )
        )
        with self.assertRaises(ImproperlyConfigured):
            cinder_job.decision.appeal(
                abuse_report=abuse_report,
                appeal_text='No user but is_reporter is False',
                user=None,
                is_reporter=False,
            )

    def _test_notify_reviewer_decision(
        self,
        decision,
        activity_action,
        cinder_action,
        *,
        expect_email=True,
        expect_create_decision_call=True,
        expect_create_job_decision_call=False,
        extra_log_details=None,
    ):
        create_decision_response = responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': '123'},
            status=201,
        )
        cinder_job_id = (job := getattr(decision, 'cinder_job', None)) and job.job_id
        create_job_decision_response = responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{cinder_job_id}/decision',
            json={'uuid': '123'},
            status=201,
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]
        entity_helper = CinderJob.get_entity_helper(
            decision.addon, resolved_in_reviewer_tools=True
        )
        addon_version = decision.addon.versions.all()[0]
        log_entry = ActivityLog.objects.create(
            activity_action,
            decision.addon,
            addon_version,
            *policies,
            details={
                'comments': 'some review text',
                'cinder_action': cinder_action.constant,
                **(extra_log_details or {}),
            },
            user=user_factory(),
        )

        decision.notify_reviewer_decision(
            log_entry=log_entry,
            entity_helper=entity_helper,
        )

        assert decision.action == cinder_action
        if expect_create_decision_call:
            assert create_decision_response.call_count == 1
            assert create_job_decision_response.call_count == 0
            request = responses.calls[0].request
            request_body = json.loads(request.body)
            assert request_body['policy_uuids'] == ['12345678']
            assert request_body['reasoning'] == 'some review text'
            assert request_body['entity']['id'] == str(decision.addon.id)
            assert request_body['enforcement_actions_slugs'] == [
                cinder_action.api_value
            ]
            self.assertCloseToNow(decision.date)
            assert list(decision.policies.all()) == policies
            assert CinderDecision.objects.count() == 1
            assert decision.id
        elif expect_create_job_decision_call:
            assert create_decision_response.call_count == 0
            assert create_job_decision_response.call_count == 1
            request = responses.calls[0].request
            request_body = json.loads(request.body)
            assert request_body['policy_uuids'] == ['12345678']
            assert request_body['reasoning'] == 'some review text'
            assert 'entity' not in request_body
            assert request_body['enforcement_actions_slugs'] == [
                cinder_action.api_value
            ]
            self.assertCloseToNow(decision.date)
            assert list(decision.policies.all()) == policies
            assert CinderDecision.objects.count() == 1
            assert decision.id
        else:
            assert create_decision_response.call_count == 0
            assert create_job_decision_response.call_count == 0
            assert CinderPolicy.cinderdecision_set.through.objects.count() == 0
            assert not decision.id
        if expect_email:
            assert len(mail.outbox) == 1
            assert mail.outbox[0].to == [decision.addon.authors.first().email]
            assert str(log_entry.id) in mail.outbox[0].extra_headers['Message-ID']
            assert str(addon_version) in mail.outbox[0].body
            assert 'days' not in mail.outbox[0].body
        else:
            assert len(mail.outbox) == 0

    def test_notify_reviewer_decision_new_decision(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = CinderDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision, amo.LOG.REJECT_VERSION, DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON
        )
        assert parse.quote(f'/firefox/addon/{addon.slug}/') in mail.outbox[0].body
        assert '/developers/' not in mail.outbox[0].body

    def test_notify_reviewer_decision_updated_decision(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = CinderDecision.objects.create(
            addon=addon, action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON
        )
        self._test_notify_reviewer_decision(
            decision, amo.LOG.REJECT_VERSION, DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON
        )
        assert parse.quote(f'/firefox/addon/{addon.slug}/') in mail.outbox[0].body
        assert '/developers/' not in mail.outbox[0].body

    def test_notify_reviewer_decision_unlisted_version(self):
        addon_developer = user_factory()
        addon = addon_factory(
            users=[addon_developer], version_kw={'channel': amo.CHANNEL_UNLISTED}
        )
        decision = CinderDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision, amo.LOG.REJECT_VERSION, DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON
        )
        assert '/firefox/' not in mail.outbox[0].body
        assert (
            f'{settings.SITE_URL}/en-US/developers/addon/{addon.id}/'
            in mail.outbox[0].body
        )

    def test_notify_reviewer_decision_new_decision_no_email_to_owner(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = CinderDecision(addon=addon)
        decision.cinder_job = CinderJob.objects.create(job_id='1234')
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.CONFIRM_AUTO_APPROVED,
            DECISION_ACTIONS.AMO_APPROVE,
            expect_email=False,
            expect_create_decision_call=False,
            expect_create_job_decision_call=True,
        )

    def test_notify_reviewer_decision_updated_decision_no_email_to_owner(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = CinderDecision.objects.create(
            addon=addon, action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON
        )
        decision.cinder_job = CinderJob.objects.create(job_id='1234')
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.CONFIRM_AUTO_APPROVED,
            DECISION_ACTIONS.AMO_APPROVE,
            expect_email=False,
            expect_create_decision_call=False,
            expect_create_job_decision_call=True,
        )

    def test_no_create_decision_for_approve_without_a_job(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = CinderDecision(addon=addon)
        assert not hasattr(decision, 'cinder_job')
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.APPROVE_VERSION,
            DECISION_ACTIONS.AMO_APPROVE_VERSION,
            expect_create_decision_call=False,
            expect_email=True,
        )

    def test_notify_reviewer_decision_auto_approve_email_for_non_human_review(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = CinderDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.APPROVE_VERSION,
            DECISION_ACTIONS.AMO_APPROVE_VERSION,
            expect_email=True,
            expect_create_decision_call=False,
            extra_log_details={'human_review': False},
        )
        assert 'automatically screened and tentatively approved' in mail.outbox[0].body

    def test_notify_reviewer_decision_auto_approve_email_for_human_review(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = CinderDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.APPROVE_VERSION,
            DECISION_ACTIONS.AMO_APPROVE_VERSION,
            expect_email=True,
            expect_create_decision_call=False,
            extra_log_details={'human_review': True},
        )
        assert 'has been approved' in mail.outbox[0].body

    def test_notify_reviewer_decision_no_cinder_action_in_activity_log(self):
        addon = addon_factory()
        log_entry = ActivityLog.objects.create(
            amo.LOG.APPROVE_VERSION,
            addon,
            addon.current_version,
            details={'comments': 'some review text'},
            user=user_factory(),
        )

        with self.assertRaises(ImproperlyConfigured):
            CinderDecision().notify_reviewer_decision(
                log_entry=log_entry, entity_helper=None
            )

    def test_notify_reviewer_decision_invalid_cinder_action_in_activity_log(self):
        addon = addon_factory()
        log_entry = ActivityLog.objects.create(
            amo.LOG.APPROVE_VERSION,
            addon,
            addon.current_version,
            details={'comments': 'some review text', 'cinder_action': 'NOT_AN_ACTION'},
            user=user_factory(),
        )

        with self.assertRaises(ImproperlyConfigured):
            CinderDecision().notify_reviewer_decision(
                log_entry=log_entry, entity_helper=None
            )

    def test_notify_reviewer_decision_rejection_blocking(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = CinderDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            extra_log_details={
                'is_addon_being_blocked': True,
                'is_addon_being_disabled': False,
            },
        )
        assert (
            'Users who have previously installed those versions will be able to'
            not in mail.outbox[0].body
        )
        assert (
            'users who have previously installed those versions won’t be able to'
            in mail.outbox[0].body
        )
        assert (
            'You may upload a new version which addresses the policy violation(s)'
            in mail.outbox[0].body
        )

    def test_notify_reviewer_decision_rejection_blocking_addon_being_disabled(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = CinderDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            extra_log_details={
                'is_addon_being_blocked': True,
                'is_addon_being_disabled': True,
            },
        )
        assert (
            'Users who have previously installed those versions will be able to'
            not in mail.outbox[0].body
        )
        assert (
            'users who have previously installed those versions won’t be able to'
            in mail.outbox[0].body
        )
        assert (
            'You may upload a new version which addresses the policy violation(s)'
            not in mail.outbox[0].body
        )

    def test_notify_reviewer_decision_rejection_addon_already_disabled(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer], status=amo.STATUS_DISABLED)
        decision = CinderDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
        )
        assert (
            'Users who have previously installed those versions will be able to'
            in mail.outbox[0].body
        )
        assert (
            'users who have previously installed those versions won’t be able to'
            not in mail.outbox[0].body
        )
        assert (
            'You may upload a new version which addresses the policy violation(s)'
            not in mail.outbox[0].body
        )
