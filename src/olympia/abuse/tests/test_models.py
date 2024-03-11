import json
from datetime import datetime
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db.utils import IntegrityError

import pytest
import responses

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, addon_factory, collection_factory, user_factory
from olympia.constants.abuse import APPEAL_EXPIRATION_DAYS, DECISION_ACTIONS
from olympia.ratings.models import Rating
from olympia.reviewers.models import ReviewActionReason

from ..cinder import (
    CinderAddon,
    CinderAddonHandledByReviewers,
    CinderCollection,
    CinderRating,
    CinderUnauthenticatedReporter,
    CinderUser,
)
from ..models import AbuseReport, CinderJob, CinderPolicy
from ..utils import (
    CinderActionApproveInitialDecision,
    CinderActionBanUser,
    CinderActionDeleteCollection,
    CinderActionDeleteRating,
    CinderActionDisableAddon,
    CinderActionEscalateAddon,
    CinderActionNotImplemented,
    CinderActionOverrideApprove,
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
        del report._target_addon
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
            appeal_job=appeal_job,
            target_addon=addon,
        )
        AbuseReport.objects.create(guid=addon.guid, cinder_job=original_job)
        assert list(CinderJob.objects.for_addon(addon)) == [original_job, appeal_job]

    def test_unresolved(self):
        job = CinderJob.objects.create(job_id='1')
        AbuseReport.objects.create(guid='3456', cinder_job=job)
        AbuseReport.objects.create(
            guid='5678',
            cinder_job=CinderJob.objects.create(
                job_id='2', decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON
            ),
        )
        qs = CinderJob.objects.unresolved()
        assert len(qs) == 1
        assert list(qs) == [job]

    def test_reviewer_handled(self):
        not_policy_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            location=AbuseReport.LOCATION.BOTH,
            cinder_job=CinderJob.objects.create(job_id=1),
        )
        job = CinderJob.objects.create(job_id=2)
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
        job.update(appeal_job=appeal_job)
        qs = CinderJob.objects.resolvable_in_reviewer_tools()
        assert list(qs) == [job, appeal_job]

        not_policy_report.cinder_job.update(
            decision_action=DECISION_ACTIONS.AMO_ESCALATE_ADDON,
            resolvable_in_reviewer_tools=True,
        )
        qs = CinderJob.objects.resolvable_in_reviewer_tools()
        assert list(qs) == [not_policy_report.cinder_job, job, appeal_job]


class TestCinderJob(TestCase):
    def test_target(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        # edge case, but handle having no associated abuse_reports
        assert cinder_job.target is None

        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            location=AbuseReport.LOCATION.BOTH,
            cinder_job=cinder_job,
        )
        assert cinder_job.target == abuse_report.target == addon

        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        cinder_job.update(appeal_job=appeal_job)
        assert appeal_job.target == cinder_job.target == addon

        appeal_appeal_job = CinderJob.objects.create(job_id='fake_appeal_appeal_job_id')
        appeal_job.update(appeal_job=appeal_appeal_job)
        assert (
            appeal_appeal_job.target == appeal_job.target == cinder_job.target == addon
        )

    def test_target_addon(self):
        addon = addon_factory()
        cinder_job = CinderJob.objects.create(job_id='1234', target_addon=addon)
        assert cinder_job.target == addon

    def test_initial_abuse_report(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        assert cinder_job.initial_abuse_report is None

        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            location=AbuseReport.LOCATION.BOTH,
            cinder_job=cinder_job,
        )
        assert cinder_job.initial_abuse_report == abuse_report

        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        cinder_job.update(appeal_job=appeal_job)
        assert (
            appeal_job.initial_abuse_report
            == cinder_job.initial_abuse_report
            == abuse_report
        )

        appeal_appeal_job = CinderJob.objects.create(job_id='fake_appeal_appeal_job_id')
        appeal_job.update(appeal_job=appeal_appeal_job)
        assert (
            appeal_appeal_job.initial_abuse_report
            == appeal_job.initial_abuse_report
            == cinder_job.initial_abuse_report
            == abuse_report
        )

    def test_get_entity_helper(self):
        addon = addon_factory()
        user = user_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            location=AbuseReport.LOCATION.BOTH,
        )
        helper = CinderJob.get_entity_helper(abuse_report)
        # location is in REVIEWER_HANDLED (BOTH) but reason is not (ILLEGAL)
        assert isinstance(helper, CinderAddon)
        assert not isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version is None

        abuse_report.update(reason=AbuseReport.REASONS.POLICY_VIOLATION)
        helper = CinderJob.get_entity_helper(abuse_report)
        # now reason is in REVIEWER_HANDLED it will be reported differently
        assert isinstance(helper, CinderAddon)
        assert isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version is None

        abuse_report.update(addon_version=addon.current_version.version)
        helper = CinderJob.get_entity_helper(abuse_report)
        # if we got a version too we pass it on to the helper
        assert isinstance(helper, CinderAddon)
        assert isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version == addon.current_version

        abuse_report.update(location=AbuseReport.LOCATION.AMO)
        helper = CinderJob.get_entity_helper(abuse_report)
        # but not if the location is not in REVIEWER_HANDLED (i.e. AMO)
        assert isinstance(helper, CinderAddon)
        assert not isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version == addon.current_version

        abuse_report.update(guid=None, user=user, addon_version=None)
        helper = CinderJob.get_entity_helper(abuse_report)
        assert isinstance(helper, CinderUser)
        assert helper.user == user

        rating = Rating.objects.create(addon=addon, user=user, rating=4)
        abuse_report.update(user=None, rating=rating)
        helper = CinderJob.get_entity_helper(abuse_report)
        assert isinstance(helper, CinderRating)
        assert helper.rating == rating

        collection = collection_factory()
        abuse_report.update(rating=None, collection=collection)
        helper = CinderJob.get_entity_helper(abuse_report)
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
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid, reason=AbuseReport.REASONS.ILLEGAL
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
            guid=addon_factory().guid, reason=AbuseReport.REASONS.ILLEGAL
        )
        CinderJob.report(another_report)
        cinder_job.reload()
        assert CinderJob.objects.count() == 1
        assert list(cinder_job.abusereport_set.all()) == [abuse_report, another_report]
        assert cinder_job.target_addon == abuse_report.target
        assert not cinder_job.resolvable_in_reviewer_tools

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

    def test_get_action_helper(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        helper = cinder_job.get_action_helper()
        assert helper.cinder_job == cinder_job
        assert helper.__class__ == CinderActionNotImplemented

        action_to_class = (
            (DECISION_ACTIONS.AMO_BAN_USER, CinderActionBanUser),
            (DECISION_ACTIONS.AMO_DISABLE_ADDON, CinderActionDisableAddon),
            (DECISION_ACTIONS.AMO_ESCALATE_ADDON, CinderActionEscalateAddon),
            (DECISION_ACTIONS.AMO_DELETE_COLLECTION, CinderActionDeleteCollection),
            (DECISION_ACTIONS.AMO_DELETE_RATING, CinderActionDeleteRating),
            (DECISION_ACTIONS.AMO_APPROVE, CinderActionApproveInitialDecision),
        )
        action_existing_to_class = {
            (new_action, existing_action): ActionClass
            for new_action, ActionClass in action_to_class
            for existing_action in DECISION_ACTIONS.values
        }
        for action in DECISION_ACTIONS.REMOVING.values:
            action_existing_to_class[
                (DECISION_ACTIONS.AMO_APPROVE, action)
            ] = CinderActionTargetAppealApprove
            action_existing_to_class[
                (action, action)
            ] = CinderActionTargetAppealRemovalAffirmation

        for (
            new_action,
            existing_action,
        ), ActionClass in action_existing_to_class.items():
            cinder_job.update(decision_action=new_action)
            helper = cinder_job.get_action_helper(existing_action)
            assert helper.__class__ == ActionClass
            assert helper.cinder_job == cinder_job

        # and repeat for the override edge case
        for action in DECISION_ACTIONS.REMOVING.values:
            action_existing_to_class[
                (DECISION_ACTIONS.AMO_APPROVE, action)
            ] = CinderActionOverrideApprove
            action_existing_to_class[(action, action)] = CinderActionNotImplemented

        for (
            new_action,
            existing_action,
        ), ActionClass in action_existing_to_class.items():
            cinder_job.update(decision_action=new_action)
            helper = cinder_job.get_action_helper(existing_action, override=True)
            assert helper.__class__ == ActionClass

    def test_process_decision(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        new_date = datetime(2023, 1, 1)
        policy_a = CinderPolicy.objects.create(uuid='123-45', name='aaa', text='AAA')
        policy_b = CinderPolicy.objects.create(uuid='678-90', name='bbb', text='BBB')

        with mock.patch.object(
            CinderActionBanUser, 'process_action'
        ) as action_mock, mock.patch.object(
            CinderActionBanUser, 'notify_owners'
        ) as notify_mock:
            action_mock.return_value = True
            cinder_job.process_decision(
                decision_id='12345',
                decision_date=new_date,
                decision_action=DECISION_ACTIONS.AMO_BAN_USER.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
            )
        assert cinder_job.decision_id == '12345'
        assert cinder_job.decision_date == new_date
        assert cinder_job.decision_action == DECISION_ACTIONS.AMO_BAN_USER
        assert cinder_job.decision_notes == 'teh notes'
        assert action_mock.call_count == 1
        assert notify_mock.call_count == 1
        assert list(cinder_job.policies.all()) == [policy_a, policy_b]

    def test_process_decision_with_duplicate_parent(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
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
            action_mock.return_value = True
            cinder_job.process_decision(
                decision_id='12345',
                decision_date=new_date,
                decision_action=DECISION_ACTIONS.AMO_BAN_USER.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
            )
        assert cinder_job.decision_id == '12345'
        assert cinder_job.decision_date == new_date
        assert cinder_job.decision_action == DECISION_ACTIONS.AMO_BAN_USER
        assert cinder_job.decision_notes == 'teh notes'
        assert action_mock.call_count == 1
        assert notify_mock.call_count == 1
        assert list(cinder_job.policies.all()) == [policy]

    def test_process_decision_escalate_addon(self):
        addon = addon_factory()
        cinder_job = CinderJob.objects.create(job_id='1234', target_addon=addon)
        assert not cinder_job.resolvable_in_reviewer_tools
        new_date = datetime(2024, 1, 1)
        cinder_job.process_decision(
            decision_id='12345',
            decision_date=new_date,
            decision_action=DECISION_ACTIONS.AMO_ESCALATE_ADDON,
            decision_notes='blah',
            policy_ids=[],
        )
        assert cinder_job.decision_id == '12345'
        assert cinder_job.decision_date == new_date
        assert cinder_job.decision_action == DECISION_ACTIONS.AMO_ESCALATE_ADDON
        assert cinder_job.decision_notes == 'blah'
        assert cinder_job.resolvable_in_reviewer_tools
        assert cinder_job.target_addon == addon

    def test_appeal_as_target(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            cinder_job=CinderJob.objects.create(
                decision_id='4815162342-lost',
                decision_date=self.days_ago(179),
                decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
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

        abuse_report.cinder_job.appeal(
            abuse_report=abuse_report,
            appeal_text='appeal text',
            user=user_factory(),
            is_reporter=False,
        )

        abuse_report.cinder_job.reload()
        assert abuse_report.cinder_job.appeal_job_id
        assert abuse_report.cinder_job.appeal_job.job_id == '2432615184-tsol'
        assert abuse_report.cinder_job.appeal_job.target_addon == addon
        abuse_report.reload()
        assert not abuse_report.reporter_appeal_date
        assert not abuse_report.appellant_job

    def test_appeal_as_target_improperly_configured(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            cinder_job=CinderJob.objects.create(
                decision_id='4815162342-lost',
                decision_date=self.days_ago(179),
                decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
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
            abuse_report.cinder_job.appeal(
                abuse_report=abuse_report,
                appeal_text='appeal text',
                # Can't pass user=None for a target appeal, unless it's
                # specifically a user ban (see test_appeal_as_target_banned()).
                user=None,
                is_reporter=False,
            )

        abuse_report.cinder_job.reload()
        assert not abuse_report.cinder_job.appeal_job_id
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
                decision_id='4815162342-lost',
                decision_date=self.days_ago(179),
                # This (target is an add-on, decision is a user ban) shouldn't
                # be possible but we want to make sure this is handled
                # explicitly.
                decision_action=DECISION_ACTIONS.AMO_BAN_USER,
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
            abuse_report.cinder_job.appeal(
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
        assert not abuse_report.cinder_job.appeal_job_id
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
                decision_id='4815162342-lost',
                decision_date=self.days_ago(179),
                decision_action=DECISION_ACTIONS.AMO_BAN_USER,
            ),
        )
        assert not abuse_report.reporter_appeal_date
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )

        abuse_report.cinder_job.appeal(
            abuse_report=abuse_report,
            appeal_text='appeal text',
            # user=None is allowed here since the original decision was a ban,
            # the target user can no longer log in but should be allowed to
            # appeal.
            user=None,
            is_reporter=False,
        )

        abuse_report.cinder_job.reload()
        assert abuse_report.cinder_job.appeal_job_id
        assert abuse_report.cinder_job.appeal_job.job_id == '2432615184-tsol'
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
                decision_id='4815162342-lost',
                decision_date=self.days_ago(179),
                decision_action=DECISION_ACTIONS.AMO_APPROVE,
                target_addon=addon,
            )
        )
        assert not abuse_report.reporter_appeal_date
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )

        abuse_report.cinder_job.appeal(
            abuse_report=abuse_report,
            appeal_text='appeal text',
            user=abuse_report.reporter,
            is_reporter=True,
        )

        abuse_report.cinder_job.reload()
        assert abuse_report.cinder_job.appeal_job
        assert abuse_report.cinder_job.appeal_job.job_id == '2432615184-tsol'
        assert abuse_report.cinder_job.appeal_job.target_addon == addon
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
                decision_id='4815162342-lost',
                decision_date=self.days_ago(179),
                decision_action=DECISION_ACTIONS.AMO_APPROVE,
                target_addon=addon,
            )
        )
        # Pretend there was already an appeal job from a different reporter.
        # Make that resolvable in reviewer tools as if it had been escalated,
        # to ensure the get_or_create() call that we make can't trigger an
        # IntegrityError because of the additional parameters (job_id must
        # be the only field we use to retrieve the job).
        abuse_report.cinder_job.update(
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

        abuse_report.cinder_job.appeal(
            abuse_report=abuse_report,
            appeal_text='appeal text',
            user=abuse_report.reporter,
            is_reporter=True,
        )

        abuse_report.cinder_job.reload()
        assert abuse_report.cinder_job.appeal_job
        assert abuse_report.cinder_job.appeal_job.job_id == '2432615184-tsol'
        assert abuse_report.cinder_job.appeal_job.target_addon == addon
        abuse_report.reload()
        assert abuse_report.appellant_job.job_id == '2432615184-tsol'
        assert abuse_report.reporter_appeal_date

    def test_appeal_improperly_configured_reporter(self):
        cinder_job = CinderJob.objects.create(
            decision_id='4815162342-lost',
            decision_date=self.days_ago(179),
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        with self.assertRaises(ImproperlyConfigured):
            cinder_job.appeal(
                abuse_report=None,
                appeal_text='No abuse_report but is_reporter is True',
                user=user_factory(),
                is_reporter=True,
            )

    def test_appeal_improperly_configured_author(self):
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
        )
        cinder_job = CinderJob.objects.create(
            decision_id='4815162342-lost',
            decision_date=self.days_ago(179),
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        with self.assertRaises(ImproperlyConfigured):
            cinder_job.appeal(
                abuse_report=abuse_report,
                appeal_text='No user but is_reporter is False',
                user=None,
                is_reporter=False,
            )

    def _test_resolve_job(self, activity_action, cinder_action, *, expect_target_email):
        cinder_job = CinderJob.objects.create(job_id='999')
        addon_developer = user_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory(users=[addon_developer]).guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            cinder_job=cinder_job,
            reporter=user_factory(),
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': '123'},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{cinder_job.job_id}/cancel',
            json={'external_id': cinder_job.job_id},
            status=200,
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]
        review_action_reason = ReviewActionReason.objects.create(
            cinder_policy=policies[0]
        )

        log_entry = ActivityLog.objects.create(
            activity_action,
            abuse_report.target,
            abuse_report.target.current_version,
            review_action_reason,
            details={'comments': 'some review text'},
            user=user_factory(),
        )

        cinder_job.resolve_job(log_entry=log_entry)

        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['policy_uuids'] == ['12345678']
        assert request_body['reasoning'] == 'some review text'
        assert request_body['entity']['id'] == str(abuse_report.target.id)
        cinder_job.reload()
        assert cinder_job.decision_action == cinder_action
        self.assertCloseToNow(cinder_job.decision_date)
        assert list(cinder_job.policies.all()) == policies
        assert len(mail.outbox) == (2 if expect_target_email else 1)
        assert mail.outbox[0].to == [abuse_report.reporter.email]
        if expect_target_email:
            assert mail.outbox[1].to == [addon_developer.email]
            assert str(log_entry.id) in mail.outbox[1].extra_headers['Message-ID']
            assert 'some review text' in mail.outbox[1].body
            assert (
                str(abuse_report.target.current_version.version) in mail.outbox[1].body
            )

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

    def test_resolve_job_duplicate_policy(self):
        cinder_job = CinderJob.objects.create(job_id='999')
        addon_developer = user_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory(users=[addon_developer]).guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            cinder_job=cinder_job,
            reporter=user_factory(),
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': '123'},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{cinder_job.job_id}/cancel',
            json={'external_id': cinder_job.job_id},
            status=200,
        )
        parent_policy = CinderPolicy.objects.create(
            name='parent policy', uuid='12345678'
        )
        policy = CinderPolicy.objects.create(
            name='policy', uuid='4815162342', parent=parent_policy
        )
        review_action_reason1 = ReviewActionReason.objects.create(cinder_policy=policy)
        review_action_reason2 = ReviewActionReason.objects.create(
            cinder_policy=parent_policy
        )

        log_entry = ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION,
            abuse_report.target,
            abuse_report.target.current_version,
            review_action_reason1,
            review_action_reason2,
            details={'comments': 'some review text'},
            user=user_factory(),
        )

        cinder_job.resolve_job(log_entry=log_entry)

        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['policy_uuids'] == [policy.uuid]
        assert request_body['reasoning'] == 'some review text'
        assert request_body['entity']['id'] == str(abuse_report.target.id)
        cinder_job.reload()
        assert cinder_job.decision_action == (DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON)
        self.assertCloseToNow(cinder_job.decision_date)
        # Parent policy was a duplicate since we already have its child, and
        # has been ignored.
        assert list(cinder_job.policies.all()) == [policy]
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [abuse_report.reporter.email]
        assert mail.outbox[1].to == [addon_developer.email]
        assert str(log_entry.id) in mail.outbox[1].extra_headers['Message-ID']
        assert 'some review text' in mail.outbox[1].body
        assert str(abuse_report.target.current_version.version) in mail.outbox[1].body

    def test_resolve_job_no_cinder_action_in_activity_log(self):
        cinder_job = CinderJob.objects.create(job_id='999')
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            cinder_job=cinder_job,
        )
        log_entry = ActivityLog.objects.create(
            amo.LOG.REPLY_RATING,
            abuse_report.target,
            abuse_report.target.current_version,
            details={'comments': 'some review text'},
            user=user_factory(),
        )

        with self.assertRaises(ImproperlyConfigured):
            cinder_job.resolve_job(log_entry=log_entry)

    def test_abuse_reports(self):
        job = CinderJob.objects.create(job_id='fake_job_id')
        assert list(job.abuse_reports) == []

        report = AbuseReport.objects.create(guid=addon_factory().guid, cinder_job=job)
        assert list(job.abuse_reports) == [report]

        report2 = AbuseReport.objects.create(guid=addon_factory().guid, cinder_job=job)
        assert list(job.abuse_reports) == [report, report2]

        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        job.update(appeal_job=appeal_job)

        assert appeal_job.abuse_reports == [report, report2]
        assert list(job.abuse_reports) == [report, report2]

        appeal_appeal_job = CinderJob.objects.create(job_id='fake_appeal_appeal_job_id')
        appeal_job.update(appeal_job=appeal_appeal_job)

        assert list(appeal_appeal_job.abuse_reports) == [report, report2]
        assert list(appeal_job.abuse_reports) == [report, report2]
        assert list(job.abuse_reports) == [report, report2]

    def test_is_appeal(self):
        job = CinderJob.objects.create(job_id='fake_job_id')
        assert not job.is_appeal

        appeal = CinderJob.objects.create(job_id='an appeal job')
        job.update(appeal_job=appeal)
        job.reload()
        assert not job.is_appeal
        assert appeal.is_appeal


class TestCinderJobCanBeAppealed(TestCase):
    def setUp(self):
        self.reporter = user_factory()
        self.author = user_factory()
        self.addon = addon_factory(users=[self.author])
        self.initial_job = CinderJob.objects.create(job_id='fake_initial_job_id')
        self.initial_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=self.initial_job,
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )

    def test_appealed_decision_already_made(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        assert not self.initial_job.appealed_decision_already_made()

        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
        )
        self.initial_job.update(appeal_job=appeal_job)
        assert not self.initial_job.appealed_decision_already_made()

        appeal_job.update(decision_id='appeal decision id')
        assert self.initial_job.appealed_decision_already_made()

    def test_reporter_can_appeal_approve_decision(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        assert self.initial_job.can_be_appealed(
            is_reporter=True, abuse_report=self.initial_report
        )

    def test_reporter_cant_appeal_approve_decision_if_abuse_report_is_not_passed(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        assert not self.initial_job.can_be_appealed(is_reporter=True)

    def test_reporter_cant_appeal_non_approve_decision(self):
        for decision_action in (
            DECISION_ACTIONS.NO_DECISION,
            DECISION_ACTIONS.AMO_ESCALATE_ADDON,
            DECISION_ACTIONS.AMO_BAN_USER,
            DECISION_ACTIONS.AMO_DISABLE_ADDON,
            DECISION_ACTIONS.AMO_DELETE_RATING,
            DECISION_ACTIONS.AMO_DELETE_COLLECTION,
        ):
            self.initial_job.update(
                decision_date=datetime.now(),
                decision_id='fake_decision_id',
                decision_action=decision_action,
            )
            assert not self.initial_job.can_be_appealed(
                is_reporter=True, abuse_report=self.initial_report
            )

    def test_reporter_cant_appeal_approve_decision_already_appealed(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
        )
        self.initial_job.update(appeal_job=appeal_job)
        self.initial_report.update(
            reporter_appeal_date=datetime.now(), appellant_job=appeal_job
        )
        assert not self.initial_job.can_be_appealed(
            is_reporter=True, abuse_report=self.initial_report
        )

    def test_reporter_can_appeal_approve_decision_already_appealed_someone_else(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
        )
        self.initial_job.update(appeal_job=appeal_job)
        AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=self.initial_job,
            reporter=user_factory(),
            reporter_appeal_date=datetime.now(),
            appellant_job=appeal_job,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert self.initial_job.can_be_appealed(
            is_reporter=True, abuse_report=self.initial_report
        )

    def test_reporter_cant_appeal_approve_decision_already_appealed_and_decided(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
            decision_date=datetime.now(),
            decision_id='fake_appeal_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        self.initial_job.update(appeal_job=appeal_job)
        AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=self.initial_job,
            appellant_job=appeal_job,
            reporter=user_factory(),
            reporter_appeal_date=datetime.now(),
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert not self.initial_job.can_be_appealed(
            is_reporter=True, abuse_report=self.initial_report
        )

    def test_reporter_cant_appeal_appealed_decision(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
            decision_date=datetime.now(),
            decision_id='fake_appeal_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        self.initial_job.update(appeal_job=appeal_job)
        self.initial_report.update(
            reporter_appeal_date=datetime.now(), appellant_job=appeal_job
        )
        # We should never end up in this situation where an AbuseReport is tied
        # to a CinderJob from an appeal, but if that somehow happens we want to
        # make sure it's impossible for a reporter to appeal an appeal.
        new_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=appeal_job,
            reporter=user_factory(),
            reporter_appeal_date=datetime.now(),
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert not appeal_job.can_be_appealed(is_reporter=True, abuse_report=new_report)

    def test_reporter_cant_appeal_past_expiration_delay(self):
        self.initial_job.update(
            decision_date=self.days_ago(APPEAL_EXPIRATION_DAYS + 1),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        assert not self.initial_job.can_be_appealed(
            is_reporter=True, abuse_report=self.initial_report
        )

    def test_author_can_appeal_disable_decision(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        )
        assert self.initial_job.can_be_appealed(is_reporter=False)

    def test_author_can_appeal_delete_decision_rating(self):
        user = user_factory()
        rating = Rating.objects.create(
            addon=self.addon, user=user, rating=1, body='blah'
        )
        self.initial_report.update(guid=None, rating=rating)
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_DELETE_RATING,
        )
        self.initial_job.can_be_appealed(is_reporter=False)

    def test_author_can_appeal_delete_decision_collection(self):
        user = user_factory()
        collection = collection_factory(author=user)
        self.initial_report.update(guid=None, collection=collection)
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_DELETE_COLLECTION,
        )
        self.initial_job.can_be_appealed(is_reporter=False)

    def test_author_can_appeal_ban_user(self):
        user = user_factory()
        self.initial_report.update(guid=None, user=user)
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_BAN_USER,
        )
        self.initial_job.can_be_appealed(is_reporter=False)

    def test_author_cant_appeal_approve_or_escalation_decision(self):
        for decision_action in (
            DECISION_ACTIONS.NO_DECISION,
            DECISION_ACTIONS.AMO_ESCALATE_ADDON,
            DECISION_ACTIONS.AMO_APPROVE,
        ):
            self.initial_job.update(
                decision_date=datetime.now(),
                decision_id='fake_decision_id',
                decision_action=decision_action,
            )
            assert not self.initial_job.can_be_appealed(is_reporter=False)

    def test_author_cant_appeal_disable_decision_already_appealed(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        )
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
        )
        self.initial_job.update(appeal_job=appeal_job)
        assert not self.initial_job.can_be_appealed(is_reporter=False)

    def test_author_can_appeal_appealed_decision(self):
        self.initial_job.update(
            decision_date=datetime.now(),
            decision_id='fake_decision_id',
            decision_action=DECISION_ACTIONS.AMO_APPROVE,
        )
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
            decision_date=datetime.now(),
            decision_id='fake_appeal_decision_id',
            decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        )
        self.initial_job.update(appeal_job=appeal_job)
        assert appeal_job.can_be_appealed(is_reporter=False)


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
