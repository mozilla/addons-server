import json
import uuid
from datetime import datetime, timedelta
from unittest import mock

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
    DECISION_SOURCES,
    ILLEGAL_CATEGORIES,
    ILLEGAL_SUBCATEGORIES,
)
from olympia.constants.permissions import ADDONS_HIGH_IMPACT_APPROVE
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.core import set_user
from olympia.ratings.models import Rating
from olympia.reviewers.models import NeedsHumanReview
from olympia.users.models import UserProfile
from olympia.versions.models import Version, VersionReviewerFlags

from ..actions import (
    CONTENT_ACTION_FROM_DECISION_ACTION,
    ContentActionBanUser,
    ContentActionDeleteCollection,
    ContentActionDeleteRating,
    ContentActionDisableAddon,
    ContentActionOverrideApprove,
    ContentActionTargetAppealApprove,
    ContentActionTargetAppealRemovalAffirmation,
)
from ..cinder import (
    CinderAddon,
    CinderAddonHandledByLegal,
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
        # open job
        job = CinderJob.objects.create(job_id='1')
        addon = addon_factory()
        # closed job
        resolved = CinderJob.objects.create(job_id='2')
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon, cinder_job=resolved
        )
        assert list(CinderJob.objects.unresolved()) == [job]

        # this job has been requeued, so is now unresolved again
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_REQUEUE,
            addon=addon,
            override_of=resolved.final_decision,
            cinder_job=resolved,
        )
        assert list(CinderJob.objects.unresolved()) == [job, resolved]

        # but not after it's resolved again
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            override_of=resolved.final_decision,
            cinder_job=resolved,
        )
        assert list(CinderJob.objects.unresolved()) == [job]

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
        CinderQueueMove.objects.create(
            cinder_job=not_policy_report.cinder_job, to_queue='?'
        )
        qs = CinderJob.objects.resolvable_in_reviewer_tools()
        assert list(qs) == [not_policy_report.cinder_job, job, appeal_job]


class TestCinderJob(TestCase):
    def setUp(self):
        user_factory(id=settings.TASK_USER_ID)

    def test_decision_and_final_decision(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        addon = addon_factory()
        first = ContentDecision.objects.create(
            addon=addon, action=DECISION_ACTIONS.AMO_APPROVE, cinder_job=cinder_job
        )
        second = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            cinder_job=cinder_job,
            override_of=first,
        )
        third = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            cinder_job=cinder_job,
            override_of=second,
        )
        assert cinder_job.decision == first
        assert cinder_job.final_decision == third

    def test_target(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        # edge case, but handle having no associated abuse_reports, decisions or appeals
        assert cinder_job.target is None

        # case when CinderJob.target_addon is set
        addon = addon_factory()
        cinder_job.update(target_addon=addon)
        assert cinder_job.target_addon == cinder_job.target == addon

        # case when there is already a decision
        cinder_job.update(target_addon=None)
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_APPROVE, addon=addon, cinder_job=cinder_job
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
        assert helper.versions_strings is None

        helper = CinderJob.get_entity_helper(
            addon,
            resolved_in_reviewer_tools=True,
            addon_version_string=addon.current_version.version,
        )
        # if we got a version too we pass it on to the helper
        assert isinstance(helper, CinderAddon)
        assert isinstance(helper, CinderAddonHandledByReviewers)
        assert helper.addon == addon
        assert helper.versions_strings == [addon.current_version.version]

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

    def test_should_auto_resolve_removed(self):
        job = CinderJob.objects.create(resolvable_in_reviewer_tools=False)
        abuse_report = AbuseReport.objects.create(
            collection=collection_factory(),
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
            cinder_job=job,
        )
        assert not job.should_auto_resolve()
        abuse_report.collection.update(deleted=True)
        assert job.should_auto_resolve()

        abuse_report.update(collection=None, user=user_factory())
        assert not job.should_auto_resolve()
        abuse_report.user.update(banned=datetime.now())
        assert job.should_auto_resolve()

        abuse_report.update(
            user=None,
            rating=Rating.objects.create(user=abuse_report.user, addon=addon_factory()),
        )
        assert not job.should_auto_resolve()
        abuse_report.rating.update(deleted=True)
        assert job.should_auto_resolve()

        addon = abuse_report.rating.addon
        abuse_report.update(rating=None, guid=addon.guid)
        assert not job.should_auto_resolve()
        addon.update(status=amo.STATUS_DISABLED)
        assert job.should_auto_resolve()

        # appeal jobs are excluded though - they could be appealling the removal
        ContentDecision.objects.create(
            addon=addon, action=DECISION_ACTIONS.AMO_DISABLE_ADDON, appeal_job=job
        )
        assert not job.should_auto_resolve()

    def test_should_auto_resolve_human_reviewed(self):
        addon = addon_factory()
        job = CinderJob.objects.create(
            target_addon=addon, resolvable_in_reviewer_tools=True
        )
        abuse_already_moderated = {
            'reason': AbuseReport.REASONS.POLICY_VIOLATION,
            'location': AbuseReport.LOCATION.ADDON,
            'addon_version': None,
        }
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reporter_email='some@email.com',
            cinder_job=job,
            **abuse_already_moderated,
        )
        addon.current_version.update(human_review_date=datetime.now())
        abuse_report.update(**abuse_already_moderated)
        # first, success case for non addon version specified
        assert job.should_auto_resolve()

        # not a reviewer handled report/job
        job.update(resolvable_in_reviewer_tools=False)
        assert not job.should_auto_resolve()

        # for a legal reason
        abuse_report.update(
            **{**abuse_already_moderated, 'reason': AbuseReport.REASONS.ILLEGAL}
        )
        job.update(resolvable_in_reviewer_tools=True)
        assert not job.should_auto_resolve()

        # other non-legal reasons are fine though
        abuse_report.update(
            **{**abuse_already_moderated, 'reason': AbuseReport.REASONS.SOMETHING_ELSE}
        )
        assert job.should_auto_resolve()

        # no current_version
        abuse_report.update(**abuse_already_moderated)
        addon.update(_current_version=None)
        assert not job.should_auto_resolve()

        # or if not already reviewed by a human
        addon.update_version()
        assert addon._current_version
        addon.current_version.update(human_review_date=None)
        assert not job.should_auto_resolve()

        # success case for addon version specified
        version = version_factory(
            addon=addon,
            human_review_date=datetime.now(),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        abuse_already_moderated['addon_version'] = version.version
        abuse_report.update(**abuse_already_moderated)
        addon.current_version.update(human_review_date=datetime.now())
        assert job.should_auto_resolve()

        # addon version doesn't exist - falls back to current_version
        abuse_report.update(
            **{**abuse_already_moderated, 'addon_version': 'some-missing-version'}
        )
        assert job.should_auto_resolve()

        # if exists, but not already reviewed by a human, it fails
        abuse_report.update(**abuse_already_moderated)
        version.update(human_review_date=None)
        assert not job.should_auto_resolve()

        # and double-check that was the cause
        version.update(human_review_date=datetime.now())
        assert job.should_auto_resolve()

    def test_should_auto_resolve_job_with_multiple_reports(self):
        # For an incoming reports it's an edge case to have multiple reports in a job,
        # but for a forwarded job it's pretty common.
        addon = addon_factory(version_kw={'human_review_date': datetime.now()})
        version = version_factory(addon=addon, human_review_date=datetime.now())
        job = CinderJob.objects.create(
            target_addon=addon, resolvable_in_reviewer_tools=True
        )
        abuse_already_moderated = {
            'guid': addon.guid,
            'reporter_email': 'some@email.com',
            'cinder_job': job,
            'reason': AbuseReport.REASONS.POLICY_VIOLATION,
            'location': AbuseReport.LOCATION.ADDON,
            'addon_version': None,
        }
        old_report = AbuseReport.objects.create(**abuse_already_moderated)
        AbuseReport.objects.create(**abuse_already_moderated)

        # both reports are for the add-on, so should be okay
        assert job.should_auto_resolve()

        # update the old report so it's for a specific version
        old_report.update(addon_version=version.version)
        assert job.should_auto_resolve()

        # but should fail to auto-resolve if the older version meet criteria
        old_report.update(reason=AbuseReport.REASONS.ILLEGAL)
        assert not job.should_auto_resolve()

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

    def check_report_with_already_moderated_content(self, abuse_report):
        job_id = '1234-xyz'
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': job_id},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{job_id}/decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        policy = CinderPolicy.objects.create(
            uuid='123',
            enforcement_actions=[DECISION_ACTIONS.AMO_CLOSED_NO_ACTION.api_value],
        )

        CinderJob.report(abuse_report)
        assert CinderJob.objects.count() == 1
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['some@email.com']
        assert 'already assessed' in mail.outbox[0].body
        assert ContentDecision.objects.exists()
        decision = ContentDecision.objects.get()
        assert decision.action == DECISION_ACTIONS.AMO_CLOSED_NO_ACTION
        self.assertCloseToNow(decision.action_date)
        assert decision.cinder_job == CinderJob.objects.get()
        assert decision.policies.get() == policy

    def test_report_with_disabled_addon(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
        )
        addon.update(status=amo.STATUS_DISABLED)
        self.check_report_with_already_moderated_content(abuse_report)

    def test_report_with_banned_user(self):
        user = user_factory()
        abuse_report = AbuseReport.objects.create(
            user=user,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
        )
        user.update(banned=datetime.now())
        self.check_report_with_already_moderated_content(abuse_report)

    def test_report_with_deleted_collection(self):
        collection = collection_factory(author=user_factory())
        abuse_report = AbuseReport.objects.create(
            collection=collection,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
        )
        collection.delete()
        self.check_report_with_already_moderated_content(abuse_report)

    def test_report_with_deleted_rating(self):
        rating = Rating.objects.create(addon=addon_factory(), user=user_factory())
        abuse_report = AbuseReport.objects.create(
            rating=rating,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter_email='some@email.com',
        )
        rating.delete()
        self.check_report_with_already_moderated_content(abuse_report)

    def test_report_with_addon_already_moderated(self):
        addon = addon_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            reporter_email='some@email.com',
        )
        addon.current_version.update(human_review_date=datetime.now())
        self.check_report_with_already_moderated_content(abuse_report)

    def test_report_with_addon_version_already_moderated(self):
        addon = addon_factory()
        version = version_factory(
            addon=addon,
            human_review_date=datetime.now(),
            file_kw={'status': amo.STATUS_DISABLED},
        )
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            reporter_email='some@email.com',
            addon_version=version.version,
        )
        self.check_report_with_already_moderated_content(abuse_report)

    def test_report_with_addon_already_moderated_existing_job(self):
        addon = addon_factory()
        AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            cinder_job=CinderJob.objects.create(
                target_addon=addon, job_id='1234-xyz', resolvable_in_reviewer_tools=True
            ),
        )
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            location=AbuseReport.LOCATION.ADDON,
            reporter_email='some@email.com',
        )
        addon.current_version.update(human_review_date=datetime.now())
        self.check_report_with_already_moderated_content(abuse_report)

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
        policy_a = CinderPolicy.objects.create(uuid='123-45', name='aaa', text='AAA')
        policy_b = CinderPolicy.objects.create(uuid='678-90', name='bbb', text='BBB')

        with (
            mock.patch.object(ContentActionBanUser, 'process_action') as action_mock,
            mock.patch.object(ContentActionBanUser, 'notify_owners') as notify_mock,
        ):
            action_mock.return_value = None
            cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_action=DECISION_ACTIONS.AMO_BAN_USER.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
                job_queue='some-cinder-queue',
            )
        assert cinder_job.decision.cinder_id == '12345'
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_BAN_USER
        assert cinder_job.decision.private_notes == 'teh notes'
        assert cinder_job.decision.reasoning == ''
        assert cinder_job.decision.from_job_queue == 'some-cinder-queue'
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

        with (
            mock.patch.object(ContentActionBanUser, 'process_action') as action_mock,
            mock.patch.object(ContentActionBanUser, 'notify_owners') as notify_mock,
        ):
            action_mock.return_value = None
            assert cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_action=DECISION_ACTIONS.AMO_BAN_USER.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
                job_queue='some-cinder-queue',
            )
        assert cinder_job.decision.cinder_id == '12345'
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_BAN_USER
        assert cinder_job.decision.private_notes == 'teh notes'
        assert cinder_job.decision.reasoning == ''
        assert cinder_job.decision.user == target
        assert action_mock.call_count == 1
        assert notify_mock.call_count == 1
        assert list(cinder_job.decision.policies.all()) == [policy]

    def test_process_decision_decision_already_exists(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        target = user_factory()
        AbuseReport.objects.create(user=target, cinder_job=cinder_job)
        parent_policy = CinderPolicy.objects.create(
            uuid='678-90', name='bbb', text='BBB'
        )
        CinderPolicy.objects.create(
            uuid='123-45', name='aaa', text='AAA', parent=parent_policy
        )
        ContentDecision.objects.create(
            cinder_id='12345',
            action=DECISION_ACTIONS.AMO_BAN_USER.value,
            user=target,
            cinder_job=cinder_job,
        )

        with (
            mock.patch.object(ContentActionBanUser, 'process_action') as action_mock,
            mock.patch.object(ContentActionBanUser, 'notify_owners') as notify_mock,
        ):
            action_mock.return_value = None
            # Shouldn't fail.
            assert not cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_action=DECISION_ACTIONS.AMO_BAN_USER.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
                job_queue='some-cinder-queue',
            )
        # Shouldn't execute the action or notify, we already processed this
        # decision.
        assert action_mock.call_count == 0
        assert notify_mock.call_count == 0

    def test_process_decision_for_legal_reviewed_job(self):
        """An add-on forwarded to the legal queue for review will be a job that may not
        contain any attached abuse reports (i.e. if an add-on was forwared without a
        job)."""
        target = addon_factory()
        cinder_job = CinderJob.objects.create(job_id='1234', target_addon=target)
        policy_a = CinderPolicy.objects.create(uuid='123-45', name='aaa', text='AAA')
        policy_b = CinderPolicy.objects.create(uuid='678-90', name='bbb', text='BBB')
        assert AbuseReport.objects.filter(cinder_job=cinder_job).count() == 0
        assert ContentDecision.objects.filter(appeal_job=cinder_job).count() == 0

        with (
            mock.patch.object(
                ContentActionDisableAddon, 'process_action'
            ) as action_mock,
            mock.patch.object(
                ContentActionDisableAddon, 'notify_owners'
            ) as notify_mock,
        ):
            action_mock.return_value = None
            cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON.value,
                decision_notes='teh notes',
                policy_ids=['123-45', '678-90'],
                job_queue='some-cinder-queue',
            )
        assert cinder_job.decision.cinder_id == '12345'
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_DISABLE_ADDON
        assert cinder_job.decision.private_notes == 'teh notes'
        assert cinder_job.decision.reasoning == ''
        assert cinder_job.decision.addon == target
        assert cinder_job.decision.from_job_queue == 'some-cinder-queue'
        assert action_mock.call_count == 1
        assert notify_mock.call_count == 1
        assert list(cinder_job.decision.policies.all()) == [policy_a, policy_b]

    def test_process_decision_sets_target_versions_for_reject_version_appeals(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        target = addon_factory()
        policy_a = CinderPolicy.objects.create(uuid='123-45', name='aaa', text='AAA')
        ContentDecision.objects.create(
            addon=target,
            appeal_job=cinder_job,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
        ).target_versions.add(target.current_version)

        with (
            mock.patch.object(
                ContentActionTargetAppealApprove, 'process_action'
            ) as action_mock,
            mock.patch.object(
                ContentActionTargetAppealApprove, 'notify_owners'
            ) as notify_mock,
        ):
            action_mock.return_value = None
            cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_action=DECISION_ACTIONS.AMO_APPROVE.value,
                decision_notes='',
                policy_ids=['123-45'],
                job_queue='some-cinder-queue',
            )
        assert cinder_job.decision.cinder_id == '12345'
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_APPROVE
        assert cinder_job.decision.addon == target
        assert cinder_job.decision.target_versions.get() == target.current_version
        assert action_mock.call_count == 1
        assert notify_mock.call_count == 1
        assert list(cinder_job.decision.policies.all()) == [policy_a]

    def test_process_decision_overrides_action_for_reject_version_appeals(self):
        cinder_job = CinderJob.objects.create(job_id='1234')
        target = addon_factory()
        policy_a = CinderPolicy.objects.create(uuid='123-45', name='aaa', text='AAA')
        ContentDecision.objects.create(
            addon=target,
            appeal_job=cinder_job,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
        )

        with (
            mock.patch.object(
                ContentActionTargetAppealRemovalAffirmation, 'process_action'
            ) as action_mock,
            mock.patch.object(
                ContentActionTargetAppealRemovalAffirmation, 'notify_owners'
            ) as notify_mock,
        ):
            action_mock.return_value = None
            cinder_job.process_decision(
                decision_cinder_id='12345',
                decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON.value,
                decision_notes='',
                policy_ids=['123-45'],
                job_queue='some-cinder-queue',
            )
        assert cinder_job.decision.cinder_id == '12345'
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON
        assert cinder_job.decision.addon == target
        assert action_mock.call_count == 1
        assert notify_mock.call_count == 1
        assert list(cinder_job.decision.policies.all()) == [policy_a]

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

    @override_switch('dsa-cinder-forwarded-review', active=True)
    def test_process_queue_move_with_addon_already_moderated(self):
        addon = addon_factory()
        job = CinderJob.objects.create(
            target_addon=addon, job_id='1234-xyz', resolvable_in_reviewer_tools=True
        )
        policy = CinderPolicy.objects.create(
            uuid='123',
            enforcement_actions=[DECISION_ACTIONS.AMO_CLOSED_NO_ACTION.api_value],
        )
        AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.SOMETHING_ELSE,
            location=AbuseReport.LOCATION.AMO,
            cinder_job=job,
        )
        AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            reporter_email='some@email.com',
            cinder_job=job,
        )
        addon.current_version.update(human_review_date=datetime.now())
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{job.job_id}/decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )

        job.process_queue_move(new_queue='amo-env-addon-infringement', notes='notes!')
        assert not NeedsHumanReview.objects.exists()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['some@email.com']
        assert 'already assessed' in mail.outbox[0].body
        assert ContentDecision.objects.exists()
        decision = ContentDecision.objects.get()
        assert decision.action == DECISION_ACTIONS.AMO_CLOSED_NO_ACTION
        self.assertCloseToNow(decision.action_date)
        assert decision.cinder_job == CinderJob.objects.get()
        assert decision.policies.get() == policy

    def test_all_abuse_reports(self):
        job = CinderJob.objects.create(job_id='fake_job_id')
        # no abuse reports
        assert list(job.all_abuse_reports) == []

        addon = addon_factory()
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)
        report2 = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)
        # two abuse reports
        assert list(job.all_abuse_reports) == [report, report2]

        appeal_job = CinderJob.objects.create(job_id='fake_appeal_job_id')
        original_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            appeal_job=appeal_job,
            cinder_job=job,
        )
        # the abuse reports are found by the appealed job AND the appeal
        assert appeal_job.all_abuse_reports == [report, report2]
        assert list(job.all_abuse_reports) == [report, report2]

        appeal_appeal_job = CinderJob.objects.create(job_id='fake_appeal_appeal_job_id')
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            appeal_job=appeal_appeal_job,
            cinder_job=appeal_job,
        )
        # also when that appeal is appealled
        assert list(appeal_appeal_job.all_abuse_reports) == [report, report2]
        assert list(appeal_job.all_abuse_reports) == [report, report2]
        assert list(job.all_abuse_reports) == [report, report2]

        report3 = AbuseReport.objects.create(guid=addon.guid, cinder_job=appeal_job)
        report4 = AbuseReport.objects.create(
            guid=addon.guid, cinder_job=appeal_appeal_job
        )
        # unusual scenario when abuse reports are associate directly with appeal jobs
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
        original_decision.update(appeal_job=None)
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            appeal_job=appeal_job,
            override_of=job.decision,
            cinder_job=job,
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
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon_factory(),
            appeal_job=appeal,
            cinder_job=job,
        )
        job.reload()
        assert not job.is_appeal
        assert appeal.is_appeal

    def _setup_clear_needs_human_review_flags(self):
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
            reason=NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL,
        )
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE,
        )
        return job

    def _nhr_exists(self, reason):
        return NeedsHumanReview.objects.filter(reason=reason, is_active=True).exists()

    def test_clear_needs_human_review_flags_abuse(self):
        job = self._setup_clear_needs_human_review_flags()
        # for a non-forwarded or appealed job, this should clear the abuse NHR only
        job.clear_needs_human_review_flags()
        assert not self._nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
        assert self._nhr_exists(NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE)

    def test_clear_needs_human_review_flags_forwarded_moved_queue(self):
        job = self._setup_clear_needs_human_review_flags()
        # if the job is forwarded, we make sure that there are no other forwarded jobs
        CinderQueueMove.objects.create(cinder_job=job, to_queue='wherever')

        other_forward = CinderJob.objects.create(
            job_id='3',
            target_addon=job.target_addon,
            resolvable_in_reviewer_tools=True,
        )
        CinderQueueMove.objects.create(cinder_job=other_forward, to_queue='whoever')
        job.clear_needs_human_review_flags()
        assert self._nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
        assert self._nhr_exists(NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE)

        # unless the other job is closed too
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=job.target_addon,
            cinder_job=other_forward,
        )
        job.clear_needs_human_review_flags()
        assert self._nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert not self._nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert not self._nhr_exists(NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
        assert self._nhr_exists(NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE)

    def test_clear_needs_human_review_flags_forwarded_requeue(self):
        job = self._setup_clear_needs_human_review_flags()
        # if the job is forwarded, we make sure that there are no other forwarded jobs
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_REQUEUE,
            addon=job.target_addon,
            cinder_job=job,
            override_of=job.decision,
        )
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=job.target_addon,
            cinder_job=job,
            override_of=job.final_decision,
        )
        other_forward = CinderJob.objects.create(
            job_id='3',
            target_addon=job.target_addon,
            resolvable_in_reviewer_tools=True,
        )
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_REQUEUE,
            addon=job.target_addon,
            cinder_job=other_forward,
        )
        job.clear_needs_human_review_flags()
        assert self._nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
        assert self._nhr_exists(NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE)

        # unless the other job is closed too
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=job.target_addon,
            cinder_job=other_forward,
            override_of=other_forward.decision,
        )
        job.clear_needs_human_review_flags()
        assert self._nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
        assert not self._nhr_exists(NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE)

    def test_clear_needs_human_review_flags_appeal(self):
        job = self._setup_clear_needs_human_review_flags()
        # similarly if the job is an appeal we make sure that there are no other appeals
        CinderJob.objects.create(
            job_id='5',
            target_addon=job.target_addon,
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=job.target_addon,
                appeal_job=job,
            ),
        )
        other_appeal = CinderJob.objects.create(
            job_id='6',
            target_addon=job.target_addon,
            resolvable_in_reviewer_tools=True,
        )
        CinderJob.objects.create(
            job_id='7',
            target_addon=job.target_addon,
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=job.target_addon,
                appeal_job=other_appeal,
            ),
        )
        job.clear_needs_human_review_flags()
        assert self._nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
        assert self._nhr_exists(NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE)

        # unless the other job is closed too
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=job.target_addon,
            cinder_job=other_appeal,
        )
        job.clear_needs_human_review_flags()
        assert self._nhr_exists(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_ESCALATION)
        assert self._nhr_exists(NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION)
        assert not self._nhr_exists(NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
        assert self._nhr_exists(NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE)


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

        ContentDecision.objects.create(
            cinder_id='appeal decision id',
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            cinder_job=appeal_job,
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
            cinder_job=self.decision.cinder_job,
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

    def test_author_cant_appeal_own_appeal(self):
        appeal_job = CinderJob.objects.create(
            job_id='fake_appeal_job_id',
            decision=ContentDecision.objects.create(
                cinder_id='fake_appeal_decision_id',
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                addon=self.addon,
                action_date=datetime.now(),
            ),
        )
        self.decision.update(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, appeal_job=appeal_job
        )
        assert not appeal_job.decision.can_be_appealed(is_reporter=False)


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

    def test_full_name(self):
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
            text='Parent Description',
            uuid='parent-uuid',
        )
        child_policy = CinderPolicy.objects.create(
            name='Child Policy',
            text='Child {FOO} Description {BAR}',
            uuid='child-uuid',
            parent=parent_policy,
        )
        assert parent_policy.full_text() == 'Parent Policy: Parent Description'
        assert (
            parent_policy.full_text(text='Some Canned Response')
            == 'Parent Policy: Some Canned Response'
        )
        assert (
            child_policy.full_text()
            == 'Parent Policy, specifically Child Policy: Child {FOO} Description {BAR}'
        )
        assert (
            child_policy.full_text(values={'FOO': 'yes'})
            == 'Parent Policy, specifically Child Policy: Child yes Description {BAR}'
        )
        assert (
            child_policy.full_text(text='Canned Response')
            == 'Parent Policy, specifically Child Policy: Canned Response'
        )

    def test_get_full_texts(self):
        parent_policy = CinderPolicy.objects.create(
            name='Parent Policy',
            text='Parent Description',
            uuid='parent-uuid',
        )
        child_policy = CinderPolicy.objects.create(
            name='Child Policy',
            text='Child {FOO} Description {BAR}',
            uuid='child-uuid',
            parent=parent_policy,
        )
        policies = (parent_policy, child_policy)
        values = {child_policy.uuid: {'FOO': 'egg'}}
        assert CinderPolicy.get_full_texts(policies) == [
            'Parent Policy: Parent Description',
            'Parent Policy, specifically Child Policy: Child {FOO} Description {BAR}',
        ]
        assert CinderPolicy.get_full_texts(policies, values=values) == [
            'Parent Policy: Parent Description',
            'Parent Policy, specifically Child Policy: Child egg Description {BAR}',
        ]

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

    def test_get_decision_actions_from_policies(self):
        policies = (
            # no actions, ignored
            CinderPolicy.objects.create(uuid='1', enforcement_actions=[]),
            # multiple actions
            CinderPolicy.objects.create(
                uuid='2',
                enforcement_actions=[
                    'amo-disable-addon',
                    'amo-approve',
                    'amo-ban-user',
                ],
            ),
            # some duplicates, and unsupported actions
            CinderPolicy.objects.create(
                uuid='3', enforcement_actions=['amo-disable-addon', 'not-amo-action']
            ),
        )
        assert sorted(CinderPolicy.get_decision_actions_from_policies(policies)) == [
            DECISION_ACTIONS.AMO_BAN_USER,
            DECISION_ACTIONS.AMO_DISABLE_ADDON,
            DECISION_ACTIONS.AMO_APPROVE,
        ]

        assert sorted(
            CinderPolicy.get_decision_actions_from_policies(policies, for_entity=Addon)
        ) == [
            DECISION_ACTIONS.AMO_DISABLE_ADDON,
            DECISION_ACTIONS.AMO_APPROVE,
        ]

        assert sorted(
            CinderPolicy.get_decision_actions_from_policies(
                policies, for_entity=UserProfile
            )
        ) == [
            DECISION_ACTIONS.AMO_BAN_USER,
            DECISION_ACTIONS.AMO_APPROVE,
        ]

    def test_get_text_formatter_pairs(self):
        policy = CinderPolicy.objects.create(
            name='Child Policy',
            text='Child {FOO} Description {BAR}?',
            uuid='child-uuid',
        )
        assert policy.get_text_formatter_pairs() == [
            ('Child ', 'FOO'),
            (' Description ', 'BAR'),
            ('?', None),
        ]


class TestContentDecisionManager(TestCase):
    def test_held_for_2nd_level_approval(self):
        # This decision doesn't have action_date, so is held for 2nd leval approval
        held = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon_factory()
        )
        # This decision already has an action_date, so should be ignored
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon_factory(),
            action_date=datetime.now(),
        )
        # This doesn't have an action_date, but is overriden by a later decision, so
        # should be ignored
        overriden = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon_factory()
        )
        override = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon_factory(),
            override_of=overriden,
        )
        assert list(ContentDecision.objects.awaiting_action()) == [held, override]


@override_switch('dsa-abuse-reports-review', active=True)
class TestContentDecision(TestCase):
    def setUp(self):
        # It's the webhook's responsibility to do this before calling the
        # action. We need it for the ActivityLog creation to work.
        self.task_user = user_factory(pk=settings.TASK_USER_ID)
        self.reviewer_user = user_factory()
        set_user(self.reviewer_user)

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

    def test_souce(self):
        addon = addon_factory()
        decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon
        )
        assert decision.source == DECISION_SOURCES.TASKUS

        decision.update(reviewer_user=self.task_user)
        assert decision.source == DECISION_SOURCES.AUTOMATION

        decision.update(reviewer_user=self.reviewer_user)
        assert decision.source == DECISION_SOURCES.REVIEWER

        decision.update(
            reviewer_user=None, from_job_queue=CinderAddonHandledByLegal.queue
        )
        assert decision.source == DECISION_SOURCES.LEGAL

        decision.update(from_job_queue='some-other-cinder-queue')
        assert decision.source == DECISION_SOURCES.TASKUS

    def test_get_action_helper(self):
        addon = addon_factory()
        decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon
        )
        overriden_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            action_date=datetime.now(),
        )
        appealed_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            appeal_job=CinderJob.objects.create(job_id='1234'),
        )
        targets = {
            ContentActionBanUser: {'user': user_factory()},
            ContentActionDeleteCollection: {'collection': collection_factory()},
            ContentActionDeleteRating: {
                'rating': Rating.objects.create(addon=addon, user=user_factory())
            },
        }
        action_to_class = [
            (decision_action, CONTENT_ACTION_FROM_DECISION_ACTION[decision_action])
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
                override_of=None,
                cinder_job=None,
                **{
                    'action': new_action,
                    'addon': None,
                    'rating': None,
                    'collection': None,
                    'user': None,
                    **targets.get(ActionClass, {'addon': addon}),
                },
            )
            if overridden_action:
                decision.update(override_of=overriden_decision)
                overriden_decision.update(action=overridden_action)
            if appealed_action:
                decision.update(cinder_job=appealed_decision.appeal_job)
                appealed_decision.update(action=appealed_action)
            helper = decision.get_action_helper()
            assert helper.__class__ == ActionClass
            assert helper.decision == decision
            assert helper.reporter_template_path == ActionClass.reporter_template_path
            assert (
                helper.reporter_appeal_template_path
                == ActionClass.reporter_appeal_template_path
            )

        action_existing_to_class_no_reporter_emails = {
            (action, action): CONTENT_ACTION_FROM_DECISION_ACTION[action]
            for action in DECISION_ACTIONS.REMOVING.values
        }
        for (
            new_action,
            overridden_action,
        ), ActionClass in action_existing_to_class_no_reporter_emails.items():
            decision.update(
                override_of=None,
                **{
                    'action': new_action,
                    'addon': None,
                    'rating': None,
                    'collection': None,
                    'user': None,
                    **targets.get(ActionClass, {'addon': addon}),
                },
            )
            if overridden_action:
                decision.update(override_of=overriden_decision)
                overriden_decision.update(action=overridden_action)
            helper = decision.get_action_helper()
            assert helper.reporter_template_path is None
            assert helper.reporter_appeal_template_path is None
            assert ActionClass.reporter_template_path is not None
            assert ActionClass.reporter_appeal_template_path is not None

    def test_get_action_helper_override(self):
        addon = addon_factory()
        first_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon
        )
        second_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            override_of=first_decision,
        )
        current_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            override_of=second_decision,
        )

        action_existing_to_class = {}
        action_date = datetime.now()
        for action in DECISION_ACTIONS.REMOVING.values:
            for approve_action in (
                DECISION_ACTIONS.AMO_APPROVE,
                DECISION_ACTIONS.AMO_APPROVE_VERSION,
                DECISION_ACTIONS.AMO_IGNORE,
            ):
                action_existing_to_class[
                    (approve_action, action, action_date, None)
                ] = ContentActionOverrideApprove

                # But if there is no action_date the override is ignored
                action_existing_to_class[(approve_action, action, None, None)] = (
                    CONTENT_ACTION_FROM_DECISION_ACTION[approve_action]
                )

                # Previous decisions are also considered though
                action_existing_to_class[
                    (approve_action, action, None, action_date)
                ] = ContentActionOverrideApprove

        for (
            new_action,
            overridden_action,
            second_decision_date,
            first_decision_date,
        ), ActionClass in action_existing_to_class.items():
            current_decision.update(action=new_action)
            second_decision.update(
                action=overridden_action, action_date=second_decision_date
            )
            first_decision.update(
                action=overridden_action, action_date=first_decision_date
            )

            assert current_decision.get_action_helper().__class__ == ActionClass

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
                    reviewer_user=self.reviewer_user,
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
            resolvable_in_reviewer_tools=False, expected_queue='amo-env-listings'
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
                    reviewer_user=self.reviewer_user,
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
                    reviewer_user=self.reviewer_user,
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
                    reviewer_user=self.reviewer_user,
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
                    reviewer_user=self.reviewer_user,
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
        assert request_body['queue_slug'] == 'amo-env-listings'

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
                    reviewer_user=self.reviewer_user,
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
                    reviewer_user=self.reviewer_user,
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
                reviewer_user=self.reviewer_user,
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
                reviewer_user=self.reviewer_user,
            )
        )
        with self.assertRaises(ImproperlyConfigured):
            cinder_job.decision.appeal(
                abuse_report=abuse_report,
                appeal_text='No user but is_reporter is False',
                user=None,
                is_reporter=False,
            )

    def _test_report_to_cinder(
        self,
        decision,
        *,
        expect_create_decision_call,
        expect_create_job_decision_call,
        expect_create_override_call,
    ):
        cinder_job_id = (job := getattr(decision, 'cinder_job', None)) and job.job_id
        overridden_id = (dn := getattr(decision, 'override_of', None)) and dn.cinder_id
        if not overridden_id and decision.override_of:
            overridden_id = (
                dn := getattr(decision.override_of, 'override_of', None)
            ) and dn.cinder_id
        create_decision_response = responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        create_job_decision_response = responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{cinder_job_id}/decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        create_override_decision_response = responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}decisions/{overridden_id}/override/',
            json={'uuid': uuid.uuid4().hex},
            status=200,
        )
        decision.policies.add(
            CinderPolicy.objects.create(name='policy', uuid='12345678')
        )
        decision.update(reasoning='some review text')

        decision.report_to_cinder(
            CinderJob.get_entity_helper(
                decision.target, resolved_in_reviewer_tools=False
            )
        )

        if expect_create_decision_call:
            assert create_decision_response.call_count == 1
            assert create_job_decision_response.call_count == 0
            assert create_override_decision_response.call_count == 0
            request = responses.calls[0].request
            request_body = json.loads(request.body)
            assert request_body['policy_uuids'] == ['12345678']
            assert request_body['reasoning'] == 'some review text'
            assert request_body['entity']['id'] == str(decision.addon.id)
            assert request_body['enforcement_actions_slugs'] == [
                decision.action.api_value
            ]
        elif expect_create_job_decision_call:
            assert cinder_job_id
            assert create_decision_response.call_count == 0
            assert create_job_decision_response.call_count == 1
            assert create_override_decision_response.call_count == 0
            request = responses.calls[0].request
            request_body = json.loads(request.body)
            assert request_body['policy_uuids'] == ['12345678']
            assert request_body['reasoning'] == 'some review text'
            assert 'entity' not in request_body
            assert request_body['enforcement_actions_slugs'] == [
                decision.action.api_value
            ]
        elif expect_create_override_call:
            assert overridden_id
            assert create_decision_response.call_count == 0
            assert create_job_decision_response.call_count == 0
            assert create_override_decision_response.call_count == 1
            request = responses.calls[0].request
            request_body = json.loads(request.body)
            assert request_body['policy_uuids'] == ['12345678']
            assert request_body['reasoning'] == 'some review text'
            assert 'entity' not in request_body
            assert request_body['enforcement_actions_slugs'] == [
                decision.action.api_value
            ]
        else:
            assert create_decision_response.call_count == 0
            assert create_job_decision_response.call_count == 0

    def test_report_to_cinder_disable(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
        )
        self._test_report_to_cinder(
            decision,
            expect_create_decision_call=True,
            expect_create_job_decision_call=False,
            expect_create_override_call=False,
        )

    def test_report_to_cinder_approve_no_job(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_APPROVE,
            reviewer_user=self.reviewer_user,
        )
        self._test_report_to_cinder(
            decision,
            expect_create_decision_call=False,
            expect_create_job_decision_call=False,
            expect_create_override_call=False,
        )

    def test_report_to_cinder_approve_with_job(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_APPROVE,
            reviewer_user=self.reviewer_user,
        )
        CinderJob.objects.create(job_id='123', decision=decision)
        self._test_report_to_cinder(
            decision,
            expect_create_decision_call=False,
            expect_create_job_decision_call=True,
            expect_create_override_call=False,
        )

    def test_report_to_cinder_approve_with_job_via_override(self):
        addon = addon_factory()
        previous_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
            cinder_id='123456',
        )
        override = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            override_of=previous_decision,
            reviewer_user=self.reviewer_user,
        )
        CinderJob.objects.create(job_id='123', decision=previous_decision)
        self._test_report_to_cinder(
            override,
            expect_create_decision_call=False,
            expect_create_job_decision_call=False,
            expect_create_override_call=True,
        )

    def test_report_to_cinder_approve_no_job_override(self):
        addon = addon_factory()
        previous_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
            cinder_id='123456',
        )
        override = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            override_of=previous_decision,
            reviewer_user=self.reviewer_user,
        )
        self._test_report_to_cinder(
            override,
            expect_create_decision_call=False,
            expect_create_job_decision_call=False,
            expect_create_override_call=True,
        )

    def test_report_to_cinder_approve_override_without_cinder_id(self):
        addon = addon_factory()
        previous_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
            cinder_id=None,
        )
        override = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            override_of=previous_decision,
            reviewer_user=self.reviewer_user,
        )
        self._test_report_to_cinder(
            override,
            expect_create_decision_call=True,
            expect_create_job_decision_call=False,
            expect_create_override_call=False,
        )

    def test_report_to_cinder_approve_override_previous_decision_has_cinder_id(self):
        addon = addon_factory()
        first_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
            cinder_id='123456',
        )
        second_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
            cinder_id=None,
            override_of=first_decision,
        )
        override = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            override_of=second_decision,
            reviewer_user=self.reviewer_user,
        )
        self._test_report_to_cinder(
            override,
            expect_create_decision_call=False,
            expect_create_job_decision_call=False,
            expect_create_override_call=True,
        )

    def _test_execute_action_ban_user_outcome(self, decision):
        self.assertCloseToNow(decision.action_date)
        self.assertCloseToNow(decision.user.reload().banned)
        alog = ActivityLog.objects.filter(action=amo.LOG.ADMIN_USER_BANNED.id).get()
        assert alog.contentdecisionlog_set.get().decision == decision
        decision.send_notifications()
        assert len(mail.outbox) == 1
        assert 'appeal' in mail.outbox[0].body

    def test_execute_action_ban_user_held(self):
        self.grant_permission(user_factory(), ':'.join(ADDONS_HIGH_IMPACT_APPROVE))
        user = user_factory(email='superstarops@mozilla.com')
        decision = ContentDecision.objects.create(
            user=user,
            action=DECISION_ACTIONS.AMO_BAN_USER,
            reviewer_user=self.reviewer_user,
        )
        assert decision.action_date is None
        decision.execute_action()
        assert decision.action_date is None
        assert not user.reload().banned
        alog = ActivityLog.objects.filter(
            action=amo.LOG.HELD_ACTION_ADMIN_USER_BANNED.id
        ).get()
        assert alog.contentdecisionlog_set.get().decision == decision
        assert mail.outbox.pop().subject == (
            'A new item has entered the second level approval queue'
        )
        decision.send_notifications()
        assert len(mail.outbox) == 0

        decision.execute_action(release_hold=True)
        self._test_execute_action_ban_user_outcome(decision)

    def test_execute_action_ban_user(self):
        user = user_factory()
        decision = ContentDecision.objects.create(
            user=user,
            action=DECISION_ACTIONS.AMO_BAN_USER,
            reviewer_user=self.reviewer_user,
        )
        assert decision.action_date is None
        decision.execute_action()
        self._test_execute_action_ban_user_outcome(decision)

    def _test_execute_action_disable_addon_outcome(self, decision):
        self.assertCloseToNow(decision.action_date)
        assert decision.addon.reload().status == amo.STATUS_DISABLED
        alog = ActivityLog.objects.filter(action=amo.LOG.FORCE_DISABLE.id).get()
        assert alog.contentdecisionlog_set.get().decision == decision
        decision.send_notifications()
        assert len(mail.outbox) == 1
        assert 'appeal' in mail.outbox[0].body

    def test_execute_action_disable_addon_held(self):
        self.grant_permission(user_factory(), ':'.join(ADDONS_HIGH_IMPACT_APPROVE))
        addon = addon_factory(users=[user_factory()])
        self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
        )
        assert decision.action_date is None
        decision.execute_action()
        assert decision.action_date is None
        assert addon.reload().status == amo.STATUS_APPROVED
        alog = ActivityLog.objects.filter(
            action=amo.LOG.HELD_ACTION_FORCE_DISABLE.id
        ).get()
        # attachment is linked to the original decision activity log
        AttachmentLog.objects.create(
            activity_log=alog,
            file=ContentFile('Pseudo File', name='attachment.txt'),
        )
        assert alog.contentdecisionlog_set.get().decision == decision
        assert mail.outbox.pop().subject == (
            'A new item has entered the second level approval queue'
        )
        decision.send_notifications()
        assert len(mail.outbox) == 0

        decision.execute_action(release_hold=True)
        self._test_execute_action_disable_addon_outcome(decision)
        assert 'An attachment was provided.' in mail.outbox[0].body
        assert 'To respond or view the file,' in mail.outbox[0].body

    def test_execute_action_disable_addon(self):
        addon = addon_factory(users=[user_factory()])
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
        )
        assert decision.action_date is None
        decision.execute_action()
        self._test_execute_action_disable_addon_outcome(decision)
        assert '14 day(s)' not in mail.outbox[0].body
        assert 'An attachment was provided.' not in mail.outbox[0].body
        assert 'To respond or view the file,' not in mail.outbox[0].body

    def test_execute_action_disable_addon_from_cinder_without_private_notes(self):
        addon = addon_factory(users=[user_factory()])
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=None,
        )
        policy = CinderPolicy.objects.create(
            uuid='1234',
            name='Bad policy',
            text='This is bad',
            parent=CinderPolicy.objects.create(
                uuid='p4r3nt',
                name='Parent',
                text='Parent policy text',
            ),
        )
        decision.policies.add(policy)
        assert decision.action_date is None
        decision.execute_action()
        self._test_execute_action_disable_addon_outcome(decision)
        assert 'Parent, specifically Bad policy: This is bad' in mail.outbox[0].body

    def test_execute_action_disable_addon_from_cinder_with_private_notes(self):
        addon = addon_factory(users=[user_factory()])
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=None,
            private_notes='some private notes',
        )
        policy = CinderPolicy.objects.create(
            uuid='1234',
            name='Bad policy',
            text='This is bad',
            parent=CinderPolicy.objects.create(
                uuid='p4r3nt',
                name='Parent',
                text='Parent policy text',
            ),
        )
        decision.policies.add(policy)
        assert decision.action_date is None
        decision.execute_action()
        self._test_execute_action_disable_addon_outcome(decision)
        assert 'Parent, specifically Bad policy: This is bad' in mail.outbox[0].body
        assert 'some private notes' not in mail.outbox[0].body

    def _test_execute_action_reject_version_outcome(self, decision):
        decision.send_notifications()
        assert 'appeal' in mail.outbox[0].body
        assert 'some review text' in mail.outbox[0].body
        assert '14 day(s)' not in mail.outbox[0].body
        self.assertCloseToNow(decision.action_date)
        version = decision.target_versions.get()
        assert version.file.reload().status == amo.STATUS_DISABLED
        assert VersionReviewerFlags.objects.filter(version=version).exists()

    def test_execute_action_reject_version_held(self):
        self.grant_permission(user_factory(), ':'.join(ADDONS_HIGH_IMPACT_APPROVE))
        addon = addon_factory(users=[user_factory()], file_kw={'is_signed': True})
        version = addon.current_version
        self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        )
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            reasoning='some review text',
            reviewer_user=self.reviewer_user,
        )
        CinderJob.objects.create(decision=decision)
        decision.target_versions.set([version])
        assert decision.action_date is None
        decision.execute_action()
        assert decision.action_date is None
        assert version.file.reload().status == amo.STATUS_APPROVED
        alog = ActivityLog.objects.filter(
            action=amo.LOG.HELD_ACTION_REJECT_VERSIONS.id
        ).get()
        assert alog.contentdecisionlog_set.get().decision == decision
        # attachment is linked to the original decision activity log
        AttachmentLog.objects.create(
            activity_log=alog,
            file=ContentFile('Pseudo File', name='attachment.txt'),
        )
        assert mail.outbox.pop().subject == (
            'A new item has entered the second level approval queue'
        )
        decision.send_notifications()
        assert len(mail.outbox) == 0
        assert not version.needshumanreview_set.filter(is_active=True).exists()

        decision.execute_action(release_hold=True)
        self._test_execute_action_reject_version_outcome(decision)
        assert 'An attachment was provided.' in mail.outbox[0].body
        assert 'To respond or view the file,' in mail.outbox[0].body

    def test_execute_action_reject_version(self):
        addon = addon_factory(users=[user_factory()])
        version = addon.current_version
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        )

        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            reasoning='some review text',
            reviewer_user=self.reviewer_user,
        )
        decision.target_versions.set([addon.current_version])
        cinder_job = CinderJob.objects.create(decision=decision)
        cinder_job.pending_rejections.add(
            version_review_flags_factory(
                version=addon.current_version,
                pending_rejection=self.days_ago(1),
                pending_rejection_by=user_factory(),
                pending_content_rejection=False,
            )
        )
        assert decision.action_date is None

        decision.execute_action()
        assert not cinder_job.pending_rejections.exists()
        self._test_execute_action_reject_version_outcome(decision)
        assert '14 day(s)' not in mail.outbox[0].body
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert 'An attachment was provided.' not in mail.outbox[0].body
        assert 'To respond or view the file,' not in mail.outbox[0].body

    def _test_execute_action_reject_version_delayed_outcome(self, decision):
        decision.send_notifications()
        assert 'appeal' not in mail.outbox[0].body
        assert 'some review text' in mail.outbox[0].body
        assert '14 day(s)' in mail.outbox[0].body
        self.assertCloseToNow(decision.action_date)
        assert (
            decision.addon.current_version.file.reload().status == amo.STATUS_APPROVED
        )

    def test_execute_action_reject_version_delayed(self):
        addon = addon_factory(users=[user_factory()])
        in_fourteen_days = datetime.now() + timedelta(days=14, minutes=3)
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            reasoning='some review text',
            reviewer_user=self.reviewer_user,
            metadata={'delayed_rejection_date': in_fourteen_days.isoformat()},
        )
        decision.target_versions.set([addon.current_version])
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
            version=addon.current_version,
        )
        assert addon.current_version.due_date
        cinder_job = CinderJob.objects.create(decision=decision)

        decision.execute_action()
        assert decision.is_delayed
        self._test_execute_action_reject_version_delayed_outcome(decision)
        assert cinder_job.reload().pending_rejections.exists()
        assert VersionReviewerFlags.objects.filter(
            version=addon.current_version
        ).exists()
        assert set(cinder_job.pending_rejections.all()) == set(
            VersionReviewerFlags.objects.filter(version=addon.current_version)
        )
        assert not NeedsHumanReview.objects.filter(is_active=True).exists()
        decision.send_notifications()
        assert 'appeal' not in mail.outbox[0].body
        assert 'some review text' in mail.outbox[0].body
        assert '14 day(s)' in mail.outbox[0].body
        assert addon.current_version.reviewerflags.pending_rejection == in_fourteen_days

    def test_execute_action_reject_version_delayed_held(self):
        self.grant_permission(user_factory(), ':'.join(ADDONS_HIGH_IMPACT_APPROVE))
        addon = addon_factory(users=[user_factory()], file_kw={'is_signed': True})
        version = addon.current_version
        self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        some_time_ago = self.days_ago(13)
        little_over_fourteen_days = timedelta(days=14, minutes=1)
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            reasoning='some review text',
            reviewer_user=self.reviewer_user,
            created=some_time_ago,
            metadata={
                'delayed_rejection_date': (
                    some_time_ago + little_over_fourteen_days
                ).isoformat()
            },
        )
        decision.target_versions.set([version])
        assert decision.action_date is None
        decision.execute_action()
        assert decision.action_date is None
        assert version.file.reload().status == amo.STATUS_APPROVED
        alog = ActivityLog.objects.filter(
            action=amo.LOG.HELD_ACTION_REJECT_VERSIONS_DELAYED.id
        ).get()
        assert alog.contentdecisionlog_set.get().decision == decision
        assert mail.outbox.pop().subject == (
            'A new item has entered the second level approval queue'
        )
        decision.send_notifications()
        assert len(mail.outbox) == 0

        decision.execute_action(release_hold=True)
        self._test_execute_action_reject_version_delayed_outcome(decision)
        self.assertCloseToNow(
            version.reviewerflags.pending_rejection,
            now=datetime.now() + little_over_fourteen_days,
        )

    def test_send_notifications_change_pending_rejection_date(self):
        addon = addon_factory(users=[user_factory(email='author@example.com')])
        old_pending_rejection = self.days_ago(1)
        new_pending_rejection = datetime.now() + timedelta(days=1)
        version_review_flags_factory(
            version=addon.current_version,
            pending_rejection=old_pending_rejection,
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_CHANGE_PENDING_REJECTION_DATE,
            action_date=datetime.now(),
        )
        ActivityLog.objects.create(
            amo.LOG.CHANGE_PENDING_REJECTION,
            addon,
            addon.current_version,
            decision,
            details={
                'old_deadline': str(old_pending_rejection),
                'new_deadline': str(new_pending_rejection),
            },
            user=user_factory(),
        )
        decision.send_notifications()
        assert (
            'previous correspondence indicated that you would be required '
            f'to correct the violation(s) by {old_pending_rejection}'
        ) in mail.outbox[0].body
        assert (
            'now require you to correct your add-on violations no later '
            f'than {new_pending_rejection}'
        ) in mail.outbox[0].body

    def test_send_notifications_without_notifying_owners(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        reporter = user_factory()
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid,
            reason=AbuseReport.REASONS.ILLEGAL,
            reporter=reporter,
            cinder_job=CinderJob.objects.create(
                target_addon=addon,
                resolvable_in_reviewer_tools=True,
                decision=ContentDecision.objects.create(
                    cinder_id='4815162342-lost',
                    action_date=self.days_ago(1),
                    action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                    addon=addon,
                    reviewer_user=self.reviewer_user,
                ),
            ),
        )
        decision = abuse_report.cinder_job.decisions.get()
        decision.send_notifications(notify_owners=False)
        assert len(mail.outbox) == 1  # No email to owner
        assert mail.outbox[0].to == [reporter.email]
        mail.outbox = []

        decision.send_notifications(notify_owners=True)
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [reporter.email]
        assert mail.outbox[1].to == [addon_developer.email]

    def test_resolve_job_forwarded(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            action_date=datetime.now(),
            reasoning='some review text',
            reviewer_user=self.reviewer_user,
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]
        decision.policies.set(policies)
        cinder_job = CinderJob.objects.create(job_id='999', decision=decision)
        CinderQueueMove.objects.create(cinder_job=cinder_job, to_queue='wherever')
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

        log_entry = ActivityLog.objects.create(
            amo.LOG.FORCE_DISABLE,
            abuse_report.target,
            abuse_report.target.current_version,
            *policies,
            decision,
            user=user_factory(),
        )

        decision.execute_action()
        assert not NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.CINDER_ESCALATION
        ).exists()
        assert NeedsHumanReview.objects.filter(is_active=True).count() == 2
        decision.send_notifications()
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [abuse_report.reporter.email]
        assert 'requested the developer' not in mail.outbox[0].body
        assert mail.outbox[1].to == [addon_developer.email]
        assert str(log_entry.id) in mail.outbox[1].extra_headers['Message-ID']
        assert 'some review text' in mail.outbox[1].body

    def test_execute_action_forwarded_to_legal(self):
        addon_developer = user_factory()
        addon = addon_factory(users=[addon_developer])
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_LEGAL_FORWARD,
            reasoning='some reasoning',
            reviewer_user=self.reviewer_user,
        )
        cinder_job = CinderJob.objects.create(job_id='999', decision=decision)
        CinderQueueMove.objects.create(cinder_job=cinder_job, to_queue='wherever')
        NeedsHumanReview.objects.create(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
        )
        AbuseReport.objects.create(
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

        decision.execute_action()

        cinder_job.reload()
        assert cinder_job.decision.action == DECISION_ACTIONS.AMO_LEGAL_FORWARD
        self.assertCloseToNow(cinder_job.decision.action_date)
        assert not NeedsHumanReview.objects.filter(
            is_active=True, reason=NeedsHumanReview.REASONS.CINDER_ESCALATION
        ).exists()
        new_job = CinderJob.objects.first()
        assert not new_job.resolvable_in_reviewer_tools

        decision.send_notifications()
        assert len(mail.outbox) == 0

    def _test_execute_action_delete_collection_outcome(self, decision):
        self.assertCloseToNow(decision.action_date)
        assert decision.collection.reload().deleted
        alog = ActivityLog.objects.filter(action=amo.LOG.COLLECTION_DELETED.id).get()
        assert alog.contentdecisionlog_set.get().decision == decision
        decision.send_notifications()
        assert len(mail.outbox) == 1
        assert 'appeal' in mail.outbox[0].body

    def test_execute_action_delete_collection_held(self):
        self.grant_permission(user_factory(), ':'.join(ADDONS_HIGH_IMPACT_APPROVE))
        collection = collection_factory(author=self.task_user)
        decision = ContentDecision.objects.create(
            collection=collection,
            action=DECISION_ACTIONS.AMO_DELETE_COLLECTION,
            reviewer_user=self.reviewer_user,
        )
        assert decision.action_date is None
        decision.execute_action()
        assert decision.action_date is None
        assert not collection.reload().deleted
        alog = ActivityLog.objects.filter(
            action=amo.LOG.HELD_ACTION_COLLECTION_DELETED.id
        ).get()
        assert alog.contentdecisionlog_set.get().decision == decision
        assert mail.outbox.pop().subject == (
            'A new item has entered the second level approval queue'
        )
        decision.send_notifications()
        assert len(mail.outbox) == 0

        decision.execute_action(release_hold=True)
        self._test_execute_action_delete_collection_outcome(decision)

    def test_execute_action_delete_collection(self):
        collection = collection_factory(author=user_factory())
        decision = ContentDecision.objects.create(
            collection=collection,
            action=DECISION_ACTIONS.AMO_DELETE_COLLECTION,
            reviewer_user=self.reviewer_user,
        )
        assert decision.action_date is None
        decision.execute_action()
        self._test_execute_action_delete_collection_outcome(decision)

    def _test_execute_action_delete_rating_outcome(self, decision):
        self.assertCloseToNow(decision.action_date)
        assert decision.rating.reload().deleted
        alog = ActivityLog.objects.filter(action=amo.LOG.DELETE_RATING.id).get()
        assert alog.contentdecisionlog_set.get().decision == decision
        decision.send_notifications()
        assert len(mail.outbox) == 1
        assert 'appeal' in mail.outbox[0].body

    def test_execute_action_delete_rating_held(self):
        self.grant_permission(user_factory(), ':'.join(ADDONS_HIGH_IMPACT_APPROVE))
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
            rating=rating,
            action=DECISION_ACTIONS.AMO_DELETE_RATING,
            reviewer_user=self.reviewer_user,
        )
        self.make_addon_promoted(
            rating.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        assert decision.action_date is None
        mail.outbox.clear()

        decision.execute_action()
        assert decision.action_date is None
        assert not rating.reload().deleted
        alog = ActivityLog.objects.filter(
            action=amo.LOG.HELD_ACTION_DELETE_RATING.id
        ).get()
        assert alog.contentdecisionlog_set.get().decision == decision
        assert mail.outbox.pop().subject == (
            'A new item has entered the second level approval queue'
        )
        decision.send_notifications()
        assert len(mail.outbox) == 0

        decision.execute_action(release_hold=True)
        self._test_execute_action_delete_rating_outcome(decision)

    def test_execute_action_delete_rating(self):
        rating = Rating.objects.create(addon=addon_factory(), user=user_factory())
        decision = ContentDecision.objects.create(
            rating=rating,
            action=DECISION_ACTIONS.AMO_DELETE_RATING,
            reviewer_user=self.reviewer_user,
        )
        assert decision.action_date is None
        decision.execute_action()
        self._test_execute_action_delete_rating_outcome(decision)

    def test_execute_action_with_action_date_already(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(users=[user_factory()]),
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            action_date=datetime.now(),
            reasoning='some review text',
            reviewer_user=self.reviewer_user,
        )
        log_entry = ActivityLog.objects.create(
            amo.LOG.FORCE_DISABLE,
            decision.addon,
            decision,
            details={'comments': 'some review text'},
            user=user_factory(),
        )

        with (
            mock.patch.object(
                ContentActionDisableAddon, 'process_action'
            ) as process_mock,
            mock.patch.object(ContentActionDisableAddon, 'hold_action') as hold_mock,
        ):
            decision.execute_action()
            process_mock.assert_not_called()
            hold_mock.assert_not_called()
        decision.send_notifications()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [decision.addon.authors.first().email]
        assert str(log_entry.id) in mail.outbox[0].extra_headers['Message-ID']
        assert 'days' not in mail.outbox[0].body
        assert 'some review text' in mail.outbox[0].body
        assert 'some policy text' not in mail.outbox[0].body
        AttachmentLog.objects.create(
            activity_log=log_entry,
            file=ContentFile('Pseudo File', name='attachment.txt'),
        )
        decision.send_notifications()
        assert 'An attachment was provided.' not in mail.outbox[0].body
        assert 'To respond or view the file,' not in mail.outbox[0].body
        assert 'An attachment was provided.' in mail.outbox[1].body
        assert 'To respond or view the file,' in mail.outbox[1].body

    def _check_requeue_decision(self, requeue, job, decision, user):
        assert requeue != decision
        assert requeue.action == DECISION_ACTIONS.AMO_REQUEUE
        self.assertCloseToNow(requeue.action_date)
        assert requeue.override_of == decision
        assert requeue.private_notes == 'go!'
        assert requeue.reviewer_user == user
        assert requeue.cinder_job == job
        assert NeedsHumanReview.objects.filter(
            reason=NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE
        ).exists()

    def test_requeue_held_action_no_job(self):
        addon = addon_factory()
        user = user_factory()
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
            cinder_id='1234',
        )

        decision.requeue_held_action(user=user, notes='go!')

        new_job = decision.reload().cinder_job
        assert new_job.resolvable_in_reviewer_tools is True
        assert new_job.target_addon == addon
        self._check_requeue_decision(new_job.final_decision, new_job, decision, user)

    def test_requeue_held_action_existing_job(self):
        addon = addon_factory()
        user = user_factory()
        job = CinderJob.objects.create(target_addon=addon)
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
            cinder_job=job,
            cinder_id='1234',
        )

        decision.requeue_held_action(user=user, notes='go!')

        assert job.reload().resolvable_in_reviewer_tools is True
        assert job.decision == decision
        self._check_requeue_decision(job.final_decision, job, decision, user)

    def test_requeue_held_action_existing_job_unlisted(self):
        addon = addon_factory()
        self.make_addon_unlisted(addon)
        user = user_factory()
        job = CinderJob.objects.create(target_addon=addon)
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
            cinder_job=job,
            cinder_id='1234',
        )
        decision.target_versions.add(addon.versions.get())

        decision.requeue_held_action(user=user, notes='go!')

        assert job.reload().resolvable_in_reviewer_tools is True
        assert job.decision == decision
        self._check_requeue_decision(job.final_decision, job, decision, user)

    def test_get_target_review_url(self):
        addon = addon_factory()
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
        )
        assert decision.get_target_review_url() == reverse(
            'reviewers.decision_review', args=(decision.id,)
        )

    def test_get_target_display(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
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
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            reviewer_user=self.reviewer_user,
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

    def test_get_policy_texts(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            metadata={
                ContentDecision.POLICY_DYNAMIC_VALUES: {
                    'uuid-a': {'NPM_VER': '123.4', 'EXPLAIN': ':rolleyes:'},
                    'uuid-b': {'THING': 'thing?'},
                }
            },
        )
        decision.policies.set(
            (
                CinderPolicy.objects.create(
                    name='policy a', uuid='uuid-a', text='Something {NPM_VER} {EXPLAIN}'
                ),
                CinderPolicy.objects.create(
                    name='policy b', uuid='uuid-b', text='Other {THING} with {MISSING}'
                ),
            )
        )

        assert decision.get_policy_texts() == [
            'policy a: Something 123.4 :rolleyes:',
            'policy b: Other thing? with {MISSING}',
        ]

    def test_has_policy_text_in_comments(self):
        decision = ContentDecision.objects.create(
            addon=addon_factory(),
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        )
        assert decision.has_policy_text_in_comments is False

        decision.update(reviewer_user=user_factory())
        assert decision.has_policy_text_in_comments is True

        decision.update(
            metadata={
                ContentDecision.POLICY_DYNAMIC_VALUES: {
                    'uuid-a': {'NPM_VER': '123.4', 'EXPLAIN': ':rolleyes:'},
                    'uuid-b': {'THING': 'thing?'},
                }
            },
        )
        assert decision.has_policy_text_in_comments is False


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
