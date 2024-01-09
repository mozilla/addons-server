import json
from datetime import datetime
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError

import responses

from olympia.amo.tests import TestCase, addon_factory, collection_factory, user_factory
from olympia.ratings.models import Rating

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
    CinderActionApproveAppealOverride,
    CinderActionApproveInitialDecision,
    CinderActionBanUser,
    CinderActionDeleteCollection,
    CinderActionDeleteRating,
    CinderActionDisableAddon,
    CinderActionEscalateAddon,
    CinderActionNotImplemented,
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

    def test_unresolved(self):
        report_no_job = AbuseReport.objects.create(guid='1234')
        report_unresolved_job = AbuseReport.objects.create(
            guid='3456', cinder_job=CinderJob.objects.create(job_id='1')
        )
        AbuseReport.objects.create(
            guid='5678',
            cinder_job=CinderJob.objects.create(
                job_id='2', decision_action=CinderJob.DECISION_ACTIONS.AMO_DISABLE_ADDON
            ),
        )
        qs = AbuseReport.objects.unresolved()
        assert len(qs) == 2
        assert list(qs) == [report_no_job, report_unresolved_job]

    def test_reviewer_handled(self):
        AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            location=AbuseReport.LOCATION.BOTH,
        )
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
        )
        AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.AMO,
        )
        qs = AbuseReport.objects.reviewer_handled()
        assert len(qs) == 1
        assert list(qs) == [abuse_report]


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

        # And check if we get back the same job_id for a subsequent report we update

        another_report = AbuseReport.objects.create(
            guid=addon_factory().guid, reason=AbuseReport.REASONS.ILLEGAL
        )
        CinderJob.report(another_report)
        cinder_job.reload()
        assert CinderJob.objects.count() == 1
        assert list(cinder_job.abusereport_set.all()) == [abuse_report, another_report]

    def test_get_action_helper(self):
        DECISION_ACTIONS = CinderJob.DECISION_ACTIONS
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
        )
        for action, ActionClass in (
            *action_to_class,
            (DECISION_ACTIONS.AMO_APPROVE, CinderActionApproveInitialDecision),
        ):
            cinder_job.update(decision_action=action)
            helper = cinder_job.get_action_helper()
            assert helper.__class__ == ActionClass
            assert helper.cinder_job == cinder_job

        for action, ActionClass in (
            *action_to_class,
            (DECISION_ACTIONS.AMO_APPROVE, CinderActionApproveAppealOverride),
        ):
            cinder_job.update(decision_action=action)
            helper = cinder_job.get_action_helper(DECISION_ACTIONS.AMO_DISABLE_ADDON)
            assert helper.__class__ == ActionClass
            assert helper.cinder_job == cinder_job

    def test_process_decision(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        new_date = datetime(2023, 1, 1)
        policy_a = CinderPolicy.objects.create(uuid='123-45', name='aaa', text='AAA')
        policy_b = CinderPolicy.objects.create(uuid='678-90', name='bbb', text='BBB')

        with mock.patch.object(CinderActionBanUser, 'process') as cinder_action_mock:
            cinder_job.process_decision(
                decision_id='12345',
                decision_date=new_date,
                decision_action=CinderJob.DECISION_ACTIONS.AMO_BAN_USER.value,
                policy_ids=['123-45', '678-90'],
            )
        assert cinder_job.decision_id == '12345'
        assert cinder_job.decision_date == new_date
        assert cinder_job.decision_action == CinderJob.DECISION_ACTIONS.AMO_BAN_USER
        assert cinder_action_mock.call_count == 1
        assert list(cinder_job.policies.all()) == [policy_a, policy_b]

    def test_can_be_appealed(self):
        addon = addon_factory()

        cinder_job = CinderJob.objects.create(
            decision_id='4815162342-lost',
            decision_date=self.days_ago(179),
        )
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            cinder_job=cinder_job,
        )

        assert cinder_job.can_be_appealed(abuse_report)

        cinder_job.update(decision_date=None)
        assert not cinder_job.can_be_appealed(abuse_report)

        cinder_job.update(decision_date=self.days_ago(185))
        assert not cinder_job.can_be_appealed(abuse_report)

        cinder_job.update(decision_date=self.days_ago(179), decision_id=None)
        assert not cinder_job.can_be_appealed(abuse_report)

        cinder_job.update(decision_id='some-decision-id')
        assert cinder_job.can_be_appealed(abuse_report)

        # not if there was already an appeal
        appeal = CinderJobAppeal.objects.create(
            appeal_id='some-appeal-id', abuse_report=abuse_report
        )
        abuse_report.refresh_from_db()
        assert not cinder_job.can_be_appealed(abuse_report)

        # but can for a different abuse report for the same job
        assert cinder_job.can_be_appealed(
            AbuseReport.objects.create(
                guid=addon.guid,
                reason=AbuseReport.REASONS.ILLEGAL,
                cinder_job=cinder_job,
            )
        )

        # or if the appeal didn't exist
        appeal.delete()
        abuse_report.refresh_from_db()
        assert cinder_job.can_be_appealed(abuse_report)

        user = user_factory()
        abuse_report.update(user=user, guid=None)
        assert cinder_job.can_be_appealed(abuse_report)

        rating = Rating.objects.create(addon=addon, user=user, rating=1)
        abuse_report.update(user=None, rating=rating)
        assert cinder_job.can_be_appealed(abuse_report)

        collection = collection_factory()
        abuse_report.update(rating=None, collection=collection)
        assert cinder_job.can_be_appealed(abuse_report)

    def test_appeal(self):
        cinder_job = CinderJob.objects.create(
            decision_id='4815162342-lost',
            decision_date=self.days_ago(179),
        )
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            cinder_job=cinder_job,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )

        cinder_job.appeal(abuse_report, 'appeal text', user_factory())

        appeal = CinderJobAppeal.objects.get()
        assert appeal.appeal_id == '2432615184-tsol'
        assert appeal.abuse_report == abuse_report

    def test_resolve_job(self):
        cinder_job = CinderJob.objects.create(job_id='999')
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.AMO,
            cinder_job=cinder_job,
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

        cinder_job.resolve_job(
            'some text',
            CinderJob.DECISION_ACTIONS.AMO_DISABLE_ADDON,
            policies,
        )

        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['policy_uuids'] == ['12345678']
        assert request_body['reasoning'] == 'some text'
        assert request_body['entity']['id'] == str(abuse_report.target.id)
        cinder_job.reload()
        assert cinder_job.decision_action == (
            CinderJob.DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        self.assertCloseToNow(cinder_job.decision_date)
        assert list(cinder_job.policies.all()) == policies

    def test_abuse_reports(self):
        job = CinderJob.objects.create(job_id='fake_job_id')
        assert job.abuse_reports == set()

        report = AbuseReport.objects.create(guid=addon_factory().guid, cinder_job=job)
        assert job.abuse_reports == {report}

        report2 = AbuseReport.objects.create(guid=addon_factory().guid, cinder_job=job)
        assert job.abuse_reports == {report, report2}

        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        job.update(appeal_job=appeal_job)

        assert appeal_job.abuse_reports == {report, report2}
        assert job.abuse_reports == {report, report2}

        appeal_appeal_job = CinderJob.objects.create(job_id='fake_appeal_appeal_job_id')
        appeal_job.update(appeal_job=appeal_appeal_job)

        assert appeal_appeal_job.abuse_reports == {report, report2}
        assert appeal_job.abuse_reports == {report, report2}
        assert job.abuse_reports == {report, report2}


class TestCinderJobCanBeAppealed(TestCase):
    def setUp(self):
        self.addon = addon_factory()

    def test_reporter_can_appeal_approve_decision(self):
        raise NotImplementedError

    def test_reporter_cant_appeal_approve_decision_already_appealed(self):
        raise NotImplementedError

    def test_reporter_can_appeal_approve_decision_already_appealed_someone_else(self):
        raise NotImplementedError

    def test_reporter_cant_appeal_appealed_decision(self):
        raise NotImplementedError

    def test_etc(self):
        raise NotImplementedError

    # FIXME: more!
