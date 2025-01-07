import json
import uuid
from datetime import datetime
from unittest import mock
from urllib import parse

from django.conf import settings
from django.core import mail
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.db.utils import IntegrityError
from django.urls import reverse

import pytest
import responses
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog, AttachmentLog
from olympia.addons.models import Addon
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    user_factory,
    version_factory,
    version_review_flags_factory,
)
from olympia.constants.abuse import (
    APPEAL_EXPIRATION_DAYS,
    DECISION_ACTIONS,
    ILLEGAL_CATEGORIES,
    ILLEGAL_SUBCATEGORIES,
)
from olympia.constants.promoted import RECOMMENDED
from olympia.core import set_user
from olympia.ratings.models import Rating
from olympia.reviewers.models import NeedsHumanReview
from olympia.versions.models import Version, VersionReviewerFlags

from ..actions import (
    ContentActionBanUser,
    ContentActionDeleteCollection,
    ContentActionDeleteRating,
    ContentActionOverrideApprove,
    ContentActionTargetAppealApprove,
    ContentActionTargetAppealRemovalAffirmation,
)
from ..cinder import (
    CinderAddon,
    CinderAddonHandledByReviewers,
    CinderCollection,
    CinderRating,
    CinderUnauthenticatedReporter,
    CinderUser,
)
from ..models import (
    AbuseReport,
    AbuseReportManager,
    CinderAppeal,
    CinderJob,
    CinderPolicy,
    CinderQueueMove,
    ContentDecision,
)


class TestAbuseReport(TestCase):
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
            (13, 'Not required'),
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
            (13, 'not_required'),
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

        assert ILLEGAL_CATEGORIES.choices == (
            (None, 'None'),
            (1, 'Animal welfare'),
            (2, 'Consumer information infringements'),
            (3, 'Data protection and privacy violations'),
            (4, 'Illegal or harmful speech'),
            (5, 'Intellectual property infringements'),
            (6, 'Negative effects on civic discourse or elections'),
            (7, 'Non-consensual behavior'),
            (8, 'Pornography or sexualized content'),
            (9, 'Protection of minors'),
            (10, 'Risk for public security'),
            (11, 'Scams or fraud'),
            (12, 'Self-harm'),
            (13, 'Unsafe, non-compliant, or prohibited products'),
            (14, 'Violence'),
            (15, 'Other'),
        )
        assert ILLEGAL_CATEGORIES.api_choices == (
            (None, None),
            (1, 'animal_welfare'),
            (2, 'consumer_information'),
            (3, 'data_protection_and_privacy_violations'),
            (4, 'illegal_or_harmful_speech'),
            (5, 'intellectual_property_infringements'),
            (6, 'negative_effects_on_civic_discourse_or_elections'),
            (7, 'non_consensual_behaviour'),
            (8, 'pornography_or_sexualized_content'),
            (9, 'protection_of_minors'),
            (10, 'risk_for_public_security'),
            (11, 'scams_and_fraud'),
            (12, 'self_harm'),
            (13, 'unsafe_and_prohibited_products'),
            (14, 'violence'),
            (15, 'other'),
        )

        assert ILLEGAL_SUBCATEGORIES.choices == (
            (None, 'None'),
            (1, 'Something else'),
            (2, 'Insufficient information on traders'),
            (3, 'Non-compliance with pricing regulations'),
            (
                4,
                'Hidden advertisement or commercial communication, including '
                'by influencers',
            ),
            (
                5,
                'Misleading information about the characteristics of the goods '
                'and services',
            ),
            (6, 'Misleading information about the consumer’s rights'),
            (7, 'Biometric data breach'),
            (8, 'Missing processing ground for data'),
            (9, 'Right to be forgotten'),
            (10, 'Data falsification'),
            (11, 'Defamation'),
            (12, 'Discrimination'),
            (
                13,
                'Illegal incitement to violence and hatred based on protected '
                'characteristics (hate speech)',
            ),
            (14, 'Design infringements'),
            (15, 'Geographical indications infringements'),
            (16, 'Patent infringements'),
            (17, 'Trade secret infringements'),
            (18, 'Violation of EU law relevant to civic discourse or elections'),
            (19, 'Violation of national law relevant to civic discourse or elections'),
            (
                20,
                'Misinformation, disinformation, foreign information manipulation '
                'and interference',
            ),
            (21, 'Non-consensual image sharing'),
            (
                22,
                'Non-consensual items containing deepfake or similar technology '
                "using a third party's features",
            ),
            (23, 'Online bullying/intimidation'),
            (24, 'Stalking'),
            (25, 'Adult sexual material'),
            (26, 'Image-based sexual abuse (excluding content depicting minors)'),
            (27, 'Age-specific restrictions concerning minors'),
            (28, 'Child sexual abuse material'),
            (29, 'Grooming/sexual enticement of minors'),
            (30, 'Illegal organizations'),
            (31, 'Risk for environmental damage'),
            (32, 'Risk for public health'),
            (33, 'Terrorist content'),
            (34, 'Inauthentic accounts'),
            (35, 'Inauthentic listings'),
            (36, 'Inauthentic user reviews'),
            (37, 'Impersonation or account hijacking'),
            (38, 'Phishing'),
            (39, 'Pyramid schemes'),
            (40, 'Content promoting eating disorders'),
            (41, 'Self-mutilation'),
            (42, 'Suicide'),
            (43, 'Prohibited or restricted products'),
            (44, 'Unsafe or non-compliant products'),
            (45, 'Coordinated harm'),
            (46, 'Gender-based violence'),
            (47, 'Human exploitation'),
            (48, 'Human trafficking'),
            (49, 'General calls or incitement to violence and/or hatred'),
        )
        assert ILLEGAL_SUBCATEGORIES.api_choices == (
            (None, None),
            (1, 'other'),
            (2, 'insufficient_information_on_traders'),
            (3, 'noncompliance_pricing'),
            (4, 'hidden_advertisement'),
            (5, 'misleading_info_goods_services'),
            (6, 'misleading_info_consumer_rights'),
            (7, 'biometric_data_breach'),
            (8, 'missing_processing_ground'),
            (9, 'right_to_be_forgotten'),
            (10, 'data_falsification'),
            (11, 'defamation'),
            (12, 'discrimination'),
            (13, 'hate_speech'),
            (14, 'design_infringement'),
            (15, 'geographic_indications_infringement'),
            (16, 'patent_infringement'),
            (17, 'trade_secret_infringement'),
            (18, 'violation_eu_law'),
            (19, 'violation_national_law'),
            (20, 'misinformation_disinformation_disinformation'),
            (21, 'non_consensual_image_sharing'),
            (22, 'non_consensual_items_deepfake'),
            (23, 'online_bullying_intimidation'),
            (24, 'stalking'),
            (25, 'adult_sexual_material'),
            (26, 'image_based_sexual_abuse'),
            (27, 'age_specific_restrictions_minors'),
            (28, 'child_sexual_abuse_material'),
            (29, 'grooming_sexual_enticement_minors'),
            (30, 'illegal_organizations'),
            (31, 'risk_environmental_damage'),
            (32, 'risk_public_health'),
            (33, 'terrorist_content'),
            (34, 'inauthentic_accounts'),
            (35, 'inauthentic_listings'),
            (36, 'inauthentic_user_reviews'),
            (37, 'impersonation_account_hijacking'),
            (38, 'phishing'),
            (39, 'pyramid_schemes'),
            (40, 'content_promoting_eating_disorders'),
            (41, 'self_mutilation'),
            (42, 'suicide'),
            (43, 'prohibited_products'),
            (44, 'unsafe_products'),
            (45, 'coordinated_harm'),
            (46, 'gender_based_violence'),
            (47, 'human_exploitation'),
            (48, 'human_trafficking'),
            (49, 'incitement_violence_hatred'),
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

    def test_is_individually_actionable(self):
        report = AbuseReport.objects.create(
            guid='@lol', reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE
        )
        assert report.is_individually_actionable is False
        addon = addon_factory(guid='@lol')
        user = user_factory()
        for target in (
            {'guid': addon.guid},
            {'user': user},
            {'rating': Rating.objects.create(user=user, addon=addon, rating=5)},
            {'collection': collection_factory()},
        ):
            report.update(
                reason=AbuseReport.REASONS.FEEDBACK_SPAM,
                **{
                    'guid': None,
                    'user': None,
                    'rating': None,
                    'collection': None,
                    **target,
                },
            )
            assert report.is_individually_actionable is False
            report.update(reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE)
            assert report.is_individually_actionable is True

        report.update(
            guid=addon.guid,
            user=None,
            rating=None,
            collection=None,
            addon_version=addon.current_version.version,
        )
        assert report.is_individually_actionable is True

        self.make_addon_unlisted(addon)
        assert report.is_individually_actionable is False

        self.make_addon_listed(addon)
        Version.objects.get(version=report.addon_version).delete()
        assert report.is_individually_actionable is True

        Version.unfiltered.get(version=report.addon_version).delete(hard=True)
        assert report.is_individually_actionable is False

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

    def test_illegal_category_cinder_value_no_illegal_category(self):
        report = AbuseReport()
        assert not report.illegal_category_cinder_value

    def test_illegal_subcategory_cinder_value_no_illegal_subcategory(self):
        report = AbuseReport()
        assert not report.illegal_subcategory_cinder_value


class TestAbuseReportManager(TestCase):
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

    def test_is_individually_actionable_q(self):
        actionable_reason = AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE
        user = user_factory()
        addon = addon_factory(guid='@lol')
        addon_report = AbuseReport.objects.create(
            guid=addon.guid, reason=actionable_reason
        )
        user_report = AbuseReport.objects.create(user=user, reason=actionable_reason)
        collection_report = AbuseReport.objects.create(
            collection=collection_factory(),
            reason=actionable_reason,
        )
        rating_report = AbuseReport.objects.create(
            rating=Rating.objects.create(user=user, addon=addon, rating=5),
            reason=actionable_reason,
        )
        listed_version_report = AbuseReport.objects.create(
            guid=addon.guid,
            addon_version=addon.current_version.version,
            reason=actionable_reason,
        )
        listed_deleted_version_report = AbuseReport.objects.create(
            guid=addon.guid,
            addon_version=version_factory(addon=addon, deleted=True).version,
            reason=actionable_reason,
        )

        # some reports that aren't individually actionable:
        # non-actionable reason
        AbuseReport.objects.create(
            guid=addon.guid, reason=AbuseReport.REASONS.FEEDBACK_SPAM
        )
        AbuseReport.objects.create(user=user, reason=AbuseReport.REASONS.FEEDBACK_SPAM)
        AbuseReport.objects.create(
            collection=collection_factory(), reason=AbuseReport.REASONS.FEEDBACK_SPAM
        )
        AbuseReport.objects.create(
            rating=Rating.objects.create(user=user, addon=addon, rating=5),
            reason=AbuseReport.REASONS.FEEDBACK_SPAM,
        )
        # guid doesn't exist
        AbuseReport.objects.create(guid='dfdf', reason=actionable_reason)
        # unlisted version
        AbuseReport.objects.create(
            guid=addon.guid,
            addon_version=version_factory(
                addon=addon, channel=amo.CHANNEL_UNLISTED
            ).version,
            reason=actionable_reason,
        )
        # invalid version
        AbuseReport.objects.create(
            guid=addon.guid,
            addon_version='123456',
            reason=actionable_reason,
        )
        # no version specified for addon with only unlisted versions
        AbuseReport.objects.create(
            guid=addon_factory(version_kw={'channel': amo.CHANNEL_UNLISTED}).guid,
            reason=actionable_reason,
        )
        # no version specified for addon with no public versions
        AbuseReport.objects.create(
            guid=addon_factory(file_kw={'status': amo.STATUS_DISABLED}).guid,
            reason=actionable_reason,
        )

        assert set(
            AbuseReport.objects.filter(
                AbuseReportManager.is_individually_actionable_q()
            )
        ) == {
            addon_report,
            collection_report,
            user_report,
            rating_report,
            listed_version_report,
            listed_deleted_version_report,
        }


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
            decision=ContentDecision.objects.create(
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
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon
            ),
        )
        qs = CinderJob.objects.unresolved()
        assert list(qs) == [job]

    def test_reviewer_handled(self):
        not_policy_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            location=AbuseReport.LOCATION.BOTH,
            cinder_job=CinderJob.objects.create(job_id=1),
        )
        job = CinderJob.objects.create(
            job_id=2,
            decision=ContentDecision.objects.create(
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

        not_policy_report.cinder_job.update(resolvable_in_reviewer_tools=True)
        CinderJob.objects.create(forwarded_to_job=not_policy_report.cinder_job)
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
            decision=ContentDecision.objects.create(
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

        helper = CinderJob.get_entity_helper(addon, resolved_in_reviewer_tools=True)
        # if now reason is in REVIEWER_HANDLED it will be reported differently
        assert isinstance(helper, CinderAddon)
        assert isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version_string is None

        helper = CinderJob.get_entity_helper(
            addon,
            resolved_in_reviewer_tools=True,
            addon_version_string=addon.current_version.version,
        )
        # if we got a version too we pass it on to the helper
        assert isinstance(helper, CinderAddon)
        assert isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.version_string == addon.current_version.version

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

    def check_report_with_already_removed_content(self, abuse_report):
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        CinderJob.report(abuse_report)
        assert not CinderJob.objects.exists()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['some@email.com']
        assert 'already been removed' in mail.outbox[0].body
        assert ContentDecision.objects.exists()
        decision = ContentDecision.objects.get()
        assert decision.action == DECISION_ACTIONS.AMO_CLOSED_NO_ACTION
        self.assertCloseToNow(decision.action_date)

    def test_report_with_disabled_addon(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
        )
        addon.update(status=amo.STATUS_DISABLED)
        self.check_report_with_already_removed_content(abuse_report)

    def test_report_with_banned_user(self):
        user = user_factory()
        abuse_report = AbuseReport.objects.create(
            user=user,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
        )
        user.update(banned=datetime.now())
        self.check_report_with_already_removed_content(abuse_report)

    def test_report_with_deleted_collection(self):
        collection = collection_factory()
        abuse_report = AbuseReport.objects.create(
            collection=collection,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
        )
        collection.delete()
        self.check_report_with_already_removed_content(abuse_report)

    def test_report_with_deleted_rating(self):
        rating = Rating.objects.create(addon=addon_factory(), user=user_factory())
        abuse_report = AbuseReport.objects.create(
            rating=rating,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
        )
        rating.delete()
        self.check_report_with_already_removed_content(abuse_report)

    def test_report_with_outstanding_rejection(self):
        self.test_report()
        assert len(mail.outbox) == 0
        addon = Addon.objects.get()
        CinderJob.objects.get().update(
            decision=ContentDecision.objects.create(
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

    def _test_handle_job_recreated(self, *, resolvable_in_reviewer_tools):
        addon = addon_factory()
        decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_ESCALATE_ADDON, addon=addon, notes='blah'
        )
        job = CinderJob.objects.create(
            job_id='1234', target_addon=addon, decision=decision
        )
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)
        assert not job.resolvable_in_reviewer_tools

        job.handle_job_recreated(
            new_job_id='5678', resolvable_in_reviewer_tools=resolvable_in_reviewer_tools
        )

        job.reload()
        new_job = job.forwarded_to_job
        assert new_job.job_id == '5678'
        assert list(new_job.forwarded_from_jobs.all()) == [job]
        assert new_job.resolvable_in_reviewer_tools == resolvable_in_reviewer_tools
        assert new_job.target_addon == addon
        assert report.reload().cinder_job == new_job

    def test_handle_job_recreated_for_reviewers(self):
        self._test_handle_job_recreated(resolvable_in_reviewer_tools=True)

    def test_handle_job_recreated_for_cinder(self):
        self._test_handle_job_recreated(resolvable_in_reviewer_tools=False)

    def test_handle_job_recreated_existing_forwarded_job(self):
        addon = addon_factory()
        exisiting_escalation_job = CinderJob.objects.create(
            job_id='5678', target_addon=addon
        )
        other_forwarded_job = CinderJob.objects.create(
            job_id='9999', target_addon=addon, forwarded_to_job=exisiting_escalation_job
        )

        decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_ESCALATE_ADDON, addon=addon, notes='blah'
        )
        old_job = CinderJob.objects.create(
            job_id='1234', target_addon=addon, decision=decision
        )
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=old_job)
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        )

        old_job.handle_job_recreated(
            new_job_id='5678', resolvable_in_reviewer_tools=True
        )

        old_job.reload()
        exisiting_escalation_job.reload()
        assert old_job.forwarded_to_job == exisiting_escalation_job
        assert list(exisiting_escalation_job.forwarded_from_jobs.all()) == [
            other_forwarded_job,
            old_job,
        ]
        assert list(exisiting_escalation_job.abusereport_set.all()) == [report]
        assert report.reload().cinder_job == exisiting_escalation_job
        assert NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        ).exists()  # it's not cleared
        assert NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.CINDER_ESCALATION
        ).exists()  # and neither is the CINDER_ESCALATION NHR

    def test_handle_job_recreated_existing_report_job(self):
        addon = addon_factory()
        exisiting_report_job = CinderJob.objects.create(
            job_id='5678', target_addon=addon
        )
        existing_report = AbuseReport.objects.create(
            guid=addon.guid, cinder_job=exisiting_report_job
        )

        decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_ESCALATE_ADDON, addon=addon, notes='blah'
        )
        old_job = CinderJob.objects.create(
            job_id='1234', target_addon=addon, decision=decision
        )
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=old_job)
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        )

        old_job.handle_job_recreated(
            new_job_id='5678', resolvable_in_reviewer_tools=True
        )

        old_job.reload()
        exisiting_report_job.reload()
        assert old_job.forwarded_to_job == exisiting_report_job
        assert list(exisiting_report_job.forwarded_from_jobs.all()) == [old_job]
        assert list(exisiting_report_job.abusereport_set.all()) == [
            existing_report,
            report,
        ]
        assert report.reload().cinder_job == exisiting_report_job
        assert not NeedsHumanReview.objects.filter(
            is_active=True,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        ).exists()  # it's cleared
        assert NeedsHumanReview.objects.filter(
            is_active=True,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        ).exists()  # the CINDER_ESCALATION NHR isn't though

    def test_handle_job_recreated_appeal(self):
        addon = addon_factory()
        decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_ESCALATE_ADDON, addon=addon, notes='blah'
        )
        appeal_job = CinderJob.objects.create(
            job_id='1234', target_addon=addon, decision=decision
        )
        original_job = CinderJob.objects.create(
            job_id='0000',
            target_addon=addon,
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=addon,
                notes='its okay',
                appeal_job=appeal_job,
            ),
        )
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=report
        )
        assert not appeal_job.resolvable_in_reviewer_tools

        appeal_job.handle_job_recreated(
            new_job_id='5678', resolvable_in_reviewer_tools=True
        )

        appeal_job.reload()
        new_job = appeal_job.forwarded_to_job
        assert new_job.job_id == '5678'
        assert list(new_job.forwarded_from_jobs.all()) == [appeal_job]
        assert new_job.resolvable_in_reviewer_tools
        assert new_job.target_addon == addon
        assert original_job.decision.reload().appeal_job == new_job

    def test_process_decision(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        target = user_factory()
        AbuseReport.objects.create(user=target, cinder_job=cinder_job)
        policy_a = CinderPolicy.objects.create(uuid='123-45', name='aaa', text='AAA')
        policy_b = CinderPolicy.objects.create(uuid='678-90', name='bbb', text='BBB')

        with mock.patch.object(
            ContentActionBanUser, 'process_action'
        ) as action_mock, mock.patch.object(
            ContentActionBanUser, 'notify_owners'
        ) as notify_mock:
            action_mock.return_value = (True, mock.Mock(id=999))
            cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_action=DECISION_ACTIONS.AMO_BAN_USER.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
            )
        assert cinder_job.decision.cinder_id == '12345'
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
        parent_policy = CinderPolicy.objects.create(
            uuid='678-90', name='bbb', text='BBB'
        )
        policy = CinderPolicy.objects.create(
            uuid='123-45', name='aaa', text='AAA', parent=parent_policy
        )

        with mock.patch.object(
            ContentActionBanUser, 'process_action'
        ) as action_mock, mock.patch.object(
            ContentActionBanUser, 'notify_owners'
        ) as notify_mock:
            action_mock.return_value = (True, None)
            cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_action=DECISION_ACTIONS.AMO_BAN_USER.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
            )
        assert cinder_job.decision.cinder_id == '12345'
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_BAN_USER
        assert cinder_job.decision.notes == 'teh notes'
        assert cinder_job.decision.user == target
        assert action_mock.call_count == 1
        assert notify_mock.call_count == 1
        assert list(cinder_job.decision.policies.all()) == [policy]

    def test_process_decision_escalate_addon_action(self):
        addon = addon_factory()
        cinder_job = CinderJob.objects.create(job_id='1234', target_addon=addon)
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=cinder_job)
        assert not cinder_job.resolvable_in_reviewer_tools
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '5678'},
            status=201,
        )

        cinder_job.process_decision(
            decision_cinder_id='12345',
            decision_action=DECISION_ACTIONS.AMO_ESCALATE_ADDON,
            decision_notes='blah',
            policy_ids=[],
        )
        cinder_job.reload()
        assert cinder_job.decision
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_ESCALATE_ADDON
        assert cinder_job.decision.notes == 'blah'

        new_job = cinder_job.forwarded_to_job
        assert new_job
        assert new_job.job_id == '5678'
        assert list(new_job.forwarded_from_jobs.all()) == [cinder_job]
        assert new_job.resolvable_in_reviewer_tools
        assert new_job.target_addon == addon
        assert report.reload().cinder_job == new_job

    @override_switch('dsa-cinder-forwarded-review', active=True)
    def test_process_queue_move_into_reviewer_handled(self):
        addon = addon_factory(file_kw={'is_signed': True})
        cinder_job = CinderJob.objects.create(job_id='1234', target_addon=addon)
        assert not cinder_job.resolvable_in_reviewer_tools
        assert NeedsHumanReview.objects.count() == 0

        cinder_job.process_queue_move(
            new_queue='amo-env-addon-infringement', notes='notes!'
        )

        assert cinder_job.resolvable_in_reviewer_tools is True
        assert len(mail.outbox) == 0
        assert NeedsHumanReview.objects.count() == 1
        nhr = NeedsHumanReview.objects.get()
        assert nhr.reason == NeedsHumanReview.REASONS.CINDER_ESCALATION
        assert nhr.version == addon.current_version
        assert CinderQueueMove.objects.filter(
            cinder_job=cinder_job, to_queue='amo-env-addon-infringement', notes='notes!'
        ).exists()

    def test_process_queue_move_out_of_reviewer_handled(self):
        # Not yet implemented, so just check it's silently ignored
        addon = addon_factory(file_kw={'is_signed': True})
        cinder_job = CinderJob.objects.create(
            job_id='1234', target_addon=addon, resolvable_in_reviewer_tools=True
        )
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
            version=addon.current_version,
        )

        cinder_job.process_queue_move(new_queue='amo-env-listings', notes='out')

        assert cinder_job.resolvable_in_reviewer_tools is True
        assert len(mail.outbox) == 0
        assert NeedsHumanReview.objects.count() == 1
        assert CinderQueueMove.objects.filter(
            cinder_job=cinder_job, to_queue='amo-env-listings', notes='out'
        ).exists()

    def test_process_queue_move_other_queue_movement(self):
        # we don't need to about these other queue moves, so just check it's silently
        # ignored
        addon = addon_factory(file_kw={'is_signed': True})
        cinder_job = CinderJob.objects.create(job_id='1234', target_addon=addon)

        cinder_job.process_queue_move(new_queue='amo-env-some-other-queue', notes='?')

        assert not cinder_job.resolvable_in_reviewer_tools
        assert len(mail.outbox) == 0
        assert NeedsHumanReview.objects.count() == 0
        assert CinderQueueMove.objects.filter(
            cinder_job=cinder_job, to_queue='amo-env-some-other-queue', notes='?'
        ).exists()

    def _test_resolve_job(self, activity_action, cinder_action, *, expect_target_email):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        cinder_job = CinderJob.objects.create(job_id='999')
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
            json={'uuid': uuid.uuid4().hex},
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
        self.assertCloseToNow(cinder_job.decision.action_date)
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
        assert (
            log_entry.reload().contentdecisionlog_set.get().decision
            == cinder_job.decision
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
            json={'uuid': uuid.uuid4().hex},
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
        self.assertCloseToNow(cinder_job.decision.action_date)
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
        assert (
            log_entry.reload().contentdecisionlog_set.get().decision
            == cinder_job.decision
        )

    def test_resolve_job_appeal_not_third_party(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        appeal_job = CinderJob.objects.create(
            job_id='999',
        )
        CinderJob.objects.create(
            job_id='998',
            decision=ContentDecision.objects.create(
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
            json={'uuid': uuid.uuid4().hex},
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
        self.assertCloseToNow(appeal_job.decision.action_date)
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
        assert (
            log_entry.reload().contentdecisionlog_set.get().decision
            == appeal_job.decision
        )

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
            decision=ContentDecision.objects.create(
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
            json={'uuid': uuid.uuid4().hex},
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
        # We are only removing NHR with the reason matching what we're doing.
        assert NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        ).exists()
        assert NeedsHumanReview.objects.filter(is_active=True).count() == 2
        assert (
            log_entry.reload().contentdecisionlog_set.get().decision
            == appeal_job.decision
        )

    def test_resolve_job_forwarded_from_cinder(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        cinder_job = CinderJob.objects.create(job_id='999')
        CinderJob.objects.create(forwarded_to_job=cinder_job)
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
            json={'uuid': uuid.uuid4().hex},
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
        cinder_job.reload()
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_DISABLE_ADDON
        self.assertCloseToNow(cinder_job.decision.action_date)
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

    def test_resolve_job_forwarded_to_legal(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        cinder_job = CinderJob.objects.create(job_id='999')
        CinderJob.objects.create(forwarded_to_job=cinder_job)
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
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
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': uuid.uuid4().hex},
            status=201,
        )

        log_entry = ActivityLog.objects.create(
            amo.LOG.FORCE_DISABLE,
            abuse_report.target,
            abuse_report.target.current_version,
            details={
                'comments': 'some reasoning',
                'cinder_action': 'AMO_LEGAL_FORWARD',
            },
            user=user_factory(),
        )

        cinder_job.resolve_job(log_entry=log_entry)

        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['reasoning'] == 'some reasoning'
        cinder_job.reload()
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_LEGAL_FORWARD
        self.assertCloseToNow(cinder_job.decision.action_date)
        assert len(mail.outbox) == 0
        assert not NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.CINDER_ESCALATION
        ).exists()
        assert cinder_job.forwarded_to_job
        new_job = cinder_job.forwarded_to_job
        assert not new_job.resolvable_in_reviewer_tools

    def test_all_abuse_reports(self):
        job = CinderJob.objects.create(job_id='fake_job_id')
        assert list(job.all_abuse_reports) == []

        addon = addon_factory()
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)
        assert list(job.all_abuse_reports) == [report]

        report2 = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)
        assert list(job.all_abuse_reports) == [report, report2]

        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        job.update(
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                addon=addon,
                appeal_job=appeal_job,
            )
        )

        assert appeal_job.all_abuse_reports == [report, report2]
        assert list(job.all_abuse_reports) == [report, report2]

        appeal_appeal_job = CinderJob.objects.create(job_id='fake_appeal_appeal_job_id')
        appeal_job.update(
            decision=ContentDecision.objects.create(
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

        # Now test the scenario where the original decision was an override instead of
        # the first decision. The reports should still be found by all_abuse_reports.
        job.decision.update(appeal_job=None)
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            appeal_job=appeal_job,
            override_of=job.decision,
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
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                addon=addon_factory(),
                appeal_job=appeal,
            )
        )
        job.reload()
        assert not job.is_appeal
        assert appeal.is_appeal

    def test_clear_needs_human_review_flags(self):
        def nhr_exists(reason):
            return NeedsHumanReview.objects.filter(
                reason=reason, is_active=True
            ).exists()

        addon = addon_factory()
        job = CinderJob.objects.create(
            job_id='1',
            target_addon=addon,
            resolvable_in_reviewer_tools=True,
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE, addon=addon
            ),
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL,
        )

        # for a non-forwarded or appealed job, this should clear the abuse NHR only
        job.clear_needs_human_review_flags()
        assert not nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)

        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        # if the job is forwarded, we make sure that there are no other forwarded jobs
        CinderJob.objects.create(job_id='2', target_addon=addon, forwarded_to_job=job)
        other_forward = CinderJob.objects.create(
            job_id='3',
            target_addon=addon,
            resolvable_in_reviewer_tools=True,
        )
        CinderJob.objects.create(
            job_id='4', target_addon=addon, forwarded_to_job=other_forward
        )
        job.clear_needs_human_review_flags()
        assert nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)

        # unless the other job is closed too
        other_forward.update(
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE, addon=addon
            )
        )
        job.clear_needs_human_review_flags()
        assert nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert not nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)

        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        )
        # similarly if the job is an appeal we make sure that there are no other appeals
        CinderJob.objects.create(
            job_id='5',
            target_addon=addon,
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE, addon=addon, appeal_job=job
            ),
        )
        job.forwarded_from_jobs.get().delete()
        other_appeal = CinderJob.objects.create(
            job_id='6',
            target_addon=addon,
            resolvable_in_reviewer_tools=True,
        )
        CinderJob.objects.create(
            job_id='7',
            target_addon=addon,
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=addon,
                appeal_job=other_appeal,
            ),
        )
        job.clear_needs_human_review_flags()
        assert nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)

        # unless the other job is closed too
        other_appeal.update(
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE, addon=addon
            )
        )
        job.clear_needs_human_review_flags()
        assert nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert not nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)

    def test_final_decision(self):
        addon = addon_factory()
        job = CinderJob.objects.create(job_id='1')
        assert job.final_decision is None

        decision = ContentDecision.objects.create(
            addon=addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        job.update(decision=decision)
        assert job.final_decision == decision

        override = ContentDecision.objects.create(
            addon=addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON, override_of=decision
        )
        assert job.final_decision == override


class TestContentDecisionCanBeAppealed(TestCase):
    def setUp(self):
        self.reporter = user_factory()
        self.author = user_factory()
        self.addon = addon_factory(users=[self.author])
        self.decision = ContentDecision.objects.create(
            cinder_id='fake_decision_id',
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=self.addon,
            action_date=datetime.now(),
        )

    def test_appealed_decision_already_made(self):
        assert not self.decision.appealed_decision_already_made()

        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
        )
        self.decision.update(appeal_job=appeal_job)
        assert not self.decision.appealed_decision_already_made()

        appeal_job.update(
            decision=ContentDecision.objects.create(
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
            if action not in DECISION_ACTIONS.APPEALABLE_BY_REPORTER
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
        CinderAppeal.objects.create(
            decision=self.decision, reporter_report=initial_report
        )
        assert not self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )

    def test_reporter_cant_appeal_approve_decision_overridden(self):
        initial_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )
        override = ContentDecision.objects.create(
            addon=self.addon,
            action=self.decision.action,
            override_of=self.decision,
            action_date=datetime.now(),
        )
        assert not self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )
        # but can appeal the override
        assert override.can_be_appealed(is_reporter=True, abuse_report=initial_report)

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
        report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=initial_report.cinder_job,
            reporter=user_factory(),
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        CinderAppeal.objects.create(decision=self.decision, reporter_report=report)
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
            decision=ContentDecision.objects.create(
                cinder_id='fake_appeal_decision_id',
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=self.addon,
            ),
        )
        self.decision.update(appeal_job=appeal_job)
        report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=initial_report.cinder_job,
            reporter=user_factory(),
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        CinderAppeal.objects.create(decision=self.decision, reporter_report=report)
        assert not self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )

    def test_reporter_can_appeal_appealed_decision(self):
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
            decision=ContentDecision.objects.create(
                cinder_id='fake_appeal_decision_id',
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=self.addon,
                action_date=datetime.now(),
            ),
        )
        report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        CinderAppeal.objects.create(decision=self.decision, reporter_report=report)
        self.decision.update(appeal_job=appeal_job)
        # We can end up in this situation where an AbuseReport is tied
        # to a CinderJob from an appeal, and if that somehow happens we want to
        # make sure it's possible for a reporter to appeal an appeal.
        new_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=appeal_job,
            reporter=user_factory(),
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
        self.decision.update(action_date=self.days_ago(APPEAL_EXPIRATION_DAYS + 1))
        assert not self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )

    def test_reporter_cant_appeal_when_no_action_date(self):
        initial_report = AbuseReport.objects.create(
            guid=self.addon.guid,
            cinder_job=CinderJob.objects.create(decision=self.decision),
            reporter=self.reporter,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert self.decision.can_be_appealed(
            is_reporter=True, abuse_report=initial_report
        )
        self.decision.update(action_date=None)
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

    def test_author_cant_appeal_approve_decision(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_APPROVE)
        assert not self.decision.can_be_appealed(is_reporter=False)

    def test_author_cant_appeal_disable_decision_already_appealed(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        assert self.decision.can_be_appealed(is_reporter=False)
        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        self.decision.update(appeal_job=appeal_job)
        assert not self.decision.can_be_appealed(is_reporter=False)

    def test_author_cant_appeal_disable_decision_overridden(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        assert self.decision.can_be_appealed(is_reporter=False)
        override = ContentDecision.objects.create(
            addon=self.addon,
            action=self.decision.action,
            override_of=self.decision,
            action_date=datetime.now(),
        )
        assert not self.decision.can_be_appealed(is_reporter=False)
        # but can appeal the override
        assert override.can_be_appealed(is_reporter=False)

    def test_author_can_appeal_appealed_decision(self):
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
            decision=ContentDecision.objects.create(
                cinder_id='fake_appeal_decision_id',
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                addon=self.addon,
                action_date=datetime.now(),
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


@override_switch('dsa-abuse-reports-review', active=True)
@override_switch('dsa-appeals-review', active=True)
class TestContentDecision(TestCase):
    def setUp(self):
        # It's the webhook's responsibility to do this before calling the
        # action. We need it for the ActivityLog creation to work.
        self.task_user = user_factory(pk=settings.TASK_USER_ID)
        set_user(self.task_user)

    def test_originating_job(self):
        decision = ContentDecision()
        assert decision.originating_job is None

        job = CinderJob(job_id='123')
        decision.cinder_job = job
        assert decision.originating_job == job

        new_decision = ContentDecision()
        assert new_decision.originating_job is None

        new_decision.override_of = decision
        assert new_decision.originating_job == job

        decision.cinder_job = None
        assert new_decision.originating_job is None

    def test_get_reference_id(self):
        decision = ContentDecision()
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
        decision = ContentDecision.objects.create(
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
        current_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon
        )
        assert not current_decision.is_third_party_initiated

        current_job = CinderJob.objects.create(
            decision=current_decision, job_id=uuid.uuid4().hex
        )
        current_decision.refresh_from_db()
        assert not current_decision.is_third_party_initiated

        AbuseReport.objects.create(guid=addon.guid, cinder_job=current_job)
        current_decision.refresh_from_db()
        assert current_decision.is_third_party_initiated

    def test_is_third_party_initiated_appeal(self):
        addon = addon_factory()
        current_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
        )
        current_job = CinderJob.objects.create(
            decision=current_decision, job_id=uuid.uuid4().hex
        )
        original_job = CinderJob.objects.create(
            job_id='456',
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE, addon=addon, appeal_job=current_job
            ),
        )
        assert not current_decision.is_third_party_initiated

        AbuseReport.objects.create(guid=addon.guid, cinder_job=original_job)
        assert current_decision.is_third_party_initiated

    def test_get_action_helper(self):
        addon = addon_factory()
        decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon
        )
        targets = {
            ContentActionBanUser: {'user': user_factory()},
            ContentActionDeleteCollection: {'collection': collection_factory()},
            ContentActionDeleteRating: {
                'rating': Rating.objects.create(addon=addon, user=user_factory())
            },
        }
        action_to_class = [
            (decision_action, ContentDecision.get_action_helper_class(decision_action))
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
                ContentActionTargetAppealApprove
            )
            action_existing_to_class[
                (DECISION_ACTIONS.AMO_APPROVE_VERSION, None, action)
            ] = ContentActionTargetAppealApprove
            # add appeal denial cases
            action_existing_to_class[(action, None, action)] = (
                ContentActionTargetAppealRemovalAffirmation
            )
            # add override from takedown to approve cases
            action_existing_to_class[(DECISION_ACTIONS.AMO_APPROVE, action, None)] = (
                ContentActionOverrideApprove
            )
            action_existing_to_class[
                (DECISION_ACTIONS.AMO_APPROVE_VERSION, action, None)
            ] = ContentActionOverrideApprove
            # and override from takedown to ignore
            action_existing_to_class[(DECISION_ACTIONS.AMO_IGNORE, action, None)] = (
                ContentActionOverrideApprove
            )

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
                    **targets.get(ActionClass, {'addon': addon}),
                }
            )
            helper = decision.get_action_helper(
                appealed_action=appealed_action, overridden_action=overridden_action
            )
            assert helper.__class__ == ActionClass
            assert helper.decision == decision
            assert helper.reporter_template_path == ActionClass.reporter_template_path
            assert (
                helper.reporter_appeal_template_path
                == ActionClass.reporter_appeal_template_path
            )

        action_existing_to_class_no_reporter_emails = {
            (action, action): ContentDecision.get_action_helper_class(action)
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
                    **targets.get(ActionClass, {'addon': addon}),
                }
            )
            helper = decision.get_action_helper(
                appealed_action=None, overridden_action=overridden_action
            )
            assert helper.reporter_template_path is None
            assert helper.reporter_appeal_template_path is None
            assert ActionClass.reporter_template_path is not None
            assert ActionClass.reporter_appeal_template_path is not None

    def _test_appeal_as_target(self, *, resolvable_in_reviewer_tools, expected_queue):
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
                decision=ContentDecision.objects.create(
                    cinder_id='4815162342-lost',
                    action_date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                    addon=addon,
                ),
            ),
        )
        appeal_response = responses.add(
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
        assert not hasattr(abuse_report, 'cinderappeal')
        assert CinderAppeal.objects.count() == 1
        appeal_text_obj = CinderAppeal.objects.get()
        assert appeal_text_obj.text == 'appeal text'
        assert appeal_text_obj.decision == abuse_report.cinder_job.decision
        assert appeal_text_obj.reporter_report is None

        assert appeal_response.call_count == 1
        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['reasoning'] == 'appeal text'
        assert request_body['decision_to_appeal_id'] == str(
            abuse_report.cinder_job.decision.cinder_id
        )
        assert request_body['queue_slug'] == expected_queue

        return abuse_report.cinder_job.decision.appeal_job.reload()

    def test_appeal_as_target_from_resolved_in_cinder(self):
        appeal_job = self._test_appeal_as_target(
            resolvable_in_reviewer_tools=False, expected_queue='amo-escalations'
        )
        assert not appeal_job.resolvable_in_reviewer_tools
        assert not (
            NeedsHumanReview.objects.all()
            .filter(reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
            .exists()
        )

    def test_appeal_as_target_from_resolved_in_amo(self):
        appeal_job = self._test_appeal_as_target(
            resolvable_in_reviewer_tools=True,
            expected_queue='amo-env-addon-infringement',
        )
        assert appeal_job.resolvable_in_reviewer_tools
        assert (
            NeedsHumanReview.objects.all()
            .filter(reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
            .exists()
        )
        addon = Addon.unfiltered.get()
        assert addon in Addon.unfiltered.get_queryset_for_pending_queues()

    def test_appeal_as_target_improperly_configured(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            cinder_job=CinderJob.objects.create(
                decision=ContentDecision.objects.create(
                    cinder_id='4815162342-lost',
                    action_date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                    addon=addon,
                ),
                target_addon=addon,
            ),
        )
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
        assert not hasattr(abuse_report, 'cinderappeal')

    def test_appeal_as_target_ban_improperly_configured(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            cinder_job=CinderJob.objects.create(
                decision=ContentDecision.objects.create(
                    cinder_id='4815162342-lost',
                    action_date=self.days_ago(179),
                    # This (target is an add-on, decision is a user ban) shouldn't
                    # be possible but we want to make sure this is handled
                    # explicitly.
                    action=DECISION_ACTIONS.AMO_BAN_USER,
                    addon=addon,
                ),
                target_addon=addon,
            ),
        )
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
        assert not hasattr(abuse_report, 'cinderappeal')

    def test_appeal_as_target_banned(self):
        target = user_factory()
        abuse_report = AbuseReport.objects.create(
            user=target,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            cinder_job=CinderJob.objects.create(
                decision=ContentDecision.objects.create(
                    cinder_id='4815162342-lost',
                    action_date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_BAN_USER,
                    user=target,
                )
            ),
        )
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
        assert not hasattr(abuse_report, 'cinderappeal')

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
                decision=ContentDecision.objects.create(
                    cinder_id='4815162342-lost',
                    action_date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_APPROVE,
                    addon=addon,
                ),
            )
        )
        appeal_response = responses.add(
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
        assert abuse_report.cinderappeal
        assert CinderAppeal.objects.count() == 1
        appeal_text_obj = CinderAppeal.objects.get()
        assert appeal_text_obj.text == 'appeal text'
        assert appeal_text_obj.decision == abuse_report.cinder_job.decision
        assert appeal_text_obj.reporter_report == abuse_report

        assert appeal_response.call_count == 1
        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['reasoning'] == 'appeal text'
        assert request_body['decision_to_appeal_id'] == str(
            abuse_report.cinder_job.decision.cinder_id
        )
        assert request_body['queue_slug'] == 'amo-escalations'

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
                decision=ContentDecision.objects.create(
                    cinder_id='4815162342-lost',
                    action_date=self.days_ago(179),
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
        assert abuse_report.cinderappeal

    def test_appeal_as_reporter_specific_version(self):
        addon = addon_factory(version_kw={'human_review_date': datetime.now()})
        original_version = addon.current_version
        version_factory(addon=addon, human_review_date=datetime.now())
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=user_factory(),
            addon_version=original_version.version,
        )
        abuse_report.update(
            cinder_job=CinderJob.objects.create(
                target_addon=addon,
                resolvable_in_reviewer_tools=True,
                decision=ContentDecision.objects.create(
                    cinder_id='4815162342-lost',
                    action_date=self.days_ago(179),
                    action=DECISION_ACTIONS.AMO_APPROVE,
                    addon=addon,
                ),
            )
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '2432615184-tsol'},
            status=201,
        )
        assert not original_version.due_date

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
        assert abuse_report.cinderappeal
        assert CinderAppeal.objects.count() == 1
        appeal_text_obj = CinderAppeal.objects.get()
        assert appeal_text_obj.text == 'appeal text'
        assert appeal_text_obj.decision == abuse_report.cinder_job.decision
        assert appeal_text_obj.reporter_report == abuse_report
        assert original_version.reload().due_date

    def test_appeal_improperly_configured_reporter(self):
        cinder_job = CinderJob.objects.create(
            decision=ContentDecision.objects.create(
                cinder_id='4815162342-lost',
                action_date=self.days_ago(179),
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
            decision=ContentDecision.objects.create(
                cinder_id='4815162342-lost',
                action_date=self.days_ago(179),
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
        expect_create_decision_call,
        expect_create_job_decision_call,
        extra_log_details=None,
        expected_decision_object_count=1,
    ):
        create_decision_response = responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        cinder_job_id = (job := getattr(decision, 'cinder_job', None)) and job.job_id
        create_job_decision_response = responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{cinder_job_id}/decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        policies = [
            CinderPolicy.objects.create(
                name='policy', uuid='12345678', text='some policy text'
            )
        ]
        entity_helper = CinderJob.get_entity_helper(
            decision.addon, resolved_in_reviewer_tools=True
        )
        addon_version = decision.addon.versions.all()[0]
        cinder_action = cinder_action or getattr(activity_action, 'cinder_action', None)
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
        assert decision.notes == 'some review text'
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
            self.assertCloseToNow(decision.action_date)
            assert list(decision.policies.all()) == policies
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
            self.assertCloseToNow(decision.action_date)
            assert list(decision.policies.all()) == policies
            assert decision.id
        else:
            assert create_decision_response.call_count == 0
            assert create_job_decision_response.call_count == 0
            assert CinderPolicy.contentdecision_set.through.objects.count() == 0
            assert not decision.id
        assert ContentDecision.objects.count() == expected_decision_object_count
        if expected_decision_object_count > 0:
            assert log_entry.reload().contentdecisionlog_set.get().decision == decision

        if expect_email:
            assert len(mail.outbox) == 1
            assert mail.outbox[0].to == [decision.addon.authors.first().email]
            assert str(log_entry.id) in mail.outbox[0].extra_headers['Message-ID']
            assert str(addon_version) in mail.outbox[0].body
            assert 'days' not in mail.outbox[0].body
            assert 'some review text' in mail.outbox[0].body
            assert 'some policy text' not in mail.outbox[0].body
            AttachmentLog.objects.create(
                activity_log=log_entry,
                file=ContentFile('Pseudo File', name='attachment.txt'),
            )
            decision.notify_reviewer_decision(
                log_entry=log_entry,
                entity_helper=entity_helper,
            )
            assert 'An attachment was provided.' not in mail.outbox[0].body
            assert 'To respond or view the file,' not in mail.outbox[0].body
            assert 'An attachment was provided.' in mail.outbox[1].body
            assert 'To respond or view the file,' in mail.outbox[1].body
        else:
            assert len(mail.outbox) == 0

    def test_notify_reviewer_decision_first_decision(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = ContentDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            expect_create_decision_call=True,
            expect_create_job_decision_call=False,
        )
        assert parse.quote(f'/firefox/addon/{addon.slug}/') in mail.outbox[0].body
        assert '/developers/' not in mail.outbox[0].body

    def test_notify_reviewer_decision_override_decision(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        previous_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            action_date=datetime.now(),
        )
        decision = ContentDecision(addon=addon, override_of=previous_decision)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            expect_create_decision_call=True,
            expect_create_job_decision_call=False,
            expected_decision_object_count=2,
        )
        assert parse.quote(f'/firefox/addon/{addon.slug}/') in mail.outbox[0].body
        assert '/developers/' not in mail.outbox[0].body

    def test_notify_reviewer_decision_unlisted_version(self):
        addon_developer = user_factory()
        addon = addon_factory(
            users=[addon_developer], version_kw={'channel': amo.CHANNEL_UNLISTED}
        )
        decision = ContentDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            expect_create_decision_call=True,
            expect_create_job_decision_call=False,
        )
        assert '/firefox/' not in mail.outbox[0].body
        assert (
            f'{settings.SITE_URL}/en-US/developers/addon/{addon.id}/'
            in mail.outbox[0].body
        )

    def test_notify_reviewer_decision_first_decision_no_email_to_owner(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = ContentDecision(addon=addon)
        decision.cinder_job = CinderJob.objects.create(job_id='1234')
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.CONFIRM_AUTO_APPROVED,
            DECISION_ACTIONS.AMO_APPROVE,
            expect_email=False,
            expect_create_decision_call=False,
            expect_create_job_decision_call=True,
        )

    def test_notify_reviewer_decision_override_decision_no_email_to_owner(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        previous_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            action_date=datetime.now(),
        )
        previous_decision.cinder_job = CinderJob.objects.create(
            job_id='1234', decision=previous_decision
        )
        decision = ContentDecision(addon=addon, override_of=previous_decision)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.CONFIRM_AUTO_APPROVED,
            DECISION_ACTIONS.AMO_APPROVE,
            expect_email=False,
            expect_create_decision_call=True,
            expect_create_job_decision_call=False,
            expected_decision_object_count=2,
        )

    def test_no_create_decision_for_approve_without_a_job(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = ContentDecision(addon=addon)
        assert not hasattr(decision, 'cinder_job')
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.APPROVE_VERSION,
            DECISION_ACTIONS.AMO_APPROVE_VERSION,
            expect_create_decision_call=False,
            expect_create_job_decision_call=False,
            expect_email=True,
            expected_decision_object_count=0,
        )

    def test_notify_reviewer_decision_auto_approve_email_for_non_human_review(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = ContentDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.APPROVE_VERSION,
            DECISION_ACTIONS.AMO_APPROVE_VERSION,
            expect_email=True,
            expect_create_decision_call=False,
            expect_create_job_decision_call=False,
            expected_decision_object_count=0,
            extra_log_details={'human_review': False},
        )
        assert 'automatically screened and tentatively approved' in mail.outbox[0].body

    def test_notify_reviewer_decision_auto_approve_email_for_human_review(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = ContentDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.APPROVE_VERSION,
            DECISION_ACTIONS.AMO_APPROVE_VERSION,
            expect_email=True,
            expect_create_decision_call=False,
            expect_create_job_decision_call=False,
            expected_decision_object_count=0,
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
            ContentDecision().notify_reviewer_decision(
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
            ContentDecision().notify_reviewer_decision(
                log_entry=log_entry, entity_helper=None
            )

    def test_notify_reviewer_decision_rejection_blocking(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = ContentDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            expect_create_decision_call=True,
            expect_create_job_decision_call=False,
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
            "users who have previously installed those versions won't be able to"
            in mail.outbox[0].body
        )
        assert (
            'You may upload a new version which addresses the policy violation(s)'
            in mail.outbox[0].body
        )

    def test_notify_reviewer_decision_rejection_blocking_addon_being_disabled(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = ContentDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            expect_create_decision_call=True,
            expect_create_job_decision_call=False,
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
            "users who have previously installed those versions won't be able to"
            in mail.outbox[0].body
        )
        assert (
            'You may upload a new version which addresses the policy violation(s)'
            not in mail.outbox[0].body
        )

    def test_notify_reviewer_decision_rejection_addon_already_disabled(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer], status=amo.STATUS_DISABLED)
        decision = ContentDecision(addon=addon)
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REJECT_VERSION,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            expect_create_decision_call=True,
            expect_create_job_decision_call=False,
        )
        assert (
            'Users who have previously installed those versions will be able to'
            in mail.outbox[0].body
        )
        assert (
            "users who have previously installed those versions won't be able to"
            not in mail.outbox[0].body
        )
        assert (
            'You may upload a new version which addresses the policy violation(s)'
            not in mail.outbox[0].body
        )

    def test_notify_reviewer_decision_legal_forward(self):
        """Test a reviewer "decision" to forward to legal. Because there is no job there
        is no decision though, so we don't expect any decision to be notified to Cinder.
        """
        addon_developer = user_factory()
        # Set to disabled because we already don't create decisions for approvals.
        addon = addon_factory(users=[addon_developer], status=amo.STATUS_DISABLED)
        decision = ContentDecision(addon=addon)
        # Check there isn't a job already so our .get later isn't a false positive.
        assert not CinderJob.objects.exists()
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '123456'},
            status=201,
        )
        self._test_notify_reviewer_decision(
            decision,
            amo.LOG.REQUEST_LEGAL,
            None,
            # as above, we arne't making a decision on a job, so no call is expected
            expect_create_decision_call=False,
            expect_create_job_decision_call=False,
            expected_decision_object_count=0,
            # and certainly no email to the developer
            expect_email=False,
        )
        assert CinderJob.objects.get().job_id == '123456'

    def _test_process_action_ban_user_outcome(self, decision):
        self.assertCloseToNow(decision.action_date)
        self.assertCloseToNow(decision.user.reload().banned)
        assert (
            ActivityLog.objects.filter(action=amo.LOG.ADMIN_USER_BANNED.id).count() == 1
        )
        assert 'appeal' in mail.outbox[0].body

    def test_process_action_ban_user_held(self):
        user = user_factory(email='superstarops@mozilla.com')
        decision = ContentDecision.objects.create(
            user=user, action=DECISION_ACTIONS.AMO_BAN_USER
        )
        assert decision.action_date is None
        decision.process_action()
        assert decision.action_date is None
        assert not user.reload().banned
        assert (
            ActivityLog.objects.filter(
                action=amo.LOG.HELD_ACTION_ADMIN_USER_BANNED.id
            ).count()
            == 1
        )
        assert len(mail.outbox) == 0

        decision.process_action(release_hold=True)
        self._test_process_action_ban_user_outcome(decision)

    def test_process_action_ban_user(self):
        user = user_factory()
        decision = ContentDecision.objects.create(
            user=user, action=DECISION_ACTIONS.AMO_BAN_USER
        )
        assert decision.action_date is None
        decision.process_action()
        self._test_process_action_ban_user_outcome(decision)

    def _test_process_action_disable_addon_outcome(self, decision):
        self.assertCloseToNow(decision.action_date)
        assert decision.addon.reload().status == amo.STATUS_DISABLED
        assert ActivityLog.objects.filter(action=amo.LOG.FORCE_DISABLE.id).count() == 1
        assert 'appeal' in mail.outbox[0].body

    def test_process_action_disable_addon_held(self):
        addon = addon_factory(users=[user_factory()])
        self.make_addon_promoted(addon, RECOMMENDED, approve_version=True)
        decision = ContentDecision.objects.create(
            addon=addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        assert decision.action_date is None
        decision.process_action()
        assert decision.action_date is None
        assert addon.reload().status == amo.STATUS_APPROVED
        assert (
            ActivityLog.objects.filter(
                action=amo.LOG.HELD_ACTION_FORCE_DISABLE.id
            ).count()
            == 1
        )
        assert len(mail.outbox) == 0

        decision.process_action(release_hold=True)
        self._test_process_action_disable_addon_outcome(decision)

    def test_process_action_disable_addon(self):
        addon = addon_factory(users=[user_factory()])
        decision = ContentDecision.objects.create(
            addon=addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        assert decision.action_date is None
        decision.process_action()
        self._test_process_action_disable_addon_outcome(decision)

    def _test_process_action_delete_collection_outcome(self, decision):
        self.assertCloseToNow(decision.action_date)
        assert decision.collection.reload().deleted
        assert (
            ActivityLog.objects.filter(action=amo.LOG.COLLECTION_DELETED.id).count()
            == 1
        )
        assert 'appeal' in mail.outbox[0].body

    def test_process_action_delete_collection_held(self):
        collection = collection_factory(author=self.task_user)
        decision = ContentDecision.objects.create(
            collection=collection, action=DECISION_ACTIONS.AMO_DELETE_COLLECTION
        )
        assert decision.action_date is None
        decision.process_action()
        assert decision.action_date is None
        assert not collection.reload().deleted
        assert (
            ActivityLog.objects.filter(
                action=amo.LOG.HELD_ACTION_COLLECTION_DELETED.id
            ).count()
            == 1
        )
        assert len(mail.outbox) == 0

        decision.process_action(release_hold=True)
        self._test_process_action_delete_collection_outcome(decision)

    def test_process_action_delete_collection(self):
        collection = collection_factory(author=user_factory())
        decision = ContentDecision.objects.create(
            collection=collection, action=DECISION_ACTIONS.AMO_DELETE_COLLECTION
        )
        assert decision.action_date is None
        decision.process_action()
        self._test_process_action_delete_collection_outcome(decision)

    def _test_process_action_delete_rating_outcome(self, decision):
        self.assertCloseToNow(decision.action_date)
        assert decision.rating.reload().deleted
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_RATING.id).count() == 1
        assert 'appeal' in mail.outbox[0].body

    def test_process_action_delete_rating_held(self):
        user = user_factory()
        addon = addon_factory(users=[user])
        rating = Rating.objects.create(
            addon=addon,
            user=user,
            body='reply',
            reply_to=Rating.objects.create(
                addon=addon, user=user_factory(), body='sdsd'
            ),
        )
        decision = ContentDecision.objects.create(
            rating=rating, action=DECISION_ACTIONS.AMO_DELETE_RATING
        )
        self.make_addon_promoted(rating.addon, RECOMMENDED, approve_version=True)
        assert decision.action_date is None
        mail.outbox.clear()

        decision.process_action()
        assert decision.action_date is None
        assert not rating.reload().deleted
        assert (
            ActivityLog.objects.filter(
                action=amo.LOG.HELD_ACTION_DELETE_RATING.id
            ).count()
            == 1
        )
        assert len(mail.outbox) == 0

        decision.process_action(release_hold=True)
        self._test_process_action_delete_rating_outcome(decision)

    def test_process_action_delete_rating(self):
        rating = Rating.objects.create(addon=addon_factory(), user=user_factory())
        decision = ContentDecision.objects.create(
            rating=rating, action=DECISION_ACTIONS.AMO_DELETE_RATING
        )
        assert decision.action_date is None
        decision.process_action()
        self._test_process_action_delete_rating_outcome(decision)

    def test_get_target_review_url(self):
        addon = addon_factory()
        decision = ContentDecision.objects.create(
            addon=addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        assert decision.get_target_review_url() == reverse(
            'reviewers.decision_review', args=(decision.id,)
        )

    def test_get_target_display(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(), action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        assert decision.get_target_display() == 'Extension'

        decision.update(addon=None, user=user_factory())
        assert decision.get_target_display() == 'User profile'

        decision.update(user=None, collection=collection_factory())
        assert decision.get_target_display() == 'Collection'

        decision.update(
            collection=None,
            rating=Rating.objects.create(addon=addon_factory(), user=user_factory()),
        )
        assert decision.get_target_display() == 'Rating'

    def test_get_target_name(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(), action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        assert decision.get_target_name() == str(decision.addon.name)

        decision.update(addon=None, user=user_factory())
        assert decision.get_target_name() == decision.user.name

        decision.update(user=None, collection=collection_factory())
        assert decision.get_target_name() == decision.collection.name

        decision.update(
            collection=None,
            rating=Rating.objects.create(
                addon=addon_factory(), user=user_factory(), body='something'
            ),
        )
        assert (
            decision.get_target_name()
            == f'"something" for {decision.rating.addon.name}'
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    'illegal_category,expected',
    [
        (None, None),
        (
            ILLEGAL_CATEGORIES.ANIMAL_WELFARE,
            'STATEMENT_CATEGORY_ANIMAL_WELFARE',
        ),
        (
            ILLEGAL_CATEGORIES.CONSUMER_INFORMATION,
            'STATEMENT_CATEGORY_CONSUMER_INFORMATION',
        ),
        (
            ILLEGAL_CATEGORIES.DATA_PROTECTION_AND_PRIVACY_VIOLATIONS,
            'STATEMENT_CATEGORY_DATA_PROTECTION_AND_PRIVACY_VIOLATIONS',
        ),
        (
            ILLEGAL_CATEGORIES.ILLEGAL_OR_HARMFUL_SPEECH,
            'STATEMENT_CATEGORY_ILLEGAL_OR_HARMFUL_SPEECH',
        ),
        (
            ILLEGAL_CATEGORIES.INTELLECTUAL_PROPERTY_INFRINGEMENTS,
            'STATEMENT_CATEGORY_INTELLECTUAL_PROPERTY_INFRINGEMENTS',
        ),
        (
            ILLEGAL_CATEGORIES.NEGATIVE_EFFECTS_ON_CIVIC_DISCOURSE_OR_ELECTIONS,
            'STATEMENT_CATEGORY_NEGATIVE_EFFECTS_ON_CIVIC_DISCOURSE_OR_ELECTIONS',
        ),
        (
            ILLEGAL_CATEGORIES.NON_CONSENSUAL_BEHAVIOUR,
            'STATEMENT_CATEGORY_NON_CONSENSUAL_BEHAVIOUR',
        ),
        (
            ILLEGAL_CATEGORIES.PORNOGRAPHY_OR_SEXUALIZED_CONTENT,
            'STATEMENT_CATEGORY_PORNOGRAPHY_OR_SEXUALIZED_CONTENT',
        ),
        (
            ILLEGAL_CATEGORIES.PROTECTION_OF_MINORS,
            'STATEMENT_CATEGORY_PROTECTION_OF_MINORS',
        ),
        (
            ILLEGAL_CATEGORIES.RISK_FOR_PUBLIC_SECURITY,
            'STATEMENT_CATEGORY_RISK_FOR_PUBLIC_SECURITY',
        ),
        (
            ILLEGAL_CATEGORIES.SCAMS_AND_FRAUD,
            'STATEMENT_CATEGORY_SCAMS_AND_FRAUD',
        ),
        (ILLEGAL_CATEGORIES.SELF_HARM, 'STATEMENT_CATEGORY_SELF_HARM'),
        (
            ILLEGAL_CATEGORIES.UNSAFE_AND_PROHIBITED_PRODUCTS,
            'STATEMENT_CATEGORY_UNSAFE_AND_PROHIBITED_PRODUCTS',
        ),
        (ILLEGAL_CATEGORIES.VIOLENCE, 'STATEMENT_CATEGORY_VIOLENCE'),
        (ILLEGAL_CATEGORIES.OTHER, 'STATEMENT_CATEGORY_OTHER'),
    ],
)
def test_illegal_category_cinder_value(illegal_category, expected):
    addon = addon_factory()
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        illegal_category=illegal_category,
    )
    assert abuse_report.illegal_category_cinder_value == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    'illegal_subcategory,expected',
    [
        (None, None),
        (ILLEGAL_SUBCATEGORIES.OTHER, 'KEYWORD_OTHER'),
        (
            ILLEGAL_SUBCATEGORIES.INSUFFICIENT_INFORMATION_ON_TRADERS,
            'KEYWORD_INSUFFICIENT_INFORMATION_ON_TRADERS',
        ),
        (
            ILLEGAL_SUBCATEGORIES.NONCOMPLIANCE_PRICING,
            'KEYWORD_NONCOMPLIANCE_PRICING',
        ),
        (
            ILLEGAL_SUBCATEGORIES.HIDDEN_ADVERTISEMENT,
            'KEYWORD_HIDDEN_ADVERTISEMENT',
        ),
        (
            ILLEGAL_SUBCATEGORIES.MISLEADING_INFO_GOODS_SERVICES,
            'KEYWORD_MISLEADING_INFO_GOODS_SERVICES',
        ),
        (
            ILLEGAL_SUBCATEGORIES.MISLEADING_INFO_CONSUMER_RIGHTS,
            'KEYWORD_MISLEADING_INFO_CONSUMER_RIGHTS',
        ),
        (
            ILLEGAL_SUBCATEGORIES.BIOMETRIC_DATA_BREACH,
            'KEYWORD_BIOMETRIC_DATA_BREACH',
        ),
        (
            ILLEGAL_SUBCATEGORIES.MISSING_PROCESSING_GROUND,
            'KEYWORD_MISSING_PROCESSING_GROUND',
        ),
        (
            ILLEGAL_SUBCATEGORIES.RIGHT_TO_BE_FORGOTTEN,
            'KEYWORD_RIGHT_TO_BE_FORGOTTEN',
        ),
        (
            ILLEGAL_SUBCATEGORIES.DATA_FALSIFICATION,
            'KEYWORD_DATA_FALSIFICATION',
        ),
        (ILLEGAL_SUBCATEGORIES.DEFAMATION, 'KEYWORD_DEFAMATION'),
        (ILLEGAL_SUBCATEGORIES.DISCRIMINATION, 'KEYWORD_DISCRIMINATION'),
        (ILLEGAL_SUBCATEGORIES.HATE_SPEECH, 'KEYWORD_HATE_SPEECH'),
        (
            ILLEGAL_SUBCATEGORIES.DESIGN_INFRINGEMENT,
            'KEYWORD_DESIGN_INFRINGEMENT',
        ),
        (
            ILLEGAL_SUBCATEGORIES.GEOGRAPHIC_INDICATIONS_INFRINGEMENT,
            'KEYWORD_GEOGRAPHIC_INDICATIONS_INFRINGEMENT',
        ),
        (
            ILLEGAL_SUBCATEGORIES.PATENT_INFRINGEMENT,
            'KEYWORD_PATENT_INFRINGEMENT',
        ),
        (
            ILLEGAL_SUBCATEGORIES.TRADE_SECRET_INFRINGEMENT,
            'KEYWORD_TRADE_SECRET_INFRINGEMENT',
        ),
        (
            ILLEGAL_SUBCATEGORIES.VIOLATION_EU_LAW,
            'KEYWORD_VIOLATION_EU_LAW',
        ),
        (
            ILLEGAL_SUBCATEGORIES.VIOLATION_NATIONAL_LAW,
            'KEYWORD_VIOLATION_NATIONAL_LAW',
        ),
        (
            ILLEGAL_SUBCATEGORIES.MISINFORMATION_DISINFORMATION_DISINFORMATION,
            'KEYWORD_MISINFORMATION_DISINFORMATION_DISINFORMATION',
        ),
        (
            ILLEGAL_SUBCATEGORIES.NON_CONSENSUAL_IMAGE_SHARING,
            'KEYWORD_NON_CONSENSUAL_IMAGE_SHARING',
        ),
        (
            ILLEGAL_SUBCATEGORIES.NON_CONSENSUAL_ITEMS_DEEPFAKE,
            'KEYWORD_NON_CONSENSUAL_ITEMS_DEEPFAKE',
        ),
        (
            ILLEGAL_SUBCATEGORIES.ONLINE_BULLYING_INTIMIDATION,
            'KEYWORD_ONLINE_BULLYING_INTIMIDATION',
        ),
        (ILLEGAL_SUBCATEGORIES.STALKING, 'KEYWORD_STALKING'),
        (
            ILLEGAL_SUBCATEGORIES.ADULT_SEXUAL_MATERIAL,
            'KEYWORD_ADULT_SEXUAL_MATERIAL',
        ),
        (
            ILLEGAL_SUBCATEGORIES.IMAGE_BASED_SEXUAL_ABUSE,
            'KEYWORD_IMAGE_BASED_SEXUAL_ABUSE',
        ),
        (
            ILLEGAL_SUBCATEGORIES.AGE_SPECIFIC_RESTRICTIONS_MINORS,
            'KEYWORD_AGE_SPECIFIC_RESTRICTIONS_MINORS',
        ),
        (
            ILLEGAL_SUBCATEGORIES.CHILD_SEXUAL_ABUSE_MATERIAL,
            'KEYWORD_CHILD_SEXUAL_ABUSE_MATERIAL',
        ),
        (
            ILLEGAL_SUBCATEGORIES.GROOMING_SEXUAL_ENTICEMENT_MINORS,
            'KEYWORD_GROOMING_SEXUAL_ENTICEMENT_MINORS',
        ),
        (
            ILLEGAL_SUBCATEGORIES.ILLEGAL_ORGANIZATIONS,
            'KEYWORD_ILLEGAL_ORGANIZATIONS',
        ),
        (
            ILLEGAL_SUBCATEGORIES.RISK_ENVIRONMENTAL_DAMAGE,
            'KEYWORD_RISK_ENVIRONMENTAL_DAMAGE',
        ),
        (
            ILLEGAL_SUBCATEGORIES.RISK_PUBLIC_HEALTH,
            'KEYWORD_RISK_PUBLIC_HEALTH',
        ),
        (
            ILLEGAL_SUBCATEGORIES.TERRORIST_CONTENT,
            'KEYWORD_TERRORIST_CONTENT',
        ),
        (
            ILLEGAL_SUBCATEGORIES.INAUTHENTIC_ACCOUNTS,
            'KEYWORD_INAUTHENTIC_ACCOUNTS',
        ),
        (
            ILLEGAL_SUBCATEGORIES.INAUTHENTIC_LISTINGS,
            'KEYWORD_INAUTHENTIC_LISTINGS',
        ),
        (
            ILLEGAL_SUBCATEGORIES.INAUTHENTIC_USER_REVIEWS,
            'KEYWORD_INAUTHENTIC_USER_REVIEWS',
        ),
        (
            ILLEGAL_SUBCATEGORIES.IMPERSONATION_ACCOUNT_HIJACKING,
            'KEYWORD_IMPERSONATION_ACCOUNT_HIJACKING',
        ),
        (ILLEGAL_SUBCATEGORIES.PHISHING, 'KEYWORD_PHISHING'),
        (ILLEGAL_SUBCATEGORIES.PYRAMID_SCHEMES, 'KEYWORD_PYRAMID_SCHEMES'),
        (
            ILLEGAL_SUBCATEGORIES.CONTENT_PROMOTING_EATING_DISORDERS,
            'KEYWORD_CONTENT_PROMOTING_EATING_DISORDERS',
        ),
        (ILLEGAL_SUBCATEGORIES.SELF_MUTILATION, 'KEYWORD_SELF_MUTILATION'),
        (ILLEGAL_SUBCATEGORIES.SUICIDE, 'KEYWORD_SUICIDE'),
        (
            ILLEGAL_SUBCATEGORIES.PROHIBITED_PRODUCTS,
            'KEYWORD_PROHIBITED_PRODUCTS',
        ),
        (ILLEGAL_SUBCATEGORIES.UNSAFE_PRODUCTS, 'KEYWORD_UNSAFE_PRODUCTS'),
        (
            ILLEGAL_SUBCATEGORIES.COORDINATED_HARM,
            'KEYWORD_COORDINATED_HARM',
        ),
        (
            ILLEGAL_SUBCATEGORIES.GENDER_BASED_VIOLENCE,
            'KEYWORD_GENDER_BASED_VIOLENCE',
        ),
        (
            ILLEGAL_SUBCATEGORIES.HUMAN_EXPLOITATION,
            'KEYWORD_HUMAN_EXPLOITATION',
        ),
        (
            ILLEGAL_SUBCATEGORIES.HUMAN_TRAFFICKING,
            'KEYWORD_HUMAN_TRAFFICKING',
        ),
        (
            ILLEGAL_SUBCATEGORIES.INCITEMENT_VIOLENCE_HATRED,
            'KEYWORD_INCITEMENT_VIOLENCE_HATRED',
        ),
    ],
)
def test_illegal_subcategory_cinder_value(illegal_subcategory, expected):
    addon = addon_factory()
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        illegal_subcategory=illegal_subcategory,
    )
    assert abuse_report.illegal_subcategory_cinder_value == expected
