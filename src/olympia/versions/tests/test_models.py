import os.path
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core import mail

import pytest
import waffle
from waffle.testutils import override_switch

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonReviewerFlags
from olympia.amo.tests import (
    AMOPaths,
    TestCase,
    addon_factory,
    create_default_webext_appversion,
    license_factory,
    user_factory,
    version_factory,
    version_review_flags_factory,
)
from olympia.amo.tests.test_models import BasePreviewMixin
from olympia.amo.utils import utc_millesecs_from_epoch
from olympia.applications.models import AppVersion
from olympia.blocklist.models import Block, BlockType, BlockVersion
from olympia.constants.promoted import (
    PROMOTED_GROUP_CHOICES,
    PROMOTED_GROUPS_BY_ID,
)
from olympia.constants.scanners import CUSTOMS, YARA
from olympia.files.models import File
from olympia.files.tests.test_models import UploadMixin
from olympia.files.utils import parse_addon
from olympia.promoted.models import PromotedApproval, PromotedGroup
from olympia.reviewers.models import AutoApprovalSummary, NeedsHumanReview
from olympia.scanners.models import ScannerResult
from olympia.users.models import (
    RESTRICTION_TYPES,
    EmailUserRestriction,
    IPNetworkUserRestriction,
    UserProfile,
)
from olympia.users.utils import get_task_user
from olympia.zadmin.models import set_config

from ..compare import VersionString, version_int
from ..models import (
    ApplicationsVersions,
    DeniedInstallOrigin,
    InstallOrigin,
    License,
    Version,
    VersionCreateError,
    VersionPreview,
    VersionProvenance,
    VersionReviewerFlags,
    source_upload_path,
)
from ..utils import get_review_due_date


pytestmark = pytest.mark.django_db


class TestVersionManagerLatestPublicCompatibleWith(TestCase):
    def test_latest_public_compatible_with_multiple_addons(self):
        # Add compatible add-ons. We're going to request versions compatible
        # with 58.0.
        compatible_pack1 = addon_factory(
            name='Spanish Language Pack',
            type=amo.ADDON_LPAPP,
            target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        compatible_pack1.current_version.update(created=self.days_ago(2))
        compatible_version1 = version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        compatible_version1.update(created=self.days_ago(1))
        compatible_pack2 = addon_factory(
            name='French Language Pack',
            type=amo.ADDON_LPAPP,
            target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '58.0', 'max_app_version': '58.*'},
        )
        compatible_version2 = compatible_pack2.current_version
        compatible_version2.update(created=self.days_ago(2))
        version_factory(
            addon=compatible_pack2,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0',
            max_app_version='59.*',
        )
        # Add a more recent version for both add-ons, that would be compatible
        # with 58.0, but is not public/listed so should not be returned.
        version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
            channel=amo.CHANNEL_UNLISTED,
        )
        version_factory(
            addon=compatible_pack2,
            file_kw={'strict_compatibility': True, 'status': amo.STATUS_DISABLED},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        # And for the first pack, add a couple of versions that are also
        # compatible. They are older so should appear after.
        extra_compatible_version_1 = version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        extra_compatible_version_1.update(created=self.days_ago(3))
        extra_compatible_version_2 = version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        extra_compatible_version_2.update(created=self.days_ago(4))

        # Add a few of incompatible add-ons.
        incompatible_pack1 = addon_factory(
            name='German Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP,
            target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '56.0', 'max_app_version': '56.*'},
        )
        version_factory(
            addon=incompatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0',
            max_app_version='59.*',
        )
        addon_factory(
            name='Italian Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP,
            target_locale='it',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '59.0', 'max_app_version': '59.*'},
        )
        # Even add a pack with a compatible version... not public. And another
        # one with a compatible version... not listed.
        incompatible_pack2 = addon_factory(
            name='Japanese Language Pack (public, but 58.0 version is not)',
            type=amo.ADDON_LPAPP,
            target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        version_factory(
            addon=incompatible_pack2,
            min_app_version='58.0',
            max_app_version='58.*',
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'strict_compatibility': True,
            },
        )
        incompatible_pack3 = addon_factory(
            name='Nederlands Language Pack (58.0 version is unlisted)',
            type=amo.ADDON_LPAPP,
            target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        version_factory(
            addon=incompatible_pack3,
            min_app_version='58.0',
            max_app_version='58.*',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'strict_compatibility': True},
        )

        appversions = {
            'min': version_int('58.0'),
            'max': version_int('58.0a'),
        }
        qs = Version.objects.latest_public_compatible_with(amo.FIREFOX.id, appversions)

        expected_versions = [
            compatible_version1,
            compatible_version2,
            extra_compatible_version_1,
            extra_compatible_version_2,
        ]
        assert list(qs) == expected_versions

    def test_latest_public_compatible_with(self):
        addon = addon_factory(
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        appversions = {
            'min': version_int('58.0'),
            'max': version_int('58.0'),
        }
        qs = Version.objects.latest_public_compatible_with(amo.FIREFOX.id, appversions)
        # We should get 4 joins:
        # - applications_versions
        # - appversions (min)
        # - appversions (max)
        # - files (status and strict_compatibility)
        assert str(qs.query).count('JOIN') == 4
        # We're not in strict mode, and the add-on hasn't strict compatibility enabled,
        # so we find a result.
        assert qs.exists()
        assert qs[0] == addon.current_version
        assert qs[0].min_compatible_version == '57.0'
        assert qs[0].max_compatible_version == '57.*'

    def test_latest_public_compatible_with_wrong_app(self):
        addon = addon_factory(
            version_kw={
                'application': amo.ANDROID.id,
                'min_app_version': '121.0',
                'max_app_version': '*',
            },
        )
        appversions = {
            'min': version_int('121.0'),
            'max': version_int('121.0'),
        }
        qs = Version.objects.latest_public_compatible_with(amo.FIREFOX.id, appversions)
        assert not qs.exists()
        assert str(qs.query).count('JOIN') == 4

        qs = Version.objects.latest_public_compatible_with(amo.ANDROID.id, appversions)
        assert qs.exists()
        assert str(qs.query).count('JOIN') == 4
        assert qs[0] == addon.current_version
        assert qs[0].min_compatible_version == '121.0'
        assert qs[0].max_compatible_version == '*'

        # Add a Firefox version, but don't let it be compatible with what we're
        # requesting yet.
        av_min, _ = AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='122.0'
        )
        av_max, _ = AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='*'
        )
        avs, _ = ApplicationsVersions.objects.get_or_create(
            application=amo.FIREFOX.id,
            version=addon.current_version,
            min=av_min,
            max=av_max,
        )
        qs = Version.objects.latest_public_compatible_with(amo.FIREFOX.id, appversions)
        assert not qs.exists()

        avs.min = AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='121.0'
        )[0]
        avs.save()

        # Now it should work!
        qs = Version.objects.latest_public_compatible_with(amo.FIREFOX.id, appversions)
        assert qs.exists()
        assert qs[0] == addon.current_version
        assert qs[0].min_compatible_version == '121.0'
        assert qs[0].max_compatible_version == '*'

    def test_latest_public_compatible_with_no_max_argument(self):
        addon = addon_factory(
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        appversions = {
            'min': version_int('58.0'),
        }
        qs = Version.objects.latest_public_compatible_with(amo.FIREFOX.id, appversions)
        assert str(qs.query).count('JOIN') == 4
        assert qs.exists()
        assert qs[0] == addon.current_version
        assert qs[0].min_compatible_version == '57.0'
        assert qs[0].max_compatible_version == '57.*'  # Still annotated.

    def test_latest_public_compatible_with_strict_compat_mode(self):
        addon = addon_factory(
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        appversions = {
            'min': version_int('58.0'),
            'max': version_int('58.0'),
        }
        qs = Version.objects.latest_public_compatible_with(
            amo.FIREFOX.id, appversions, strict_compat_mode=True
        )
        assert str(qs.query).count('JOIN') == 4
        assert not qs.exists()

        appversions = {
            'min': version_int('57.0'),
            'max': version_int('57.0'),
        }
        qs = Version.objects.latest_public_compatible_with(
            amo.FIREFOX.id, appversions, strict_compat_mode=True
        )
        assert str(qs.query).count('JOIN') == 4
        assert qs.exists()
        assert qs[0] == addon.current_version
        assert qs[0].min_compatible_version == '57.0'
        assert qs[0].max_compatible_version == '57.*'

    def test_latest_public_compatible_with_strict_compatibility_set(self):
        addon = addon_factory(
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
            file_kw={'strict_compatibility': True},
        )
        appversions = {
            'min': version_int('58.0'),
            'max': version_int('58.0'),
        }
        qs = Version.objects.latest_public_compatible_with(amo.FIREFOX.id, appversions)
        assert str(qs.query).count('JOIN') == 4
        assert not qs.exists()

        # Strict mode shouldn't change anything.
        qs = Version.objects.latest_public_compatible_with(
            amo.FIREFOX.id, appversions, strict_compat_mode=True
        )
        assert str(qs.query).count('JOIN') == 4
        assert not qs.exists()

        appversions = {
            'min': version_int('57.0'),
            'max': version_int('57.0'),
        }
        qs = Version.objects.latest_public_compatible_with(amo.FIREFOX.id, appversions)
        assert str(qs.query).count('JOIN') == 4
        assert qs.exists()
        assert qs[0] == addon.current_version
        assert qs[0].min_compatible_version == '57.0'
        assert qs[0].max_compatible_version == '57.*'

        # Strict mode shouldn't change anything.
        qs2 = Version.objects.latest_public_compatible_with(
            amo.FIREFOX.id, appversions, strict_compat_mode=True
        )
        assert list(qs2) == list(qs)


class TestVersionQuerySet(TestCase):
    def test_not_rejected(self):
        addon = addon_factory(version_kw={'version': '1.0'})
        version1 = addon.current_version
        version2 = version_factory(addon=addon, version='2.0')
        assert list(addon.versions.all().not_rejected().order_by('pk')) == [
            version1,
            version2,
        ]

        version1.is_user_disabled = True
        assert list(addon.versions.all().not_rejected().order_by('pk')) == [
            version1,
            version2,
        ]

        version1.is_user_disabled = False
        version1.file.update(status=amo.STATUS_DISABLED)
        assert list(addon.versions.all().not_rejected().order_by('pk')) == [version2]

        version1.file.update(
            status=amo.STATUS_DISABLED,
            status_disabled_reason=version1.file.STATUS_DISABLED_REASONS.VERSION_DELETE,
        )
        assert list(
            addon.versions(manager='unfiltered_for_relations')
            .all()
            .not_rejected()
            .order_by('pk')
        ) == [version1, version2]


class TestVersionManager(TestCase):
    def test_version_hidden_from_related_manager_after_deletion(self):
        """Test that a version that has been deleted should be hidden from the
        reverse relations, unless using the specific unfiltered_for_relations
        manager."""

        addon = addon_factory()
        version = addon.current_version
        assert addon.versions.get() == version

        # Deleted Version should be hidden from the reverse relation manager.
        version.delete()
        addon = Addon.objects.get(pk=addon.pk)
        assert addon.versions.count() == 0

        # But we should be able to see it using unfiltered_for_relations.
        assert addon.versions(manager='unfiltered_for_relations').count() == 1
        assert addon.versions(manager='unfiltered_for_relations').get() == version

    def test_version_still_accessible_from_foreign_key_after_deletion(self):
        """Test that a version that has been deleted should still be accessible
        from a foreign key."""

        version = addon_factory().current_version
        # We use VersionPreview as atm those are kept around, but any other
        # model that has a FK to Version and isn't deleted when a Version is
        # soft-deleted would work.
        version_preview = VersionPreview.objects.create(version=version)
        assert version_preview.version == version

        # Deleted Version should *not* prevent the version from being
        # accessible using the FK.
        version.delete()
        version_preview = VersionPreview.objects.get(pk=version_preview.pk)
        assert version_preview.version == version

    def test_should_have_due_date(self):
        user_factory(pk=settings.TASK_USER_ID)
        addon_kws = {
            'file_kw': {'is_signed': True, 'status': amo.STATUS_AWAITING_REVIEW}
        }

        addon_factory(**addon_kws)  # no due_date

        first_theme_initial_version = addon_factory(
            type=amo.ADDON_STATICTHEME, status=amo.STATUS_NOMINATED, **addon_kws
        ).versions.get()
        second_theme_second_version = version_factory(
            addon=addon_factory(type=amo.ADDON_STATICTHEME),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

        unknown_nhr = addon_factory(**addon_kws).current_version
        # having the needs_human_review flag means a due dute is needed
        NeedsHumanReview.objects.create(
            version=unknown_nhr, reason=NeedsHumanReview.REASONS.UNKNOWN
        )

        # Or if it's in a pre-review promoted group it will.
        recommended = addon_factory(**addon_kws).current_version
        self.make_addon_promoted(
            addon=recommended.addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        NeedsHumanReview.objects.create(
            version=recommended,
            reason=NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP,
        )

        # And not if it's a non-pre-review group
        self.make_addon_promoted(
            addon=recommended.addon, group_id=PROMOTED_GROUP_CHOICES.STRATEGIC
        )

        # A disabled version with a developer reply
        developer_reply = addon_factory(
            file_kw={'is_signed': False, 'status': amo.STATUS_DISABLED}
        ).versions.all()[0]
        NeedsHumanReview.objects.create(
            version=developer_reply, reason=NeedsHumanReview.REASONS.DEVELOPER_REPLY
        )

        # dsa related needs_human_review flag means due dates are needed also
        abuse_nhr = addon_factory(**addon_kws).current_version
        NeedsHumanReview.objects.create(
            version=abuse_nhr, reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        )
        appeal_nhr = addon_factory(**addon_kws).current_version
        NeedsHumanReview.objects.create(
            version=appeal_nhr, reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL
        )
        # throw in an inactive NHR that should be ignored
        NeedsHumanReview.objects.create(
            version=appeal_nhr,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
            is_active=False,
        )

        # And a version with multiple reasons
        multiple = addon_factory(**addon_kws).current_version
        self.make_addon_promoted(
            addon=recommended.addon, group_id=PROMOTED_GROUP_CHOICES.LINE
        )
        NeedsHumanReview.objects.create(
            version=multiple, reason=NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
        )

        NeedsHumanReview.objects.create(
            version=multiple, reason=NeedsHumanReview.REASONS.DEVELOPER_REPLY
        )
        NeedsHumanReview.objects.create(
            version=multiple, reason=NeedsHumanReview.REASONS.CINDER_ESCALATION
        )

        # Version with escalated abuse report
        escalated_abuse = addon_factory(**addon_kws).current_version
        NeedsHumanReview.objects.create(
            version=escalated_abuse, reason=NeedsHumanReview.REASONS.CINDER_ESCALATION
        )

        # Version with escalated appeal
        escalated_appeal = addon_factory(**addon_kws).current_version
        NeedsHumanReview.objects.create(
            version=escalated_appeal,
            reason=NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION,
        )

        forwarded_2nd_level_abuse = addon_factory(**addon_kws).current_version
        NeedsHumanReview.objects.create(
            version=forwarded_2nd_level_abuse,
            reason=NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE,
        )

        qs = Version.objects.should_have_due_date().order_by('id')
        assert list(qs) == [
            # absent addon with nothing special set
            first_theme_initial_version,
            second_theme_second_version,
            unknown_nhr,
            recommended,
            # absent promoted but not prereview addon
            developer_reply,
            abuse_nhr,
            appeal_nhr,
            multiple,
            escalated_abuse,
            escalated_appeal,
            forwarded_2nd_level_abuse,
        ]

    def test_get_due_date_reason_q_objects(self):
        q_objects = Version.objects.get_due_date_reason_q_objects()
        # Every NHR reason leads to a Q() object in that dict, plus the special
        # one for themes awaiting review.
        assert len(q_objects) == len(NeedsHumanReview.REASONS) + 1
        assert 'is_from_theme_awaiting_review' in q_objects
        for entry in NeedsHumanReview.REASONS.entries:
            assert entry.annotation in q_objects

    def test_get_due_date_reason_q_objects_filtering(self):
        self.test_should_have_due_date()  # to set up the Versions

        qs = Version.objects.all().order_by('id')
        # See test_should_have_due_date for order
        (
            _,  # addon with nothing special set
            first_theme_initial_version,
            _,  # second theme first version, already approved
            second_theme_second_version,
            unknown_nhr,
            recommended,
            developer_reply,
            abuse_nhr,
            appeal_nhr,
            multiple,
            escalated_abuse,
            escalated_appeal,
            forwarded_2nd_level_abuse,
        ) = list(qs)

        q_objects = Version.objects.get_due_date_reason_q_objects()
        method = Version.objects.order_by('id').filter

        assert list(method(q_objects['is_from_theme_awaiting_review'])) == [
            first_theme_initial_version,
            second_theme_second_version,
        ]

        assert list(method(q_objects['needs_human_review_cinder_escalation'])) == [
            multiple,
            escalated_abuse,
        ]

        assert list(
            method(q_objects['needs_human_review_cinder_appeal_escalation'])
        ) == [
            escalated_appeal,
        ]

        assert list(method(q_objects['needs_human_review_second_level_requeue'])) == [
            forwarded_2nd_level_abuse
        ]

        assert list(method(q_objects['needs_human_review_abuse_addon_violation'])) == [
            abuse_nhr
        ]

        assert list(method(q_objects['needs_human_review_addon_review_appeal'])) == [
            appeal_nhr
        ]

        assert list(method(q_objects['needs_human_review_unknown'])) == [unknown_nhr]

        assert list(
            method(q_objects['needs_human_review_belongs_to_promoted_group'])
        ) == [
            recommended,
            multiple,
        ]

        assert list(method(q_objects['needs_human_review_developer_reply'])) == [
            developer_reply,
            multiple,
        ]


class TestVersion(AMOPaths, TestCase):
    fixtures = ['base/addon_3615', 'base/admin']

    def setUp(self):
        super().setUp()
        self.version = Version.objects.get(pk=81551)
        self.task_user = user_factory(pk=settings.TASK_USER_ID)

    def target_mobile(self):
        app = amo.ANDROID.id
        app_vr = AppVersion.objects.create(application=app, version='1.0')
        ApplicationsVersions.objects.create(
            version=self.version, application=app, min=app_vr, max=app_vr
        )

    def test_compatible_apps(self):
        version = Version.objects.get(pk=81551)

        assert amo.FIREFOX in version.compatible_apps, 'Missing Firefox >_<'

        # We should be re-using the same Version instance in
        # ApplicationsVersions loaded from <Version>._create_compatible_apps().
        assert id(version) == id(version.compatible_apps[amo.FIREFOX].version)

    def _get_version(self, status):
        return addon_factory(file_kw={'status': status}).current_version

    def test_is_unreviewed(self):
        assert self._get_version(amo.STATUS_AWAITING_REVIEW).is_unreviewed
        assert not self._get_version(amo.STATUS_APPROVED).is_unreviewed

    def test_sources_provided(self):
        version = Version()
        assert not version.sources_provided

        version.source = self.file_fixture_path('webextension_no_id.zip')
        assert version.sources_provided

    def test_flag_if_sources_were_provided(self):
        user = UserProfile.objects.latest('pk')
        version = Version.objects.get(pk=81551)
        assert not version.sources_provided
        version.flag_if_sources_were_provided(user)
        assert not ActivityLog.objects.exists()
        assert not version.needshumanreview_set.count()

        version.source = self.file_fixture_path('webextension_no_id.zip')
        assert version.sources_provided
        version.flag_if_sources_were_provided(user)
        activity = ActivityLog.objects.for_versions(version).get()
        assert activity.action == amo.LOG.SOURCE_CODE_UPLOADED.id
        assert activity.user == user
        assert not version.needshumanreview_set.count()

    def test_flag_if_sources_were_provided_pending_rejection(self):
        user = UserProfile.objects.latest('pk')
        version = Version.objects.get(pk=81551)
        VersionReviewerFlags.objects.create(
            version=version,
            pending_rejection=datetime.now() + timedelta(days=1),
            pending_content_rejection=False,
            pending_rejection_by=user,
        )
        assert not version.sources_provided
        version.flag_if_sources_were_provided(user)
        assert not ActivityLog.objects.exists()
        assert not version.needshumanreview_set.count()

        version.source = self.file_fixture_path('webextension_no_id.zip')
        assert version.sources_provided
        version.flag_if_sources_were_provided(user)
        assert ActivityLog.objects.for_versions(version).count() == 2
        activity = (
            ActivityLog.objects.for_versions(version)
            .filter(action=amo.LOG.SOURCE_CODE_UPLOADED.id)
            .get()
        )
        assert activity.user == user
        assert version.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASONS.PENDING_REJECTION_SOURCES_PROVIDED
        )

    @mock.patch('olympia.versions.tasks.VersionPreview.delete_preview_files')
    def test_version_delete(self, delete_preview_files_mock):
        version = Version.objects.get(pk=81551)
        version_preview = VersionPreview.objects.create(version=version)
        assert version.file
        version_file = version.file
        version.delete()

        addon = Addon.objects.get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert Version.unfiltered.filter(addon=addon).exists()
        assert File.objects.filter(version=version).exists()
        version_file.reload()
        assert version_file.original_status == amo.STATUS_APPROVED
        assert (
            version_file.status_disabled_reason
            == File.STATUS_DISABLED_REASONS.VERSION_DELETE
        )
        delete_preview_files_mock.assert_called_with(
            sender=None, instance=version_preview
        )

    def test_version_delete_unlisted(self):
        version = Version.objects.get(pk=81551)
        version.update(channel=amo.CHANNEL_UNLISTED)
        self.test_version_delete()

    def test_version_hard_delete(self):
        version = Version.objects.get(pk=81551)
        VersionPreview.objects.create(version=version)
        assert version.file
        version.delete(hard=True)

        addon = Addon.objects.get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert not Version.unfiltered.filter(addon=addon).exists()
        assert not File.objects.filter(version=version).exists()
        assert not VersionPreview.objects.filter(version=version).exists()

    def test_version_delete_logs(self):
        user = UserProfile.objects.get(pk=55021)
        core.set_user(user)
        version = Version.objects.get(pk=81551)
        qs = ActivityLog.objects.all()
        assert qs.count() == 0
        version.delete()
        assert qs.count() == 2
        assert qs[0].action == amo.LOG.CHANGE_STATUS.id
        assert qs[0].user == self.task_user
        assert qs[1].action == amo.LOG.DELETE_VERSION.id
        assert qs[1].user == user

    def test_version_delete_clear_pending_rejection(self):
        user = user_factory()
        version = Version.objects.get(pk=81551)
        version_review_flags_factory(
            version=version,
            pending_rejection=datetime.now() + timedelta(days=1),
            pending_rejection_by=user,
            pending_content_rejection=False,
        )
        flags = VersionReviewerFlags.objects.get(version=version)
        assert flags.pending_rejection
        version.delete()
        flags.reload()
        assert not flags.pending_rejection
        assert not flags.pending_rejection_by
        assert flags.pending_content_rejection is None

    def test_version_disable_and_reenable(self):
        version = Version.objects.get(pk=81551)
        assert version.file.status == amo.STATUS_APPROVED

        version.is_user_disabled = True
        version.file.reload()
        assert version.file.status == amo.STATUS_DISABLED
        assert version.file.original_status == amo.STATUS_APPROVED
        assert (
            version.file.status_disabled_reason
            == File.STATUS_DISABLED_REASONS.DEVELOPER
        )

        version.is_user_disabled = False
        version.file.reload()
        assert version.file.status == amo.STATUS_APPROVED
        assert version.file.original_status == amo.STATUS_NULL
        assert version.file.status_disabled_reason == File.STATUS_DISABLED_REASONS.NONE

    def test_version_disable_after_mozilla_disabled(self):
        # Check that a user disable doesn't override mozilla disable
        version = Version.objects.get(pk=81551)
        version.file.update(status=amo.STATUS_DISABLED)

        version.is_user_disabled = True
        version.file.reload()
        assert version.file.status == amo.STATUS_DISABLED
        assert version.file.original_status == amo.STATUS_NULL
        assert version.file.status_disabled_reason == File.STATUS_DISABLED_REASONS.NONE

        version.file.update(original_status=amo.STATUS_APPROVED)
        for reason in File.STATUS_DISABLED_REASONS.values:
            if reason == File.STATUS_DISABLED_REASONS.DEVELOPER:
                # DEVELOPER is the only reason we expect to succeed
                continue
            version.file.update(status_disabled_reason=reason)
            version.is_user_disabled = False
            version.file.reload()
            assert version.file.status == amo.STATUS_DISABLED
            assert version.file.original_status == amo.STATUS_APPROVED

    def _reset_version(self, version):
        version.file.status = amo.STATUS_APPROVED
        version.deleted = False

    def test_version_is_public(self):
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)

        # Base test. Everything is in order, the version should be public.
        assert version.is_public()

        # Non-public file.
        self._reset_version(version)
        version.file.status = amo.STATUS_DISABLED
        assert not version.is_public()

        # Deleted version.
        self._reset_version(version)
        version.deleted = True
        assert not version.is_public()

        # Non-public addon.
        self._reset_version(version)

        is_public_path = 'olympia.addons.models.Addon.is_public'
        with mock.patch(is_public_path) as is_addon_public:
            is_addon_public.return_value = False
            assert not version.is_public()

    def test_is_compatible_by_default(self):
        # Base test for fixture before the rest. Should be compatible by
        # default.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        assert version.is_compatible_by_default

    def test_is_compatible_by_default_strict_opt_in(self):
        # Add-ons opting into strict compatibility should not be compatible
        # by default.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        file = version.file
        file.update(strict_compatibility=True)
        assert not version.is_compatible_by_default

    def test_get_url_path(self):
        assert self.version.get_url_path() == ('/en-US/firefox/addon/a3615/versions/')

    def test_valid_versions(self):
        addon = Addon.objects.get(id=3615)
        additional_version = version_factory(
            addon=addon, version='0.1', file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        version_factory(
            addon=addon, version='0.2', file_kw={'status': amo.STATUS_DISABLED}
        )
        assert list(Version.objects.valid()) == [additional_version, self.version]

    def test_approved_versions(self):
        addon = Addon.objects.get(id=3615)
        version_factory(
            addon=addon, version='0.1', file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        version_factory(
            addon=addon, version='0.2', file_kw={'status': amo.STATUS_DISABLED}
        )
        assert list(Version.objects.approved()) == [self.version]

    def test_unlisted_addon_get_url_path(self):
        self.make_addon_unlisted(self.version.addon)
        self.version.reload()
        assert self.version.get_url_path() == ''

    def test_source_upload_path(self):
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon, version='0.1')
        uploaded_name = source_upload_path(version, 'foo.tar.gz')
        assert uploaded_name.endswith('a3615-0.1-src.tar.gz')

    def test_source_upload_path_utf8_chars(self):
        addon = Addon.objects.get(id=3615)
        addon.update(slug='crosswarpex-확장')
        version = version_factory(addon=addon, version='0.1')
        uploaded_name = source_upload_path(version, 'crosswarpex-확장.tar.gz')
        assert uploaded_name.endswith('crosswarpex-확장-0.1-src.tar.gz')

    def test_is_ready_for_auto_approval(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert not version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        version.update(channel=amo.CHANNEL_LISTED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        # With the auto-approval disabled flag set, it's still considered
        # "ready", even though the auto_approve code won't approve it.
        del version.is_ready_for_auto_approval
        AddonReviewerFlags.objects.create(addon=addon, auto_approval_disabled=False)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_STATICTHEME)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert not version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_LPAPP)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_DICT)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        # Test with an unlisted version. Note that it's the only version, so
        # the add-on status is reset to STATUS_NULL at this point.
        del version.is_ready_for_auto_approval
        version.update(channel=amo.CHANNEL_UNLISTED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        # Retest with an unlisted version again and the addon being approved or
        # nominated
        del version.is_ready_for_auto_approval
        addon.reload()
        addon.update(status=amo.STATUS_NOMINATED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(status=amo.STATUS_APPROVED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

    def test_is_ready_for_auto_approval_addon_status(self):
        addon = Addon.objects.get(id=3615)
        addon.status = amo.STATUS_NOMINATED
        version = addon.current_version
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(status=amo.STATUS_DISABLED)
        assert not version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

    def test_transformer_auto_approvable(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert not version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        version.update(channel=amo.CHANNEL_LISTED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        # With the auto-approval disabled flag set, it's still considered
        # "ready", even though the auto_approve code won't approve it.
        del version.is_ready_for_auto_approval
        AddonReviewerFlags.objects.create(addon=addon, auto_approval_disabled=False)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_STATICTHEME)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert not version.is_ready_for_auto_approval

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_LPAPP)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_DICT)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        # Test with an unlisted version. Note that it's the only version, so
        # the add-on status is reset to STATUS_NULL at this point.
        del version.is_ready_for_auto_approval
        version.update(channel=amo.CHANNEL_UNLISTED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        # Retest with an unlisted version again and the addon being approved or
        # nominated
        del version.is_ready_for_auto_approval
        addon.reload()
        addon.update(status=amo.STATUS_NOMINATED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        del version.is_ready_for_auto_approval
        addon.update(status=amo.STATUS_APPROVED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

    def test_was_auto_approved(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        assert not version.was_auto_approved

        AutoApprovalSummary.objects.create(version=version, verdict=amo.AUTO_APPROVED)
        assert version.was_auto_approved

        version.file.update(status=amo.STATUS_DISABLED)
        assert version.was_auto_approved  # Still was originally auto-approved.

    def test_should_have_due_date_listed(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version

        assert not version.should_have_due_date
        # having the needs_human_review flag means a due dute is needed
        needs_human_review = NeedsHumanReview.objects.create(version=version)
        assert version.should_have_due_date

        # Just a version awaiting review will be auto approved so won't need a due date
        needs_human_review.update(is_active=False)
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        assert not version.should_have_due_date

        # But if it has a NHR it will.
        nhr = version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
        )
        assert version.should_have_due_date

        # And not if it is dropped
        nhr.update(is_active=False)
        assert not version.should_have_due_date

        # But yes if another nhr is added.
        nhr = version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        assert version.should_have_due_date

    def test_should_have_due_date_listed_theme_incomplete(self):
        addon = addon_factory(
            status=amo.STATUS_NULL,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version = addon.versions.get()

        # Listed version of an incomplete add-on should not have a due date.
        assert not version.should_have_due_date

        # Unless they have the explicit a NeedsHumanReview flag active.
        needs_human_review = NeedsHumanReview.objects.create(version=version)
        assert version.should_have_due_date

        needs_human_review.update(is_active=False)
        assert not version.should_have_due_date

    def test_should_have_due_date_listed_theme_nominated(self):
        addon = addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version = addon.versions.get()

        # Listed version of a nominated add-on should have a due date.
        assert version.should_have_due_date

    def test_should_have_due_date_listed_theme_public(self):
        addon = addon_factory(type=amo.ADDON_STATICTHEME)
        version = version_factory(
            addon=addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )

        # New listed version of an approved theme should have a due date.
        assert version.should_have_due_date

    def test_should_have_due_date_unlisted_theme(self):
        addon = addon_factory(
            status=amo.STATUS_NULL,
            type=amo.ADDON_STATICTHEME,
            version_kw={'channel': amo.CHANNEL_UNLISTED},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version = addon.versions.get()

        # Unlisted version of an incomplete add-on should have a due date.
        assert version.should_have_due_date

        # Whether they have the explicit a NeedsHumanReview flag active or not.
        needs_human_review = NeedsHumanReview.objects.create(version=version)
        assert version.should_have_due_date

        needs_human_review.update(is_active=False)
        assert version.should_have_due_date

    def _test_should_have_due_date_disabled(self, channel):
        addon = Addon.objects.get(id=3615)
        version = addon.versions.get()
        version.update(channel=channel)
        assert version.needshumanreview_set.count() == 0
        assert not version.should_have_due_date

        # Any non-disabled status with needs_human_review is enough to get a
        # due date, even if not signed.
        nhr = NeedsHumanReview.objects.create(version=version)
        version.file.update(is_signed=False, status=amo.STATUS_AWAITING_REVIEW)
        assert version.should_have_due_date

        # If disabled and not signed, it should lose the due date even if it
        # was needing human review: there is no threat, reviewers don't need to
        # review it anymore.
        version.file.update(is_signed=False, status=amo.STATUS_DISABLED)
        assert not version.should_have_due_date

        # If was reported for abuse or appealed should also get a due_date,
        # even if unsigned.
        nhr.update(reason=NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL)
        assert version.should_have_due_date

        # Otherwise it needs to be signed to get a due date.
        nhr.update(reason=NeedsHumanReview.REASONS.UNKNOWN)
        assert not version.should_have_due_date
        version.file.update(is_signed=True)
        assert version.should_have_due_date

        # Even if deleted (which internally disables the file), as long as it
        # was signed and needs human review, it should keep the due date.
        version.file.update(is_signed=True)
        version.delete()
        assert version.should_have_due_date

    def test_should_have_due_date_disabled_listed(self):
        self._test_should_have_due_date_disabled(amo.CHANNEL_LISTED)

    def test_should_have_due_date_disabled_unlisted(self):
        self._test_should_have_due_date_disabled(amo.CHANNEL_UNLISTED)

    def test_should_have_due_date_unlisted(self):
        addon = Addon.objects.get(id=3615)
        self.make_addon_unlisted(addon)
        version = addon.versions.first()

        assert not version.should_have_due_date
        # having the needs_human_review flag means a due dute is needed
        needs_human_review = NeedsHumanReview.objects.create(version=version)
        assert version.should_have_due_date

        # Just a version awaiting review will be auto approved so won't need a due date
        needs_human_review.update(is_active=False)
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        assert not version.should_have_due_date

        # But if it has a NHR it will.
        nhr = version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
        )
        assert version.should_have_due_date

        # And not if it is dropped
        nhr.update(is_active=False)
        assert not version.should_have_due_date

        # But yes if another nhr is added.
        nhr = version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        assert version.should_have_due_date

    def test_should_have_due_date_developer_reply(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        assert version.needshumanreview_set.count() == 0
        assert not version.should_have_due_date

        needs_human_review = version.needshumanreview_set.create(
            is_active=False, reason=NeedsHumanReview.REASONS.DEVELOPER_REPLY
        )
        assert not version.should_have_due_date

        needs_human_review.update(is_active=True)
        assert version.should_have_due_date

        # status/is_signed shouldn't matter for developer replies
        version.file.update(is_signed=False, status=amo.STATUS_DISABLED)
        assert version.should_have_due_date

        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        assert version.should_have_due_date

        version.file.update(is_signed=True, status=amo.STATUS_APPROVED)
        assert version.should_have_due_date

        version.file.update(status=amo.STATUS_DISABLED)
        assert version.should_have_due_date

        version.file.update(is_signed=False)
        for reason in NeedsHumanReview.REASONS.values.keys() - [
            NeedsHumanReview.REASONS.DEVELOPER_REPLY,
            NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
            NeedsHumanReview.REASONS.CINDER_ESCALATION,
            NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION,
            NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL,
            NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE,
        ]:
            # Every other reason shouldn't result in a due date since the
            # version is disabled and not signed at this point.
            needs_human_review.update(reason=reason)
            assert not version.should_have_due_date

    def test_reset_due_date(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        # set up the version so it should and does have a due date
        version.needshumanreview_set.create()
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        assert version.should_have_due_date
        assert version.due_date

        # if it has a due date, and should have one, it can be overriden with a new date
        new_date = self.days_ago(1)
        version.reset_due_date(new_date)
        assert version.due_date == new_date

        # but if we don't specify a due date it won't be changed
        version.reset_due_date()
        assert version.due_date == new_date

        # unless it should have a due date and doesn't currently.
        version.update(due_date=None, _signal=False)  # no signals
        assert version.due_date is None
        version.reset_due_date()
        self.assertCloseToNow(version.due_date, now=get_review_due_date())

        # case when version shouldn't have a due_date but does
        version.file.update(status=amo.STATUS_DISABLED, _signal=False)
        version.needshumanreview_set.update(is_active=False)
        assert not version.should_have_due_date
        assert version.due_date
        version.reset_due_date()
        assert not version.due_date

    def test_needs_human_review_signal(self):
        addon = addon_factory()
        version = addon.current_version
        assert not version.due_date

        needs_human_review = NeedsHumanReview.objects.create(version=version)
        assert version.reload().due_date

        needs_human_review.update(is_active=False)
        assert not version.reload().due_date

    def test_transformer_license(self):
        addon = Addon.objects.get(id=3615)
        version1 = version_factory(addon=addon)
        license = license_factory(name='Second License', text='Second License Text')
        version2 = version_factory(addon=addon, license=license)

        qs = Version.objects.filter(pk__in=(version1.pk, version2.pk)).no_transforms()
        with self.assertNumQueries(5):
            # - 1 for the versions
            # - 2 for the licenses (1 for each version)
            # - 2 for the licenses translations (1 for each version)
            for version in qs.all():
                assert version.license.name

        # Using the transformer should prefetch licenses and name translations.
        # License text should be deferred.
        with self.assertNumQueries(3):
            # - 1 for the versions
            # - 1 for the licenses
            # - 1 for the licenses translations (name)
            for version in qs.transform(Version.transformer_license).all():
                assert 'text_id' in version.license.get_deferred_fields()
                assert version.license.name

    def test_promoted_can_be_disabled_and_deleted(self):
        addon = Addon.objects.get(id=3615)
        # A non-promoted addon can have it's versions disabled.
        assert addon.current_version.can_be_disabled_and_deleted()

        self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        addon = addon.reload()
        assert PROMOTED_GROUP_CHOICES.RECOMMENDED in addon.promoted_groups().group_id
        # But a promoted one, that's in a prereview group, can't be disabled
        assert not addon.current_version.can_be_disabled_and_deleted()

        previous_version = addon.current_version
        version_factory(addon=addon, promotion_approved=True)
        addon = addon.reload()
        assert previous_version != addon.current_version
        assert addon.current_version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        assert previous_version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        # unless the previous version is also approved for the same group
        assert addon.current_version.can_be_disabled_and_deleted()
        assert previous_version.can_be_disabled_and_deleted()

        # double-check by changing the approval of previous version
        previous_version.promoted_versions.update(
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.LINE
            )
        )
        assert not addon.current_version.can_be_disabled_and_deleted()
        previous_version.promoted_versions.update(
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            )
        )

        # Check the scenario when some of the previous versions are approved
        # but not the most recent previous - i.e. the one that would become the
        # new current_version.
        version_a = previous_version.reload()
        version_b = addon.current_version
        version_c = version_factory(addon=addon)
        version_d = version_factory(addon=addon, promotion_approved=True)
        version_c.is_user_disabled = True  # disabled version_c
        addon = addon.reload()
        version_b = version_b.reload()
        assert version_d == addon.current_version
        assert version_a.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        assert version_b.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        # ignored because disabled
        assert not version_c.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        assert version_d.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        assert version_a.can_be_disabled_and_deleted()
        assert version_b.can_be_disabled_and_deleted()
        assert version_c.can_be_disabled_and_deleted()
        assert version_d.can_be_disabled_and_deleted()
        assert PROMOTED_GROUP_CHOICES.RECOMMENDED in addon.promoted_groups().group_id
        # now un-approve version_b
        version_b.promoted_versions.all().delete()
        assert version_a.can_be_disabled_and_deleted()
        assert version_b.can_be_disabled_and_deleted()
        assert version_c.can_be_disabled_and_deleted()
        assert not version_d.can_be_disabled_and_deleted()
        assert PROMOTED_GROUP_CHOICES.RECOMMENDED in addon.promoted_groups().group_id

    def test_unbadged_non_prereview_promoted_can_be_disabled_and_deleted(self):
        addon = Addon.objects.get(id=3615)
        self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.LINE, approve_version=True
        )
        assert PROMOTED_GROUP_CHOICES.LINE in addon.promoted_groups().group_id
        # it's the only version of a group that requires pre-review and is
        # badged, so can't be deleted.
        assert not addon.current_version.can_be_disabled_and_deleted()

        # STRATEGIC isn't pre-reviewd or badged, so it's okay though
        addon.promotedaddon.all().delete()
        self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.STRATEGIC, approve_version=True
        )
        assert PROMOTED_GROUP_CHOICES.STRATEGIC in addon.promoted_groups().group_id
        assert addon.current_version.can_be_disabled_and_deleted()

        # SPOTLIGHT is pre-reviewed but not badged, so it's okay too
        self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.SPOTLIGHT, approve_version=True
        )
        assert PROMOTED_GROUP_CHOICES.SPOTLIGHT in addon.promoted_groups().group_id
        assert addon.current_version.can_be_disabled_and_deleted()

    def test_can_be_disabled_and_deleted_querycount(self):
        addon = Addon.objects.get(id=3615)
        version_factory(addon=addon)
        self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        addon.reload()
        with self.assertNumQueries(3):
            # 1. query whether the add-on has promotions or not
            # 2. query promotions
            # 3. query promoted versions
            assert not addon.current_version.can_be_disabled_and_deleted()

    def test_is_blocked(self):
        version = Addon.objects.get(id=3615).current_version
        assert version.is_blocked is False

        block = Block.objects.create(addon=version.addon, updated_by=user_factory())
        assert version.reload().is_blocked is False

        blockversion = BlockVersion.objects.create(block=block, version=version)
        assert version.reload().is_blocked is True

        blockversion.update(version=version_factory(addon=version.addon))
        version.refresh_from_db()
        assert version.is_blocked is False

    def test_pending_rejection_property(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        # No flags: None
        assert version.pending_rejection is None
        # Flag present, value is None (default): None.
        flags = version_review_flags_factory(version=version)
        assert flags.pending_rejection is None
        assert version.pending_rejection is None
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(
            pending_rejection=in_the_past,
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )
        assert version.pending_rejection == in_the_past
        assert not version.pending_content_rejection

    def test_pending_content_rejection_property(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        # No flags: None
        assert version.pending_content_rejection is None
        # Flag present, value is None (default): None.
        flags = version_review_flags_factory(version=version)
        assert flags.pending_content_rejection is None
        assert version.pending_content_rejection is None
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(
            pending_rejection=in_the_past,
            pending_rejection_by=user_factory(),
            pending_content_rejection=True,
        )
        assert version.pending_rejection == in_the_past
        assert version.pending_content_rejection

    def test_pending_rejection_by_property(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        user = user_factory()
        # No flags: None
        assert version.pending_rejection_by is None
        # Flag present, value is None (default): None.
        flags = version_review_flags_factory(version=version)
        assert flags.pending_rejection_by is None
        assert version.pending_rejection_by is None
        # Flag present, value is a user.
        flags.update(
            pending_rejection=self.days_ago(1),
            pending_rejection_by=user,
            pending_content_rejection=False,
        )
        assert version.pending_rejection_by == user

    def test_pending_rejection_by_cleared_when_pending_rejection_cleared(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        user = user_factory()
        flags = version_review_flags_factory(
            version=version,
            pending_rejection=self.days_ago(1),
            pending_rejection_by=user,
        )
        assert flags.pending_rejection
        assert flags.pending_rejection_by == user

        # Clear pending_rejection. pending_rejection_by should be cleared as well.
        flags.update(pending_rejection=None)
        assert flags.pending_rejection is None
        assert flags.pending_rejection_by is None

    def test_pending_content_rejection_cleared_when_pending_rejection_cleared(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        flags = version_review_flags_factory(
            version=version,
            pending_rejection=self.days_ago(1),
            pending_content_rejection=True,
        )
        assert flags.pending_rejection
        assert flags.pending_content_rejection is True

        # Clear pending_rejection. pending_content_rejection should be cleared as well.
        flags.update(pending_rejection=None)
        assert flags.pending_rejection is None
        assert flags.pending_content_rejection is None

    def test_approved_for_groups(self):
        version = addon_factory().current_version
        assert version.approved_for_groups == []

        # give it some promoted approvals
        PromotedApproval.objects.create(
            version=version,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.LINE
            ),
            application_id=amo.FIREFOX.id,
        )
        PromotedApproval.objects.create(
            version=version,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.ANDROID.id,
        )

        del version.approved_for_groups
        assert version.approved_for_groups == [
            (PROMOTED_GROUPS_BY_ID.get(PROMOTED_GROUP_CHOICES.LINE), amo.FIREFOX),
            (
                PROMOTED_GROUPS_BY_ID.get(PROMOTED_GROUP_CHOICES.RECOMMENDED),
                amo.ANDROID,
            ),
        ]

    def test_transform_promoted(self):
        version_a = addon_factory().current_version
        version_b = addon_factory().current_version
        versions = Version.objects.filter(
            id__in=(version_a.id, version_b.id)
        ).transform(Version.transformer_promoted)
        list(versions)  # to evaluate the queryset
        with self.assertNumQueries(0):
            assert versions[0].approved_for_groups == []
            assert versions[1].approved_for_groups == []

        # give them some promoted approvals
        PromotedApproval.objects.create(
            version=version_a,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.LINE
            ),
            application_id=amo.FIREFOX.id,
        )
        PromotedApproval.objects.create(
            version=version_a,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.FIREFOX.id,
        )
        PromotedApproval.objects.create(
            version=version_b,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.FIREFOX.id,
        )
        PromotedApproval.objects.create(
            version=version_b,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.ANDROID.id,
        )

        versions = Version.objects.filter(
            id__in=(version_a.id, version_b.id)
        ).transform(Version.transformer_promoted)
        list(versions)  # to evaluate the queryset

        def _sort(group_app_tuple):
            return group_app_tuple[0].id, group_app_tuple[1].id

        with self.assertNumQueries(0):
            assert sorted(versions[1].approved_for_groups, key=_sort) == sorted(
                [
                    (
                        PROMOTED_GROUPS_BY_ID.get(PROMOTED_GROUP_CHOICES.RECOMMENDED),
                        amo.FIREFOX,
                    ),
                    (
                        PROMOTED_GROUPS_BY_ID.get(PROMOTED_GROUP_CHOICES.LINE),
                        amo.FIREFOX,
                    ),
                ],
                key=_sort,
            )
            assert sorted(versions[0].approved_for_groups, key=_sort) == sorted(
                [
                    (
                        PROMOTED_GROUPS_BY_ID.get(PROMOTED_GROUP_CHOICES.RECOMMENDED),
                        amo.FIREFOX,
                    ),
                    (
                        PROMOTED_GROUPS_BY_ID.get(PROMOTED_GROUP_CHOICES.RECOMMENDED),
                        amo.ANDROID,
                    ),
                ],
                key=_sort,
            )

    def test_version_string(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        assert isinstance(version.version, VersionString)
        assert version.version == '2.1.072'
        assert version.version == '2.1.72.0'  # VersionString magic
        assert version.version > '2.1.072pre'
        # works after an update
        version.update(version=VersionString('2.00123'))
        assert isinstance(version.version, VersionString)
        assert version.version == '2.00123'
        assert version.version == '2.123.0.0'
        assert version.version > '2.00123a4'
        # updating a flat string still works
        version.update(version='3.3')
        assert isinstance(version.version, VersionString)
        assert version.version == '3.03.0'
        version = version.reload()
        assert isinstance(version.version, VersionString)
        assert version.version == '3.03.0'
        # and directly assigning to the field and saving too
        version.version = '5.1b4'
        assert isinstance(version.version, VersionString)
        version.save()
        assert isinstance(version.version, VersionString)
        version = version.reload()
        assert version.version == '5.1b4'

    def test_version_kept_when_license_deleted(self):
        license = License.objects.create(name='MyLicense')
        self.version.update(license=license)
        license.delete()
        assert not License.objects.filter(pk=license.pk).exists()
        assert Version.objects.filter(pk=self.version.pk).exists()

    def test_get_review_status_display(self):
        assert (
            self.version.get_review_status_display()
            == 'Approved'
            == self.version.file.get_review_status_display()
        )
        self.version.file.update(status=amo.STATUS_DISABLED)
        assert self.version.get_review_status_display() == 'Unreviewed'
        self.version.update(human_review_date=datetime.now())
        assert self.version.get_review_status_display() == 'Rejected'
        self.version.file.update(
            status_disabled_reason=File.STATUS_DISABLED_REASONS.DEVELOPER
        )
        assert self.version.get_review_status_display() == 'Disabled by Developer'
        self.version.update(deleted=True)
        assert self.version.get_review_status_display() == 'Deleted'

        # Testing show_auto_approval_and_delay_reject:
        # See test_version_get_review_status_for_auto_approval_and_delay_reject for full
        # testing of the combinations when show_auto_approval_and_delay_reject is True.
        self.version.update(deleted=False)
        self.version.file.update(
            status=amo.STATUS_APPROVED, original_status=amo.STATUS_NULL
        )
        AutoApprovalSummary.objects.create(version=self.version)
        assert self.version.get_review_status_display(False) == 'Approved'
        assert self.version.get_review_status_display(True) == 'Approved, Manual'

    def test_delete_soft_blocks_version(self):
        developer = user_factory()
        addon = addon_factory(users=[developer])
        version = addon.current_version

        version.delete()

        assert Block.objects.all()
        block = Block.objects.get()
        assert list(block.blockversion_set.values_list('version', flat=True)) == [
            version.id
        ]
        assert (
            block.blockversion_set.filter(block_type=BlockType.SOFT_BLOCKED).count()
            == 1
        )
        assert len(mail.outbox) == 0

    def test_delete_of_already_blocked_version_doesnt_soften_block(self):
        addon = addon_factory()
        hard_blocked_version = version_factory(
            addon=addon, file_kw={'status': amo.STATUS_DISABLED}
        )
        block = Block.objects.create(guid=addon.guid, updated_by=user_factory())
        BlockVersion.objects.create(
            block=block,
            version=hard_blocked_version,
        )

        hard_blocked_version.delete()

        assert list(block.blockversion_set.values_list('version', flat=True)) == [
            hard_blocked_version.id,
        ]
        assert (
            hard_blocked_version.blockversion.reload().block_type == BlockType.BLOCKED
        )
        assert len(mail.outbox) == 0


@pytest.mark.parametrize(
    'addon_status,file_status,is_unreviewed',
    [
        (amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW, True),
        (amo.STATUS_NOMINATED, amo.STATUS_NOMINATED, True),
        (amo.STATUS_NOMINATED, amo.STATUS_APPROVED, False),
        (amo.STATUS_NOMINATED, amo.STATUS_DISABLED, False),
        (amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW, True),
        (amo.STATUS_APPROVED, amo.STATUS_NOMINATED, True),
        (amo.STATUS_APPROVED, amo.STATUS_APPROVED, False),
        (amo.STATUS_APPROVED, amo.STATUS_DISABLED, False),
    ],
)
def test_unreviewed_files(db, addon_status, file_status, is_unreviewed):
    """Files that need to be reviewed are returned by version.unreviewed_files."""
    addon = amo.tests.addon_factory(status=addon_status, guid='foo')
    version = addon.current_version
    file_ = version.file
    file_.update(status=file_status)
    # If the addon is public, and we change its only file to something else
    # than public, it'll change to unreviewed.
    addon.update(status=addon_status)
    assert addon.reload().status == addon_status
    assert file_.reload().status == file_status


@pytest.mark.django_db
@pytest.mark.parametrize(
    'file_status, pending_rejection, auto_summary, verdict, confirmed, output',
    (
        (
            amo.STATUS_AWAITING_REVIEW,
            datetime(2025, 1, 22, 8, 9, 10),
            True,
            amo.AUTO_APPROVED,
            False,
            'Delay-rejected, scheduled for 2025-01-22 08:09:10',
        ),
        (
            amo.STATUS_APPROVED,
            datetime(2025, 1, 23, 10, 11, 12),
            True,
            amo.AUTO_APPROVED,
            False,
            'Delay-rejected, scheduled for 2025-01-23 10:11:12',
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
            True,  # there is an AutoApprovalSummary
            amo.NOT_AUTO_APPROVED,
            False,
            'Approved, Manual',
        ),
        (
            amo.STATUS_APPROVED,
            None,
            False,  # there isn't an AutoApprovalSummary
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
            None,
        ),
    ),
)
def test_version_get_review_status_for_auto_approval_and_delay_reject(
    file_status, pending_rejection, auto_summary, verdict, confirmed, output
):
    version = addon_factory(file_kw={'status': file_status}).find_latest_version(None)
    if pending_rejection:
        version_review_flags_factory(
            version=version, pending_rejection=pending_rejection
        )
    if auto_summary:
        AutoApprovalSummary.objects.create(
            version=version, verdict=verdict, confirmed=confirmed
        )
    assert output == version.get_review_status_for_auto_approval_and_delay_reject()


class TestVersionFromUpload(UploadMixin, TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
        }
        for version in versions:
            AppVersion.objects.get_or_create(
                application=amo.FIREFOX.id, version=version
            )
            AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version=version
            )

    def setUp(self):
        super().setUp()
        self.upload = self.get_upload(self.filename)
        self.addon = Addon.objects.get(id=3615)
        self.addon.update(guid='@webextension-guid')
        self.selected_app = amo.FIREFOX.id
        self.dummy_parsed_data = {'manifest_version': 2, 'version': '0.1'}
        self.fake_user = user_factory()


class TestExtensionVersionFromUpload(TestVersionFromUpload):
    filename = 'webextension.xpi'

    def setUp(self):
        super().setUp()

    def test_upload_already_attached_to_different_addon(self):
        # The exception isn't necessarily caught, but it's fine to 500 and go
        # to Sentry in this case - this isn't supposed to happen.
        self.upload.update(addon=addon_factory())
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    def test_addon_disabled(self):
        # The exception isn't necessarily caught, but it's fine to 500 and go
        # to Sentry in this case - this isn't supposed to happen.
        self.addon.update(status=amo.STATUS_DISABLED)
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    def test_addon_is_attached_to_upload_if_it_wasnt(self):
        assert self.upload.addon is None
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert version
        self.upload.reload()
        assert self.upload.addon == self.addon

    def test_from_upload_no_user(self):
        self.upload.user = None
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    def test_from_upload_no_ip_address(self):
        self.upload.ip_address = None
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    def test_from_upload_no_source(self):
        self.upload.source = None
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    def _test_logging(self, source):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        user.update(last_login_ip='1.2.3.4')
        self.upload.update(
            user=user,
            ip_address='5.6.7.8',
            source=source,
        )
        with self.assertLogs(logger='z.versions', level='INFO') as logs:
            version = Version.from_upload(
                self.upload,
                self.addon,
                amo.CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )
        assert len(logs.records) == 2
        assert logs.records[0].message == (
            f'New version: {version!r} ({version.pk}) from {self.upload!r}'
        )
        expected_extra = {
            'email': user.email,
            'guid': self.addon.guid,
            'upload': self.upload.uuid.hex,
            'user_id': user.pk,
            'from_api': True,
        }
        for key, value in expected_extra.items():
            assert getattr(logs.records[0], key) == value

        task_user = get_task_user()
        assert ActivityLog.objects.count() == 2
        activities = ActivityLog.objects.all()
        assert activities[0].action == amo.LOG.CHANGE_STATUS.id
        assert activities[0].arguments == [self.addon, amo.STATUS_APPROVED]
        assert activities[0].user == task_user
        assert activities[1].action == amo.LOG.ADD_VERSION.id
        assert activities[1].arguments == [version, self.addon]
        assert activities[1].user == user

    def test_logging_signing_api(self):
        self._test_logging(amo.UPLOAD_SOURCE_SIGNING_API)

    def test_logging_addons_api(self):
        self._test_logging(amo.UPLOAD_SOURCE_ADDON_API)

    def test_carry_over_old_license(self):
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert version.license_id == self.addon.current_version.license_id

    def test_mozilla_signed_extension(self):
        self.dummy_parsed_data['is_mozilla_signed_extension'] = True
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert version.is_mozilla_signed
        assert version.approval_notes == (
            'This version has been signed with Mozilla internal certificate.'
        )

    def test_carry_over_license_no_version(self):
        self.addon.versions.all().delete()
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert version.license_id is None

    def test_app_versions(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == '*'

    def test_compatibility_just_app(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            compatibility={
                amo.FIREFOX: ApplicationsVersions(application=amo.FIREFOX.id)
            },
            parsed_data=parsed_data,
        )
        assert [amo.FIREFOX] == list(version.compatible_apps)
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == '*'

    def test_compatibility_min_max_too(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            compatibility={
                amo.ANDROID: ApplicationsVersions(
                    application=amo.ANDROID.id,
                    min=AppVersion.objects.get_or_create(
                        application=amo.ANDROID.id, version='45.0'
                    )[0],
                    max=AppVersion.objects.get_or_create(
                        application=amo.ANDROID.id, version='67'
                    )[0],
                )
            },
            parsed_data=parsed_data,
        )
        assert [amo.ANDROID] == list(version.compatible_apps)
        app = version.compatible_apps[amo.ANDROID]
        assert app.min.version == '45.0'
        assert app.max.version == '67'

    def test_compatible_apps_is_pre_generated(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        # We mock File.from_upload() to prevent it from accessing
        # version.compatible_apps early - we want to test that the cache has
        # been generated regardless.

        def fake_file(*args, **kwargs):
            return File(version=kwargs['version'])

        with mock.patch('olympia.files.models.File.from_upload', side_effect=fake_file):
            version = Version.from_upload(
                self.upload,
                self.addon,
                amo.CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=parsed_data,
            )
        # Alter the ApplicationsVersions through an objects.update() so that
        # the custom save() method is not used - compatible_apps should not be
        # updated.
        ApplicationsVersions.objects.filter(version=version).update(
            application=amo.ANDROID.id
        )
        assert amo.ANDROID not in version.compatible_apps
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == '*'

        # Clear cache and check again, it should be updated.
        del version._compatible_apps
        assert amo.ANDROID in version.compatible_apps
        assert amo.FIREFOX not in version.compatible_apps
        app = version.compatible_apps[amo.ANDROID]
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == '*'

    def test_compatible_apps_cloned_if_passed_existing_instances(self):
        # If we're passed ApplicationsVersions instances that already exist in
        # the database (with a pk) in `compatibility` then we clone them
        # instead of re-using them.
        existing_version = version_factory(
            addon=self.addon,
            application=amo.FIREFOX.id,
            min_app_version='48.0',
            max_app_version='*',
        )

        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        new_version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            compatibility=existing_version.compatible_apps,
            parsed_data=parsed_data,
        )
        # Make sure we're not testing with cached data
        del existing_version._compatible_apps

        assert existing_version.compatible_apps  # Still there, untouched.
        assert amo.FIREFOX in new_version.compatible_apps
        assert (
            new_version.compatible_apps[amo.FIREFOX].min
            == existing_version.compatible_apps[amo.FIREFOX].min
        )
        assert (
            new_version.compatible_apps[amo.FIREFOX].max
            == existing_version.compatible_apps[amo.FIREFOX].max
        )
        # Shouldn't be the same instance.
        assert existing_version.compatible_apps != new_version.compatible_apps

        # Really make sure - includes the one from the original version in
        # fixtures too.
        assert ApplicationsVersions.objects.count() == 3

    def test_version_number(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.version == '0.0.1'

    def test_filename(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.file.file.name == '15/3615/3615/a3615-0.0.1.zip'

    def test_track_upload_time(self):
        # Set created time back (just for sanity) otherwise the delta
        # would be in the microsecond range.
        self.upload.update(created=datetime.now() - timedelta(days=1))

        mock_path = 'olympia.versions.models.statsd.'
        with (
            mock.patch(f'{mock_path}timing') as mock_timing,
            mock.patch(f'{mock_path}incr') as mock_incr,
        ):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

            upload_start = utc_millesecs_from_epoch(self.upload.created)
            now = utc_millesecs_from_epoch()
            rough_delta = now - upload_start
            actual_delta = mock_timing.call_args[0][1]

            fuzz = 2000  # 2 seconds
            assert actual_delta >= (rough_delta - fuzz) and actual_delta <= (
                rough_delta + fuzz
            )
            mock_incr.assert_called_with('devhub.version_created_from_upload.extension')

    def test_due_date_inherited_for_updates(self):
        assert self.addon.status == amo.STATUS_APPROVED
        self.addon.current_version.update(due_date=self.days_ago(2))
        self.addon.current_version.needshumanreview_set.create()
        pending_version = version_factory(
            addon=self.addon,
            due_date=self.days_ago(1),
            version='9.9',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        pending_version.needshumanreview_set.create()
        assert pending_version.due_date
        upload_version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        # Check twice: on the returned instance and in the database, in case
        # a signal acting on the same version but different instance updated
        # it.
        assert upload_version.due_date == pending_version.due_date
        upload_version.reload()
        assert upload_version.due_date == pending_version.due_date

    def test_due_date_inherit_from_most_recent(self):
        self.addon.current_version.needshumanreview_set.create()
        self.addon.current_version.update(due_date=self.days_ago(3))
        # In theory it isn't possible to get 2 listed versions awaiting review,
        # but this test ensures we inherit from the most recent version if
        # somehow this was to happen.
        pending_version = version_factory(
            addon=self.addon,
            due_date=self.days_ago(2),
            version='9.9',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        pending_version.needshumanreview_set.create()
        assert pending_version.due_date
        pending_version2 = version_factory(
            addon=self.addon,
            due_date=self.days_ago(1),
            version='10.0',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        pending_version2.needshumanreview_set.create()
        assert pending_version2.due_date > pending_version.due_date
        oldest_due_date = pending_version2.due_date
        upload_version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        # Check twice: on the returned instance and in the database, in case
        # a signal acting on the same version but different instance updated
        # it.
        assert upload_version.due_date == oldest_due_date
        upload_version.reload()
        assert upload_version.due_date == oldest_due_date

    def test_do_not_inherit_needs_human_review_from_other_addon(self):
        extra_addon = addon_factory()
        NeedsHumanReview.objects.create(version=extra_addon.current_version)
        upload_version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        # Check twice: on the returned instance and in the database, in case
        # a signal acting on the same version but different instance updated
        # it.
        assert not upload_version.due_date
        upload_version.reload()
        assert not upload_version.due_date
        assert upload_version.needshumanreview_set.count() == 0

    def test_inherit_needs_human_review_with_due_date(self):
        user = user_factory()
        core.set_user(user)
        due_date = get_review_due_date()
        NeedsHumanReview.objects.create(version=self.addon.current_version)
        self.addon.current_version.update(due_date=due_date)
        upload_version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        # Check twice: on the returned instance and in the database, in case
        # a signal acting on the same version but different instance updated
        # it.
        self.assertCloseToNow(upload_version.due_date, now=due_date)
        upload_version.reload()
        self.assertCloseToNow(upload_version.due_date, now=due_date)
        assert upload_version.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            upload_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASONS.INHERITANCE
        )

        activity_log = (
            ActivityLog.objects.for_versions(upload_version)
            .filter(action=amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id)
            .first()
        )
        assert core.get_user() == user
        assert activity_log.user == get_task_user()

    def test_dont_inherit_due_date_far_in_future(self):
        standard_due_date = get_review_due_date()
        due_date = datetime.now() + timedelta(days=15)
        NeedsHumanReview.objects.create(version=self.addon.current_version)
        self.addon.current_version.update(due_date=due_date)
        upload_version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        # Check twice: on the returned instance and in the database, in case
        # a signal acting on the same version but different instance updated
        # it.
        # Because the due date from the previous version is so far in the
        # future we don't inherit from it and get the default one.
        self.assertCloseToNow(upload_version.due_date, now=standard_due_date)
        upload_version.reload()
        assert upload_version.needshumanreview_set.filter(is_active=True).count() == 1
        self.assertCloseToNow(upload_version.due_date, now=standard_due_date)

    def test_dont_inherit_due_date_if_one_already_exists(self):
        previous_version_due_date = datetime.now() + timedelta(days=30)
        existing_due_date = datetime.now() + timedelta(days=15)
        NeedsHumanReview.objects.create(version=self.addon.current_version)
        self.addon.current_version.update(due_date=previous_version_due_date)
        new_version = version_factory(addon=self.addon)
        NeedsHumanReview.objects.create(version=new_version)
        new_version.update(due_date=existing_due_date)
        self.assertCloseToNow(new_version.due_date, now=existing_due_date)
        new_version.reset_due_date()
        # Check twice: on the returned instance and in the database, in case
        # a signal acting on the same version but different instance updated
        # it.
        # Because the due date from the previous version is so far in the
        # future we don't inherit from it and keep the existing one.
        self.assertCloseToNow(new_version.due_date, now=existing_due_date)
        new_version.reload()
        self.assertCloseToNow(new_version.due_date, now=existing_due_date)

    def test_dont_inherit_needs_human_review_from_different_channel(self):
        old_version = self.addon.current_version
        self.make_addon_unlisted(self.addon)
        NeedsHumanReview.objects.create(version=old_version)
        assert old_version.due_date

        upload_version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        # Check twice: on the returned instance and in the database, in case
        # a signal acting on the same version but different instance updated
        # it.
        assert not upload_version.due_date
        upload_version.reload()
        assert not upload_version.due_date
        assert upload_version.needshumanreview_set.count() == 0

    def test_dont_inherit_due_date_or_nhr_for_some_specific_reasons(self):
        # Some NeedsHumanReview reasons don't pass their due date through
        # inheritance if they are the only reason a version had a due date.
        old_version = self.addon.current_version
        old_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        )
        assert old_version.due_date
        old_version.update(due_date=self.days_ago(1))
        new_version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        # The version doesn't gain a NHR for INHERITANCE
        assert new_version.needshumanreview_set.count() == 0
        # If it gains a NHR, it doesn't inherit the due date since the old
        # version only needs human review for one of the reasons that does not
        # trigger inheritance.
        new_version.needshumanreview_set.create(reason=NeedsHumanReview.REASONS.UNKNOWN)
        assert new_version.due_date
        assert new_version.due_date > old_version.due_date
        # Forcing re-generation doesn't change anything.
        assert new_version.generate_due_date() > old_version.due_date

        # The above remains true for CINDER_ESCALATION which is another reason
        # that doesn't trigger due date inheritance.
        old_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION
        )
        assert new_version.generate_due_date() > old_version.due_date

        # If we add another reason that *does* trigger inheritance to the old
        # version, suddenly we will inherit its due date.
        old_version.needshumanreview_set.create(reason=NeedsHumanReview.REASONS.UNKNOWN)
        assert new_version.generate_due_date() == old_version.due_date

    def test_set_version_to_customs_scanners_result(self):
        self.create_switch('enable-customs', active=True)
        scanners_result = ScannerResult.objects.create(
            upload=self.upload, scanner=CUSTOMS
        )
        assert scanners_result.version is None

        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        scanners_result.refresh_from_db()
        assert scanners_result.version == version

    def test_set_version_to_yara_scanners_result(self):
        self.create_switch('enable-yara', active=True)
        scanners_result = ScannerResult.objects.create(upload=self.upload, scanner=YARA)
        assert scanners_result.version is None

        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )

        scanners_result.refresh_from_db()
        assert scanners_result.version == version

    def test_auto_approval_not_disabled_if_not_restricted(self):
        self.upload.user.update(last_login_ip='10.0.0.42')
        # Set a submission time restriction: it shouldn't matter.
        IPNetworkUserRestriction.objects.create(network='10.0.0.0/24')
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        assert (
            not ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.DISABLE_AUTO_APPROVAL.id)
            .exists()
        )

    def test_auto_approval_disabled_if_restricted_by_email(self):
        EmailUserRestriction.objects.create(
            email_pattern=self.upload.user.email,
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert self.addon.auto_approval_disabled
        assert not self.addon.auto_approval_disabled_unlisted
        assert (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.DISABLE_AUTO_APPROVAL.id)
            .exists()
        )
        activity_log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.DISABLE_AUTO_APPROVAL.id)
            .get()
        )
        assert activity_log.details['channel'] == amo.CHANNEL_LISTED
        assert (
            activity_log.details['comments']
            == 'Listed auto-approval automatically disabled because of a restriction'
        )
        assert activity_log.user == get_task_user()

    def test_auto_approval_disabled_if_restricted_by_ip(self):
        self.upload.user.update(last_login_ip='10.0.0.42')
        IPNetworkUserRestriction.objects.create(
            network='10.0.0.0/24', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert self.addon.auto_approval_disabled
        assert not self.addon.auto_approval_disabled_unlisted
        assert (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.DISABLE_AUTO_APPROVAL.id)
            .exists()
        )
        activity_log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.DISABLE_AUTO_APPROVAL.id)
            .get()
        )
        assert activity_log.details['channel'] == amo.CHANNEL_LISTED
        assert (
            activity_log.details['comments']
            == 'Listed auto-approval automatically disabled because of a restriction'
        )
        assert activity_log.user == get_task_user()

    def test_auto_approval_disabled_for_unlisted_if_restricted_by_ip(self):
        self.upload.user.update(last_login_ip='10.0.0.42')
        IPNetworkUserRestriction.objects.create(
            network='10.0.0.0/24', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_disabled
        assert self.addon.auto_approval_disabled_unlisted
        assert (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.DISABLE_AUTO_APPROVAL.id)
            .exists()
        )
        activity_log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.DISABLE_AUTO_APPROVAL.id)
            .get()
        )
        assert activity_log.details['channel'] == amo.CHANNEL_UNLISTED
        assert (
            activity_log.details['comments']
            == 'Unlisted auto-approval automatically disabled because of a restriction'
        )
        assert activity_log.user == get_task_user()

    def test_dont_record_install_origins_when_waffle_switch_is_off(self):
        # Switch should be off by default.
        assert waffle.switch_is_active('record-install-origins') is False
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        parsed_data['install_origins'] = ['https://foo.com', 'https://bar.com']
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.installorigin_set.count() == 0

    @override_switch('record-install-origins', active=True)
    def test_record_install_origins(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        parsed_data['install_origins'] = ['https://foo.com', 'https://bar.com']
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.installorigin_set.count() == 2
        assert sorted(version.installorigin_set.values_list('origin', flat=True)) == [
            'https://bar.com',
            'https://foo.com',
        ]

    @override_switch('record-install-origins', active=True)
    def test_record_install_origins_base_domain(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        parsed_data['install_origins'] = [
            'https://foô.com',
            'https://foo.bar.co.uk',
            'https://foo.bar.栃木.jp',
        ]
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.installorigin_set.count() == 3
        assert sorted(
            version.installorigin_set.values_list('origin', 'base_domain')
        ) == [
            ('https://foo.bar.co.uk', 'bar.co.uk'),
            ('https://foo.bar.栃木.jp', 'bar.xn--4pvxs.jp'),
            ('https://foô.com', 'xn--fo-9ja.com'),
        ]

    @override_switch('record-install-origins', active=True)
    def test_record_install_origins_error(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        parsed_data['install_origins'] = None  # Invalid
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.CHANNEL_UNLISTED,
                selected_apps=[self.selected_app],
                parsed_data=parsed_data,
            )

    @mock.patch('olympia.devhub.tasks.send_initial_submission_acknowledgement_email')
    def test_send_initial_submission_acknowledgement_email_first_version(
        self, send_initial_submission_acknowledgement_email_mock
    ):
        self.addon.current_version.delete(hard=True)
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.pk
        assert send_initial_submission_acknowledgement_email_mock.delay.call_count == 1
        assert send_initial_submission_acknowledgement_email_mock.delay.call_args == [
            (3615, amo.CHANNEL_LISTED, self.upload.user.email)
        ]

    @mock.patch('olympia.devhub.tasks.send_initial_submission_acknowledgement_email')
    def test_send_initial_submission_acknowledgement_email_first_version_unlisted(
        self, send_initial_submission_acknowledgement_email_mock
    ):
        self.addon.current_version.delete(hard=True)
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.pk
        assert send_initial_submission_acknowledgement_email_mock.delay.call_count == 1
        assert send_initial_submission_acknowledgement_email_mock.delay.call_args == [
            (3615, amo.CHANNEL_UNLISTED, self.upload.user.email)
        ]

    @mock.patch('olympia.devhub.tasks.send_initial_submission_acknowledgement_email')
    def test_dont_send_initial_submission_acknowledgement_email_second_version(
        self, send_initial_submission_acknowledgement_email_mock
    ):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.pk
        assert send_initial_submission_acknowledgement_email_mock.delay.call_count == 0

    @mock.patch('olympia.devhub.tasks.send_initial_submission_acknowledgement_email')
    def test_dont_send_initial_submission_acknowledgement_email_first_was_soft_deleted(
        self, send_initial_submission_acknowledgement_email_mock
    ):
        self.addon.current_version.delete()
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.pk
        assert send_initial_submission_acknowledgement_email_mock.delay.call_count == 0

    def test_version_provenance(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
            client_info='Something/42.0',
        )
        assert version.pk
        assert VersionProvenance.objects.filter(version=version).exists()
        provenance = VersionProvenance.objects.get(version=version)
        assert provenance.client_info == 'Something/42.0'
        assert provenance.source == self.upload.source


class TestExtensionVersionFromUploadUnlistedDelay(TestVersionFromUpload):
    filename = 'webextension.xpi'

    def test_no_config(self):
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        assert not self.addon.auto_approval_delayed_until_unlisted

    def test_config_no_int(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', 'blah')
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        assert not self.addon.auto_approval_delayed_until_unlisted

    def test_config_zero(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '0')
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        assert not self.addon.auto_approval_delayed_until_unlisted

    def test_set_in_future_but_creation_date_is_too_far_in_the_past(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '3600')
        self.addon.update(created=datetime.now() - timedelta(seconds=3601))
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        assert not self.addon.auto_approval_delayed_until_unlisted

    def test_set_in_future_but_existing_delay_higher(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '3600')
        self.addon.update(created=datetime.now() - timedelta(seconds=600))
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_delayed_until_unlisted=datetime.now()
            + timedelta(seconds=86400),
        )
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        self.assertCloseToNow(
            self.addon.auto_approval_delayed_until_unlisted,
            now=datetime.now() + timedelta(seconds=86400),
        )

    def test_set_in_future_but_version_is_listed(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '3600')
        self.addon.update(created=datetime.now() - timedelta(seconds=600))
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        assert not self.addon.auto_approval_delayed_until_unlisted

    def test_set_in_future_but_addon_is_a_theme(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '3600')
        self.addon.update(
            type=amo.ADDON_STATICTHEME, created=datetime.now() - timedelta(seconds=600)
        )
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        assert not self.addon.auto_approval_delayed_until_unlisted

    def test_set_in_future_but_addon_is_a_langpack(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '3600')
        self.addon.update(
            type=amo.ADDON_LPAPP, created=datetime.now() - timedelta(seconds=600)
        )
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        assert not self.addon.auto_approval_delayed_until_unlisted

    def test_set_in_future_overwrite_existing_lower_delay(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '3600')
        self.addon.update(created=datetime.now() - timedelta(seconds=600))
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_delayed_until_unlisted=datetime.now()
        )
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        self.assertCloseToNow(
            self.addon.auto_approval_delayed_until_unlisted,
            now=self.addon.created + timedelta(seconds=3600),
        )

    def test_second_unlisted_version(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '3600')
        self.addon.update(created=datetime.now() - timedelta(seconds=600))
        self.make_addon_unlisted(self.addon)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        assert not self.addon.auto_approval_delayed_until_unlisted

    def test_second_unlisted_version_deleted(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '3600')
        self.addon.update(created=datetime.now() - timedelta(seconds=600))
        version = self.addon.current_version
        self.make_addon_unlisted(self.addon)
        version.delete()
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        assert not self.addon.auto_approval_delayed_until_unlisted

    def test_set_in_future(self):
        set_config('INITIAL_DELAY_FOR_UNLISTED', '3600')
        self.addon.update(created=datetime.now() - timedelta(seconds=600))
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_delayed_until
        self.assertCloseToNow(
            self.addon.auto_approval_delayed_until_unlisted,
            now=self.addon.created + timedelta(seconds=3600),
        )


class TestDisableOldFilesInFromUpload(TestVersionFromUpload):
    filename = 'webextension.xpi'

    def setUp(self):
        super().setUp()
        self.old_version = self.addon.current_version

    def test_disable_old_files_waiting_review(self):
        self.old_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert self.old_version.file.reload().status == amo.STATUS_DISABLED
        assert version.file.status == amo.STATUS_AWAITING_REVIEW

    def test_disable_old_files_waiting_review_not_for_unlisted_channel(self):
        self.old_version.update(channel=amo.CHANNEL_UNLISTED)
        self.old_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert self.old_version.file.reload().status == amo.STATUS_AWAITING_REVIEW
        assert version.file.status == amo.STATUS_AWAITING_REVIEW

    def test_disable_old_files_waiting_review_not_for_langpacks(self):
        self.old_version.addon.update(type=amo.ADDON_LPAPP)
        self.old_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert self.old_version.file.reload().status == amo.STATUS_AWAITING_REVIEW
        assert version.file.status == amo.STATUS_AWAITING_REVIEW


class TestPermissionsFromUpload(TestVersionFromUpload):
    filename = 'webextension_all_perms.xpi'

    def setUp(self):
        super().setUp()
        self.addon.update(guid='allPermissions1@mozilla.com')
        self.current = self.addon.current_version

    def test_permissions_includes_devtools(self):
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_UNLISTED,
            selected_apps=[amo.FIREFOX.id],
            parsed_data=parsed_data,
        )
        file = version.file

        permissions = file.permissions

        assert 'devtools' in permissions


class TestStaticThemeFromUpload(UploadMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
        }
        for version in versions:
            AppVersion.objects.get_or_create(
                application=amo.FIREFOX.id, version=version
            )
            AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version=version
            )

    def setUp(self):
        path = 'src/olympia/devhub/tests/addons/static_theme.zip'
        self.user = user_factory()
        self.upload = self.get_upload(
            abspath=os.path.join(settings.ROOT, path), user=self.user
        )

    @mock.patch('olympia.versions.models.generate_static_theme_preview')
    def test_new_version_while_nominated(self, generate_static_theme_preview_mock):
        self.addon = addon_factory(
            type=amo.ADDON_STATICTHEME,
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.user)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[],
            parsed_data=parsed_data,
        )
        assert generate_static_theme_preview_mock.call_count == 1

    @mock.patch('olympia.versions.models.generate_static_theme_preview')
    def test_new_version_while_public(self, generate_static_theme_preview_mock):
        self.addon = addon_factory(type=amo.ADDON_STATICTHEME)
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.user)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[],
            parsed_data=parsed_data,
        )
        assert generate_static_theme_preview_mock.call_count == 1

    @mock.patch('olympia.versions.models.generate_static_theme_preview')
    def test_new_version_with_additional_backgrounds(
        self, generate_static_theme_preview_mock
    ):
        self.addon = addon_factory(type=amo.ADDON_STATICTHEME)
        path = 'src/olympia/devhub/tests/addons/static_theme_tiled.zip'
        self.upload = self.get_upload(
            abspath=os.path.join(settings.ROOT, path), user=self.user
        )
        parsed_data = parse_addon(self.upload, addon=self.addon, user=self.user)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[],
            parsed_data=parsed_data,
        )
        assert generate_static_theme_preview_mock.call_count == 1


class TestApplicationsVersions(TestCase):
    def setUp(self):
        super().setUp()
        self.version_kw = {'min_app_version': '5.0', 'max_app_version': '6.*'}

    def test_repr_when_compatible(self):
        addon = addon_factory(version_kw=self.version_kw)
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox 5.0 and later'

    def test_repr_when_strict(self):
        addon = addon_factory(
            version_kw=self.version_kw, file_kw={'strict_compatibility': True}
        )
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox 5.0 - 6.*'

    def test_repr_when_unicode(self):
        addon = addon_factory(
            version_kw={'min_app_version': 'ك', 'max_app_version': 'ك'},
            file_kw={'strict_compatibility': True},
        )
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox ك - ك'


class TestApplicationsVersionsVersionRangeContainsForbiddenCompatibility(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_default_webext_appversion()
        cls.fennec_appversion = AppVersion.objects.get(
            application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        )
        cls.fenix_appversion = AppVersion.objects.get(
            application=amo.ANDROID.id,
            version=amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID,
        )
        cls.fenix_ga_appversion = AppVersion.objects.get(
            application=amo.ANDROID.id,
            version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
        )
        cls.fenix_min_version = AppVersion.objects.get(
            application=amo.ANDROID.id, version=amo.MIN_VERSION_FENIX
        )
        cls.star_android_appversion = AppVersion.objects.get(
            application=amo.ANDROID.id, version='*'
        )
        # Extra not created by create_default_webext_appversion():
        cls.fennec_appversion_star = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='68.*'
        )[0]
        cls.fenix_appversion_star = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='117.*'
        )[0]

    def assert_min_and_max_unchanged_on_save(self, avs):
        old_min = avs.min
        old_max = avs.max
        avs.save()
        assert avs.min == old_min
        assert avs.max == old_max

    def assert_min_and_max_are_set_to_fenix_ga_on_save(self, avs):
        avs.save()
        assert avs.min == self.fenix_ga_appversion
        assert avs.max == self.star_android_appversion

    def test_not_android(self):
        addon = addon_factory()
        avs = ApplicationsVersions.objects.get(
            application=amo.FIREFOX.id, version=addon.current_version
        )
        assert not avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_unchanged_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_not_extension(self):
        addon = addon_factory(type=amo.ADDON_STATICTHEME)
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fennec_appversion,
            max=self.star_android_appversion,
        )
        # We don't care about allowing that non-extensions, they are filtered
        # elsewhere.
        assert not avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_unchanged_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_recommended_for_android(self):
        addon = addon_factory(promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert amo.ANDROID in addon.approved_applications
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fennec_appversion,
            max=self.star_android_appversion,
        )
        assert not avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_unchanged_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_line_for_android(self):
        addon = addon_factory(promoted_id=PROMOTED_GROUP_CHOICES.LINE)
        assert amo.ANDROID in addon.approved_applications
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fennec_appversion,
            max=self.star_android_appversion,
        )
        assert not avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_unchanged_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_other_promotion_for_android(self):
        addon = addon_factory(promoted_id=PROMOTED_GROUP_CHOICES.NOTABLE)
        assert amo.ANDROID in addon.approved_applications
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fennec_appversion,
            max=self.star_android_appversion,
        )
        # Not recommended/line and is using a forbidden range.
        assert avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_are_set_to_fenix_ga_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_recommended_or_line_for_desktop(self):
        addon = addon_factory(promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED)
        android_approval = (
            addon.current_version.promoted_versions.all()
            .filter(application_id=amo.ANDROID.id)
            .get()
        )
        android_approval.delete()
        assert amo.ANDROID not in addon.approved_applications
        assert amo.FIREFOX in addon.approved_applications
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fennec_appversion,
            max=self.star_android_appversion,
        )
        # Not recommended/line and is using a forbidden range.
        assert avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_are_set_to_fenix_ga_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_below_forbidden_range(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fennec_appversion,
            max=self.fennec_appversion_star,
        )
        # Entirely below range is allowed.
        assert not avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_unchanged_on_save(avs)
        # This triggers the file to have strict compatibility enabled though
        # (so that this extension is only seen by Fennec, not Fenix).
        assert avs.version.file.reload().strict_compatibility
        # Deleting Android compatibility resets it though.
        avs.delete()
        assert not avs.version.file.reload().strict_compatibility

    def test_above_forbidden_range(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fenix_ga_appversion,
            max=self.star_android_appversion,
        )
        # Entirely above range is allowed.
        assert not avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_unchanged_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_min_in_limited_range(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fenix_appversion,
            max=self.star_android_appversion,
        )
        assert avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_are_set_to_fenix_ga_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_max_in_limited_range(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fennec_appversion,
            max=self.fenix_appversion,
        )
        assert avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_are_set_to_fenix_ga_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_both_min_and_max_in_limited_range(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fenix_appversion,
            max=self.fenix_appversion_star,
        )
        assert avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_are_set_to_fenix_ga_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_min_below_and_max_above_limited_range(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fennec_appversion,
            max=self.fenix_ga_appversion,
        )
        assert avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_are_set_to_fenix_ga_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_both_min_and_max_above_limited_end_but_equal(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fenix_ga_appversion,
            max=self.fenix_ga_appversion,
        )
        assert not avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_unchanged_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_both_min_and_max_above_limited_start(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fenix_min_version,
            max=self.fenix_appversion_star,
        )
        assert avs.version_range_contains_forbidden_compatibility()
        self.assert_min_and_max_are_set_to_fenix_ga_on_save(avs)
        assert not avs.version.file.reload().strict_compatibility

    def test_get_default_minimum_appversion(self):
        assert ApplicationsVersions(
            application=amo.FIREFOX.id
        ).get_default_minimum_appversion() == AppVersion.objects.get(
            application=amo.FIREFOX.id,
            version=amo.DEFAULT_WEBEXT_MIN_VERSIONS[amo.FIREFOX],
        )

        assert ApplicationsVersions(
            application=amo.ANDROID.id
        ).get_default_minimum_appversion() == AppVersion.objects.get(
            application=amo.ANDROID.id,
            version=amo.DEFAULT_WEBEXT_MIN_VERSIONS[amo.ANDROID],
        )

    def get_default_maximum_appversion(self):
        self.star_firefox_appversion = AppVersion.objects.filter(
            application=amo.FIREFOX.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
        )
        assert (
            ApplicationsVersions(
                application=amo.FIREFOX.id
            ).get_default_maximum_appversion()
            == self.star_firefox_appversion
        )

        assert (
            ApplicationsVersions(
                application=amo.ANDROID.id
            ).get_default_maximum_appversion()
            == self.star_android_appversion
        )

    def test_min_not_set_fallback_to_default(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            max=self.fenix_appversion_star,
        )
        assert avs.version_range_contains_forbidden_compatibility()

    def test_max_not_set_fallback_to_default(self):
        addon = addon_factory()
        avs = ApplicationsVersions(
            application=amo.ANDROID.id,
            version=addon.current_version,
            min=self.fennec_appversion,
        )
        assert avs.version_range_contains_forbidden_compatibility()


class TestVersionPreview(BasePreviewMixin, TestCase):
    def get_object(self):
        version_preview = VersionPreview.objects.create(
            version=addon_factory().current_version
        )
        return version_preview


class TestInstallOrigin(TestCase):
    def test_save_extract_base_domain(self):
        version = addon_factory().current_version
        install_origin = InstallOrigin.objects.create(
            version=version, origin='https://mozilla.github.io'
        )
        assert install_origin.base_domain == 'mozilla.github.io'

        install_origin.origin = 'https://foo.example.com'
        install_origin.save()
        assert install_origin.base_domain == 'example.com'
        install_origin.reload()
        assert install_origin.base_domain == 'example.com'

    def test_punycode(self):
        assert InstallOrigin.punycode('examplé.com') == 'xn--exampl-gva.com'
        assert InstallOrigin.punycode('xn--exampl-gva.com') == 'xn--exampl-gva.com'
        assert InstallOrigin.punycode('example.com') == 'example.com'


class TestDeniedInstallOrigin(TestCase):
    def test_save_always_punycode(self):
        denied_install_origin = DeniedInstallOrigin.objects.create(
            hostname_pattern='eXamplÉ.com'
        )
        assert denied_install_origin.hostname_pattern == 'xn--exampl-gva.com'

        denied_install_origin.hostname_pattern = '*.examplé.com'
        denied_install_origin.save()
        assert denied_install_origin.hostname_pattern == '*.xn--exampl-gva.com'
        denied_install_origin.reload()
        assert denied_install_origin.hostname_pattern == '*.xn--exampl-gva.com'

    def test_find_denied_origins_empty_list(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.example.com')
        DeniedInstallOrigin.objects.create(
            hostname_pattern='bar.com', include_subdomains=True
        )
        assert DeniedInstallOrigin.find_denied_origins([]) == set()

    def test_find_denied_origins_nothing_denied(self):
        assert DeniedInstallOrigin.find_denied_origins(['https://example.com']) == set()
        assert (
            DeniedInstallOrigin.find_denied_origins(
                ['https://example.com', 'https://foo.bar.com']
            )
            == set()
        )
        assert (
            DeniedInstallOrigin.find_denied_origins(
                ['https://example.com', 'https://foo.baré.com']
            )
            == set()
        )

    def test_find_denied_origins_idn(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='examplé.com')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://foo.com', 'https://examplé.com']
        ) == {'https://examplé.com'}

    def test_find_denied_origins_with_port(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='example.com')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://foo.com', 'https://example.com:8888']
        ) == {'https://example.com:8888'}

    def test_find_denied_origins_multiple_matches(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='example.com')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'http://example.com', 'https://foo.com']
        ) == {
            'https://example.com',
            'http://example.com',
        }

    def test_find_denied_origins_glob(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='example.*')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'https://example.co.uk', 'https://foo.com']
        ) == {
            'https://example.com',
            'https://example.co.uk',
        }

    def test_find_denied_origins_multiple_denied_origins_match(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='example.com')
        DeniedInstallOrigin.objects.create(hostname_pattern='example.*')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'http://example.com', 'https://foo.com']
        ) == {
            'https://example.com',
            'http://example.com',
        }

    def test_find_denied_origins_include_subdomains(self):
        DeniedInstallOrigin.objects.create(
            hostname_pattern='example.com', include_subdomains=True
        )
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'https://foo.example.com', 'https://foo.com']
        ) == {
            'https://example.com',
            'https://foo.example.com',
        }

    def test_find_denied_origins_include_subdomains_complex_match(self):
        DeniedInstallOrigin.objects.create(
            hostname_pattern='example.*', include_subdomains=True
        )
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'https://foo.example.com', 'https://foo.com']
        ) == {
            'https://example.com',
            'https://foo.example.com',
        }

    def test_find_denied_origins_input_not_an_origin(self):
        # The linter would raise an error, so we only need to ensure nothing
        # blows up on addons-server side.
        DeniedInstallOrigin.objects.create(hostname_pattern='example.com')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'rofl', 'https://foo.com']
        ) == {'https://example.com'}


@mock.patch('olympia.versions.models.statsd.incr')
class TestVersionProvenance(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        self.version = self.addon.current_version

    def test_from_version_no_client_info(self, incr_mock):
        provenance = VersionProvenance.from_version(
            version=self.version, source=amo.UPLOAD_SOURCE_GENERATED, client_info=None
        )
        assert VersionProvenance.objects.get() == provenance
        assert provenance.version == self.version
        assert provenance.source == amo.UPLOAD_SOURCE_GENERATED
        assert provenance.client_info is None
        assert incr_mock.call_count == 0

    def test_from_version_client_info_no_webext_version(self, incr_mock):
        provenance = VersionProvenance.from_version(
            version=self.version,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            client_info='Mozilla/5.0 (Whatever; rv:126.0) Gecko/20100101 Firefox/126.0',
        )
        assert VersionProvenance.objects.get() == provenance
        assert provenance.version == self.version
        assert provenance.source == amo.UPLOAD_SOURCE_DEVHUB
        assert (
            provenance.client_info
            == 'Mozilla/5.0 (Whatever; rv:126.0) Gecko/20100101 Firefox/126.0'
        )
        assert incr_mock.call_count == 0

    def test_from_version_client_info_very_long(self, incr_mock):
        provenance = VersionProvenance.from_version(
            version=self.version,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            client_info='abc' * 1000,
        )
        assert VersionProvenance.objects.get() == provenance
        assert provenance.version == self.version
        assert provenance.source == amo.UPLOAD_SOURCE_ADDON_API
        assert (
            provenance.client_info == 'abc' * 85  # 255 max length.
        )
        assert incr_mock.call_count == 0

    def test_from_version_with_webext_version(self, incr_mock):
        provenance = VersionProvenance.from_version(
            version=self.version,
            source=amo.UPLOAD_SOURCE_SIGNING_API,
            client_info='web-ext/42.0',
        )
        assert VersionProvenance.objects.get() == provenance
        assert provenance.version == self.version
        assert provenance.source == amo.UPLOAD_SOURCE_SIGNING_API
        assert provenance.client_info == 'web-ext/42.0'
        assert incr_mock.call_count == 1
        assert incr_mock.call_args[0][0] == 'signing.submission.webext_version.42_0'

    def test_from_version_with_webext_version_old_signing_api(self, incr_mock):
        provenance = VersionProvenance.from_version(
            version=self.version,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            client_info='web-ext/8.0.2',
        )
        assert VersionProvenance.objects.get() == provenance
        assert provenance.version == self.version
        assert provenance.source == amo.UPLOAD_SOURCE_ADDON_API
        assert provenance.client_info == 'web-ext/8.0.2'
        assert incr_mock.call_count == 1
        assert incr_mock.call_args[0][0] == 'addons.submission.webext_version.8_0_2'

    def test_from_version_with_webext_version_other(self, incr_mock):
        provenance = VersionProvenance.from_version(
            version=self.version,
            source=amo.UPLOAD_SOURCE_GENERATED,
            client_info='web-ext/1',
        )
        assert VersionProvenance.objects.get() == provenance
        assert provenance.version == self.version
        assert provenance.source == amo.UPLOAD_SOURCE_GENERATED
        assert provenance.client_info == 'web-ext/1'
        assert incr_mock.call_count == 1
        assert incr_mock.call_args[0][0] == 'other.webext_version.1'
