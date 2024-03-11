from datetime import datetime, timedelta
from unittest.mock import call, patch

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import translation

import pytest
import responses

from olympia import amo
from olympia.abuse.models import AbuseReport, CinderJob
from olympia.activity.models import ActivityLog, ActivityLogToken, ReviewActionReasonLog
from olympia.addons.models import Addon, AddonApprovalsCounter, AddonReviewerFlags
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
    version_review_flags_factory,
)
from olympia.amo.utils import send_mail
from olympia.blocklist.models import Block, BlocklistSubmission
from olympia.constants.promoted import (
    LINE,
    NOTABLE,
    RECOMMENDED,
    SPONSORED,
    SPOTLIGHT,
    STRATEGIC,
)
from olympia.files.models import File
from olympia.lib.crypto.signing import SigningError
from olympia.lib.crypto.tests.test_signing import (
    _get_recommendation_data,
    _get_signature_details,
)
from olympia.promoted.models import PromotedAddon, PromotedApproval
from olympia.reviewers.models import (
    AutoApprovalSummary,
    NeedsHumanReview,
    ReviewActionReason,
)
from olympia.reviewers.utils import (
    ReviewAddon,
    ReviewFiles,
    ReviewHelper,
    ReviewUnlisted,
)
from olympia.users.models import UserProfile
from olympia.users.utils import get_task_user
from olympia.versions.models import VersionReviewerFlags


pytestmark = pytest.mark.django_db


REVIEW_FILES_STATUSES = (amo.STATUS_APPROVED, amo.STATUS_DISABLED)


yesterday = datetime.today() - timedelta(days=1)


class TestReviewHelperBase(TestCase):
    __test__ = False

    fixtures = ['base/addon_3615', 'base/users']
    preamble = 'Mozilla Add-ons: Delicious Bookmarks 2.1.072'

    def setUp(self):
        super().setUp()

        self.user = UserProfile.objects.get(pk=10482)
        self.addon = Addon.objects.get(pk=3615)
        self.review_version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.review_version.file

        self.create_paths()

    def remove_paths(self):
        if self.file.file and not storage.exists(self.file.file.path):
            storage.delete(self.file.file.path)

    def create_paths(self):
        if not storage.exists(self.file.file.path):
            with storage.open(self.file.file.path, 'w') as f:
                f.write('test data\n')
        self.addCleanup(self.remove_paths)

    def setup_data(
        self,
        status,
        file_status=amo.STATUS_AWAITING_REVIEW,
        channel=amo.CHANNEL_LISTED,
        content_review=False,
        type=amo.ADDON_EXTENSION,
        human_review=True,
    ):
        mail.outbox = []
        self.file.update(status=file_status)
        if channel == amo.CHANNEL_UNLISTED:
            self.make_addon_unlisted(self.addon)
            if self.review_version:
                self.review_version.reload()
            self.file.reload()
        self.addon.update(status=status, type=type)
        self.helper = self.get_helper(
            content_review=content_review, human_review=human_review
        )
        ActivityLog.objects.for_addons(self.helper.addon).delete()
        data = self.get_data().copy()
        self.helper.set_data(data)

    def get_data(self):
        return {
            'comments': 'foo',
            'action': 'public',
            'operating_systems': 'osx',
            'applications': 'Firefox',
        }

    def get_helper(self, content_review=False, human_review=True):
        return ReviewHelper(
            addon=self.addon,
            version=self.review_version,
            user=self.user,
            human_review=human_review,
            content_review=content_review,
        )

    def setup_type(self, status):
        self.addon.update(status=status)
        return self.get_helper().handler.review_type

    def check_log_count(self, id, user=None):
        user = user or self.user
        return (
            ActivityLog.objects.for_addons(self.helper.addon)
            .filter(action=id, user=user)
            .count()
        )


# Those tests can call signing when making things public. We want to test that
# it works correctly, so we set ENABLE_ADDON_SIGNING to True and mock the
# actual signing call below in setUp().
@override_settings(ENABLE_ADDON_SIGNING=True)
class TestReviewHelper(TestReviewHelperBase):
    __test__ = True

    def setUp(self):
        super().setUp()
        patcher = patch('olympia.reviewers.utils.sign_file')
        self.addCleanup(patcher.stop)
        self.sign_file_mock = patcher.start()

    def test_type_nominated(self):
        assert self.setup_type(amo.STATUS_NOMINATED) == 'extension_nominated'

    def test_type_pending(self):
        assert self.setup_type(amo.STATUS_NULL) == 'extension_pending'
        assert self.setup_type(amo.STATUS_APPROVED) == 'extension_pending'
        assert self.setup_type(amo.STATUS_DISABLED) == 'extension_pending'

    def test_no_version(self):
        helper = ReviewHelper(addon=self.addon, version=None, user=self.user)
        assert helper.handler.review_type == 'extension_pending'

    def test_review_files(self):
        version_factory(
            addon=self.addon,
            created=self.review_version.created - timedelta(days=1),
            file_kw={'status': amo.STATUS_APPROVED},
        )
        for status in REVIEW_FILES_STATUSES:
            self.setup_data(status=status)
            assert self.helper.handler.__class__ == ReviewFiles

    def test_review_addon(self):
        self.setup_data(status=amo.STATUS_NOMINATED)
        assert self.helper.handler.__class__ == ReviewAddon

    def test_process_action_none(self):
        self.helper.set_data({'action': 'foo'})
        with self.assertRaises(NotImplementedError):
            self.helper.process()

    def test_process_action_good(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.helper = self.get_helper()
        self.helper.set_data({'action': 'reply', 'comments': 'foo'})
        self.helper.process()
        assert len(mail.outbox) == 1

    def test_action_details(self):
        for status in Addon.STATUS_CHOICES:
            self.addon.update(status=status)
            helper = self.get_helper()
            actions = helper.actions
            for k, v in actions.items():
                assert str(v['details']), 'Missing details for: %s' % k

    def get_review_actions(
        self, addon_status, file_status, content_review=False, human_review=True
    ):
        self.file.update(status=file_status)
        self.addon.update(status=addon_status)
        return self.get_helper(
            human_review=human_review, content_review=content_review
        ).actions

    def test_actions_full_nominated(self):
        self.grant_permission(self.user, 'Addons:Review')
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_NOMINATED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

    def test_actions_full_update(self):
        self.grant_permission(self.user, 'Addons:Review')
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

    def test_actions_full_nonpending(self):
        self.grant_permission(self.user, 'Addons:Review')
        expected = [
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        f_statuses = [amo.STATUS_APPROVED, amo.STATUS_DISABLED]
        for file_status in f_statuses:
            assert (
                list(
                    self.get_review_actions(
                        addon_status=amo.STATUS_APPROVED, file_status=file_status
                    ).keys()
                )
                == expected
            )

    def test_actions_public_post_review(self):
        self.grant_permission(self.user, 'Addons:Review')
        expected = [
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
                ).keys()
            )
            == expected
        )

        # Now make current version auto-approved...
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        expected = [
            'confirm_auto_approved',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
                ).keys()
            )
            == expected
        )

        # Now make add a recommended promoted addon. The user should lose all
        # approve/reject actions (they are no longer considered an
        # "appropriate" reviewer for that add-on).
        self.make_addon_promoted(self.addon, RECOMMENDED)
        expected = ['reply', 'comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
                ).keys()
            )
            == expected
        )

    def test_actions_content_review(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        expected = [
            'approve_content',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_APPROVED,
                    content_review=True,
                ).keys()
            )
            == expected
        )

    def test_actions_content_review_non_approved_addon(self):
        # Content reviewers can also see add-ons before they are approved for
        # the first time.
        self.grant_permission(self.user, 'Addons:ContentReview')
        expected = [
            'approve_content',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_NOMINATED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                    content_review=True,
                ).keys()
            )
            == expected
        )

    def test_actions_public_static_theme(self):
        # Having Addons:Review and dealing with a public add-on would
        # normally be enough to give you access to reject multiple versions
        # action, but it should not be available if you're not theme reviewer.
        self.grant_permission(self.user, 'Addons:Review')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        expected = []
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

        # Themes reviewers get access to everything, including reject multiple.
        self.user.groupuser_set.all().delete()
        self.grant_permission(self.user, 'Addons:ThemeReview')
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_admin_review',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

    def test_actions_no_version(self):
        """Addons with no versions in that channel have no version set."""
        expected = []
        self.review_version = None
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
                ).keys()
            )
            == expected
        )

    def test_actions_recommended(self):
        # Having Addons:Review is not enough to review
        # recommended extensions.
        self.make_addon_promoted(self.addon, RECOMMENDED)
        self.grant_permission(self.user, 'Addons:Review')
        expected = ['reply', 'comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
                ).keys()
            )
            == expected
        )

        expected = ['reply', 'comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_NOMINATED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

        # Having Addons:RecommendedReview allows you to do it.
        self.grant_permission(self.user, 'Addons:RecommendedReview')
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

    def test_actions_recommended_content_review(self):
        # Having Addons:ContentReview is not enough to content review
        # recommended extensions.
        self.make_addon_promoted(self.addon, RECOMMENDED)
        self.grant_permission(self.user, 'Addons:ContentReview')
        expected = ['reply', 'comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_APPROVED,
                    content_review=True,
                ).keys()
            )
            == expected
        )

        # Having Addons:RecommendedReview allows you to do it (though you'd
        # be better off just do a full review).
        self.grant_permission(self.user, 'Addons:RecommendedReview')
        expected = [
            'approve_content',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_APPROVED,
                    content_review=True,
                ).keys()
            )
            == expected
        )

    def test_actions_promoted_admin_review_needs_admin_permission(self):
        # Having Addons:Review or Addons:RecommendedReview
        # is not enough to review promoted addons that are in a group that is
        # admin_review=True.
        self.make_addon_promoted(self.addon, LINE)
        self.grant_permission(self.user, 'Addons:Review')
        expected = ['comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
                ).keys()
            )
            == expected
        )
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

        # only for groups that are admin_review though
        self.make_addon_promoted(self.addon, SPONSORED, approve_version=True)
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

        # change it back to an admin_review group
        self.make_addon_promoted(self.addon, SPOTLIGHT)

        self.grant_permission(self.user, 'Addons:RecommendedReview')
        expected = ['comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

        # you need admin review permission
        self.grant_permission(self.user, 'Reviews:Admin')
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'disable_addon',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

    def test_actions_unlisted(self):
        # Just regular review permissions don't let you do much on an unlisted
        # review page.
        self.review_version.update(channel=amo.CHANNEL_UNLISTED)
        self.grant_permission(self.user, 'Addons:Review')
        expected = ['reply', 'comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_NULL, file_status=amo.STATUS_AWAITING_REVIEW
                ).keys()
            )
            == expected
        )

        # Once you have ReviewUnlisted more actions are available.
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        expected = [
            'public',
            'approve_multiple_versions',
            'reject_multiple_versions',
            'block_multiple_versions',
            'confirm_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_NULL, file_status=amo.STATUS_AWAITING_REVIEW
                ).keys()
            )
            == expected
        )

        # unlisted shouldn't be affected by promoted group status either
        self.make_addon_promoted(self.addon, LINE)
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_NULL, file_status=amo.STATUS_AWAITING_REVIEW
                ).keys()
            )
            == expected
        )

        # with admin permission you should be able to unreject and disable too
        self.grant_permission(self.user, 'Reviews:Admin')
        expected = [
            'public',
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
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_NULL, file_status=amo.STATUS_AWAITING_REVIEW
                ).keys()
            )
            == expected
        )

    def test_actions_version_blocked(self):
        self.grant_permission(self.user, 'Addons:Review')
        # default case
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

        # But when the add-on is blocked 'public' shouldn't be available
        block_factory(addon=self.addon, updated_by=self.user)
        self.review_version.refresh_from_db()
        assert self.review_version.is_blocked
        expected = [
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

        # it's okay if a different version of the add-on is blocked though
        self.review_version = version_factory(addon=self.review_version.addon)
        self.file = self.review_version.file
        assert not self.review_version.is_blocked
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

    def test_actions_pending_rejection(self):
        # An addon having its latest version pending rejection won't be
        # reviewable by regular reviewers...
        self.grant_permission(self.user, 'Addons:Review')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        version_review_flags_factory(
            version=self.review_version, pending_rejection=datetime.now()
        )
        expected = ['reply', 'comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
                ).keys()
            )
            == expected
        )

        # ... unless there is a more recent version posted.
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        self.review_version = version_factory(addon=self.addon)
        self.file = self.review_version.file

        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

    def test_actions_pending_rejection_admin(self):
        # Admins can still do everything when there is a version pending
        # rejection.
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        version_review_flags_factory(
            version=self.review_version, pending_rejection=datetime.now()
        )
        expected = [
            'confirm_auto_approved',
            'reject_multiple_versions',
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'disable_addon',
            'comment',
        ]
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
                ).keys()
            )
            == expected
        )

        # a more recent version posted does not change anything for admins.
        # confirm_auto_approved is still available since that version is still
        # the current_version, hasn't been rejected yet.
        # they have public/reject actions too, since the new version is
        # awaiting review.
        expected = [
            'public',
            'reject',
            'confirm_auto_approved',
            'reject_multiple_versions',
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'disable_addon',
            'comment',
        ]
        self.review_version = version_factory(addon=self.addon)
        self.file = self.review_version.file
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

    def test_actions_disabled_addon(self):
        self.grant_permission(self.user, 'Addons:Review')
        expected = ['reply', 'comment']
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_DISABLED,
                # This state shouldn't happen in theory (disabling the add-on
                # should disable the files and prevent new versions from being
                # submitted), but we want to make sure if we do end up in that
                # situation the version is not approvable.
                file_status=amo.STATUS_AWAITING_REVIEW,
            ).keys()
        )
        assert expected == actions

        self.grant_permission(self.user, 'Reviews:Admin')
        expected = [
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'reply',
            'enable_addon',
            'comment',
        ]
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_DISABLED, file_status=amo.STATUS_AWAITING_REVIEW
            ).keys()
        )
        assert expected == actions

    def test_actions_rejected_version(self):
        self.grant_permission(self.user, 'Addons:Review')
        expected = ['set_needs_human_review_multiple_versions', 'reply', 'comment']

        self.file.update(status=amo.STATUS_DISABLED)
        self.file.version.update(human_review_date=datetime.now())
        self.addon.update(status=amo.STATUS_NULL)
        actions = list(self.get_helper().actions.keys())
        assert expected == actions

        self.grant_permission(self.user, 'Reviews:Admin')
        expected = [
            'unreject_latest_version',
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'disable_addon',
            'comment',
        ]
        actions = list(self.get_helper().actions.keys())
        assert expected == actions

    def test_actions_non_human_reviewer(self):
        # Note that we aren't granting permissions to our user.
        assert not self.user.groups.all()
        expected = [
            'public',
            'reject_multiple_versions',
        ]
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_APPROVED,
                file_status=amo.STATUS_AWAITING_REVIEW,
                human_review=False,
            ).keys()
        )
        assert expected == actions

    def test_actions_deleted_addon(self):
        self.grant_permission(self.user, 'Addons:Review')
        expected = ['set_needs_human_review_multiple_versions', 'reply', 'comment']
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_DELETED,
                file_status=amo.STATUS_DISABLED,
            ).keys()
        )
        assert expected == actions

    def test_actions_versions_needing_human_review(self):
        NeedsHumanReview.objects.create(version=self.review_version)
        self.grant_permission(self.user, 'Addons:Review')
        expected = ['set_needs_human_review_multiple_versions', 'reply', 'comment']
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_DELETED,
                file_status=amo.STATUS_DISABLED,
            ).keys()
        )
        assert expected == actions

        self.grant_permission(self.user, 'Reviews:Admin')
        expected = [
            'clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'comment',
        ]
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_DELETED,
                file_status=amo.STATUS_DISABLED,
            ).keys()
        )
        assert expected == actions

    def test_set_file(self):
        self.file.update(datestatuschanged=yesterday)
        self.helper.handler.set_file(amo.STATUS_APPROVED, self.review_version.file)

        self.file = self.review_version.file
        assert self.file.status == amo.STATUS_APPROVED
        assert self.file.datestatuschanged.date() > yesterday.date()
        assert self.file.approval_date > yesterday

    def test_set_file_not_approved(self):
        self.file.update(datestatuschanged=yesterday)
        self.helper.handler.set_file(amo.STATUS_DISABLED, self.review_version.file)

        assert self.review_version.file.status == amo.STATUS_DISABLED
        assert not self.review_version.file.approval_date

    def test_logs(self):
        self.helper.set_data({'comments': 'something'})
        self.helper.handler.log_action(amo.LOG.APPROVE_VERSION)
        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    def test_log_action_sets_reasons(self):
        data = {
            'reasons': [
                ReviewActionReason.objects.create(
                    name='reason 1',
                    is_active=True,
                ),
                ReviewActionReason.objects.create(
                    name='reason 2',
                    is_active=True,
                ),
            ],
        }
        self.helper.set_data(data)
        self.helper.handler.log_action(amo.LOG.APPROVE_VERSION)
        assert ReviewActionReasonLog.objects.count() == 2

    def test_log_action_override_user(self):
        # ActivityLog.user will default to self.user in log_action.
        self.helper.set_data(self.get_data())
        self.helper.handler.log_action(amo.LOG.REJECT_VERSION)
        logs = ActivityLog.objects.filter(action=amo.LOG.REJECT_VERSION.id)
        assert logs.count() == 1
        assert logs[0].user == self.user
        # We can override the user.
        task_user = UserProfile.objects.get(id=settings.TASK_USER_ID)
        self.helper.handler.log_action(amo.LOG.APPROVE_VERSION, user=task_user)
        logs = ActivityLog.objects.filter(action=amo.LOG.APPROVE_VERSION.id)
        assert logs.count() == 1
        assert logs[0].user == task_user

    def test_notify_email(self):
        self.helper.set_data(self.get_data())
        base_fragment = 'To respond, please reply to this email or visit'
        user = self.addon.listed_authors[0]
        ActivityLogToken.objects.create(version=self.review_version, user=user)
        uuid = self.review_version.token.get(user=user).uuid.hex
        reply_email = f'reviewreply+{uuid}@{settings.INBOUND_EMAIL_DOMAIN}'

        templates = (
            'extension_nominated_to_approved',
            'extension_nominated_to_rejected',
            'extension_pending_to_rejected',
            'theme_nominated_to_approved',
            'theme_nominated_to_rejected',
            'theme_pending_to_rejected',
        )
        for template in templates:
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            assert len(mail.outbox) == 1
            message = mail.outbox[0]
            assert base_fragment in message.body
            assert message.reply_to == [reply_email]

        mail.outbox = []
        # This one does not inherit from base.txt because it's for unlisted
        # signing notification, which is not really something that necessitates
        # reviewer interaction, so it's simpler.
        template = 'unlisted_to_reviewed_auto'
        self.helper.handler.notify_email(template, 'Sample subject %s, %s')
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert base_fragment not in message.body
        assert message.reply_to == [reply_email]

    @patch('olympia.reviewers.utils.resolve_job_in_cinder.delay')
    def test_resolve_abuse_reports(self, mock_resolve_task):
        log_entry = ActivityLog.objects.create(
            action=amo.LOG.APPROVE_VERSION.id, user=user_factory()
        )
        self.helper.handler.log_entry = log_entry
        cinder_job1 = CinderJob.objects.create(job_id='1')
        cinder_job2 = CinderJob.objects.create(job_id='2')
        self.helper.set_data(
            {**self.get_data(), 'resolve_cinder_jobs': [cinder_job1, cinder_job2]}
        )

        self.helper.handler.resolve_abuse_reports()

        mock_resolve_task.assert_has_calls(
            [
                call(
                    cinder_job_id=cinder_job1.id,
                    log_entry_id=log_entry.id,
                ),
                call(
                    cinder_job_id=cinder_job2.id,
                    log_entry_id=log_entry.id,
                ),
            ]
        )

    def test_email_links(self):
        expected = {
            'extension_nominated_to_approved': 'addon_url',
            'extension_nominated_to_rejected': 'dev_versions_url',
            'extension_pending_to_approved': 'addon_url',
            'extension_pending_to_rejected': 'dev_versions_url',
            'theme_nominated_to_approved': 'addon_url',
            'theme_nominated_to_rejected': 'dev_versions_url',
            'theme_pending_to_approved': 'addon_url',
            'theme_pending_to_rejected': 'dev_versions_url',
            'unlisted_to_reviewed_auto': 'dev_versions_url',
            'reject_multiple_versions': 'dev_versions_url',
            'reject_multiple_versions_with_delay': 'dev_versions_url',
        }

        self.helper.set_data(self.get_data())
        context_data = self.helper.handler.get_context_data()
        for template, context_key in expected.items():
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            assert len(mail.outbox) == 1
            message = mail.outbox[0]
            assert context_key in context_data
            assert context_data.get(context_key) in message.body

    def test_send_reviewer_reply(self):
        self.setup_data(amo.STATUS_APPROVED)
        self.helper.handler.reviewer_reply()

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == self.preamble

        assert self.check_log_count(amo.LOG.REVIEWER_REPLY_VERSION.id) == 1

    def test_email_no_locale(self):
        self.addon.name = {'es': '¿Dónde está la biblioteca?'}
        self.setup_data(amo.STATUS_NOMINATED)
        with translation.override('es'):
            assert translation.get_language() == 'es'
            self.helper.handler.approve_latest_version()

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == (
            'Mozilla Add-ons: Delicious Bookmarks 2.1.072 Approved'
        )
        assert '/en-US/firefox/addon/a3615' not in message.body
        assert '/es/firefox/addon/a3615' not in message.body
        assert '/addon/a3615' in message.body
        assert 'Your add-on, Delicious Bookmarks ' in message.body

    def test_email_no_name(self):
        self.addon.name.delete()
        self.addon.refresh_from_db()
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == ('Mozilla Add-ons: None 2.1.072 Approved')
        assert '/addon/a3615' in message.body
        assert 'Your add-on, None ' in message.body

    def test_nomination_to_public_no_files(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()

        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

    def test_nomination_to_public_and_current_version(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.addon = Addon.objects.get(pk=3615)
        self.addon.update(_current_version=None)
        assert not self.addon.current_version

        self.helper.handler.approve_latest_version()
        self.addon = Addon.objects.get(pk=3615)
        assert self.addon.current_version

    def test_nomination_to_public_new_addon(self):
        """Make sure new add-ons can be made public (bug 637959)"""
        status = amo.STATUS_NOMINATED
        self.setup_data(status)
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=101
        )

        # Make sure we have no public files
        for version in self.addon.versions.all():
            version.file.update(status=amo.STATUS_AWAITING_REVIEW)

        self.helper.handler.approve_latest_version()

        # Re-fetch the add-on
        addon = Addon.objects.get(pk=3615)

        assert addon.status == amo.STATUS_APPROVED

        assert addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == '%s Approved' % self.preamble

        # AddonApprovalsCounter counter is now at 1 for this addon since there
        # was a human review.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1
        self.assertCloseToNow(approval_counter.last_human_review)

        assert storage.exists(self.file.file.path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    def test_nomination_to_public_need_human_review(self):
        self.setup_data(amo.STATUS_NOMINATED)
        NeedsHumanReview.objects.create(version=self.review_version)
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.review_version.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert not self.review_version.needshumanreview_set.filter(
            is_active=True
        ).exists()
        assert self.review_version.human_review_date

    def test_nomination_to_public_need_human_review_not_human(self):
        self.setup_data(amo.STATUS_NOMINATED, human_review=False)
        NeedsHumanReview.objects.create(version=self.review_version)
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.review_version.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.review_version.needshumanreview_set.filter(is_active=True).exists()
        assert not self.review_version.human_review_date

    def test_unlisted_approve_latest_version_need_human_review(self):
        self.setup_data(
            amo.STATUS_NULL, channel=amo.CHANNEL_UNLISTED, human_review=True
        )
        NeedsHumanReview.objects.create(version=self.review_version)
        flags = version_review_flags_factory(
            version=self.review_version,
            needs_human_review_by_mad=True,
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval_unlisted=True
        )
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.review_version.reload()
        self.file.reload()
        flags.reload()
        addon_flags = self.addon.reviewerflags.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED
        assert not self.review_version.needshumanreview_set.filter(
            is_active=True
        ).exists()
        assert not flags.needs_human_review_by_mad
        assert not addon_flags.auto_approval_disabled_until_next_approval_unlisted
        assert self.review_version.human_review_date

    def test_unlisted_approve_latest_version_need_human_review_not_human(self):
        self.setup_data(
            amo.STATUS_NULL, channel=amo.CHANNEL_UNLISTED, human_review=False
        )
        NeedsHumanReview.objects.create(version=self.review_version)
        flags = version_review_flags_factory(
            version=self.review_version, needs_human_review_by_mad=True
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval_unlisted=True
        )
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.review_version.reload()
        self.file.reload()
        flags.reload()
        addon_flags = self.addon.reviewerflags.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED
        assert self.review_version.needshumanreview_set.filter(is_active=True).exists()
        assert flags.needs_human_review_by_mad
        assert not self.review_version.human_review_date

        # Not changed this this is not a human approval.
        assert addon_flags.auto_approval_disabled_until_next_approval_unlisted

    def _unlisted_approve_flag_if_passed_auto_approval_delayed_setup(self, delay):
        self.setup_data(
            amo.STATUS_NULL, channel=amo.CHANNEL_UNLISTED, human_review=False
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_delayed_until_unlisted=delay
        )
        assert not self.review_version.needshumanreview_set.filter(
            is_active=True
        ).exists()

        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.review_version.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED

    def test_unlisted_approve_flag_if_passed_auto_approval_delayed(self):
        yesterday = datetime.now() - timedelta(days=1)
        self._unlisted_approve_flag_if_passed_auto_approval_delayed_setup(yesterday)
        assert self.review_version.needshumanreview_set.filter(is_active=True).exists()

    def test_unlisted_approve_dont_flag_if_not_past_auto_approval_delayed(self):
        tomorrow = datetime.now() + timedelta(days=1)
        self._unlisted_approve_flag_if_passed_auto_approval_delayed_setup(tomorrow)
        assert not self.review_version.needshumanreview_set.filter(
            is_active=True
        ).exists()

    def test_nomination_to_public_with_version_reviewer_flags(self):
        flags = version_review_flags_factory(
            version=self.addon.current_version,
            needs_human_review_by_mad=True,
            pending_rejection=datetime.now() + timedelta(days=2),
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )
        assert flags.needs_human_review_by_mad

        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()

        flags.refresh_from_db()
        assert not flags.needs_human_review_by_mad
        assert not flags.pending_rejection
        assert not flags.pending_rejection_by
        assert flags.pending_content_rejection is None

    def test_nomination_to_public(self):
        self.sign_file_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)
        AutoApprovalSummary.objects.update_or_create(
            version=self.review_version,
            defaults={'verdict': amo.AUTO_APPROVED, 'weight': 101},
        )

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == ('%s Approved' % self.preamble)
        assert 'has been approved' in message.body

        # AddonApprovalsCounter counter is now at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1

        self.sign_file_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file.path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    def test_nomination_to_public_not_human(self):
        self.sign_file_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED, human_review=False)

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == ('%s Approved' % self.preamble)
        assert 'has been approved' in message.body

        # AddonApprovalsCounter counter is now at 0 for this addon since there
        # was an automatic approval.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 0
        # Since approval counter did not exist for this add-on before, the last
        # human review field should be empty.
        assert approval_counter.last_human_review is None

        self.sign_file_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file.path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id, get_task_user()) == 1

        assert not self.review_version.human_review_date

    def test_public_addon_with_version_awaiting_review_to_public(self):
        self.sign_file_mock.reset()
        self.addon.current_version.update(created=self.days_ago(1))
        self.review_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            version='3.0.42',
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'filename': 'webextension.xpi',
            },
        )
        self.preamble = 'Mozilla Add-ons: Delicious Bookmarks 3.0.42'
        self.file = self.review_version.file
        self.setup_data(amo.STATUS_APPROVED)
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=101
        )
        self.create_paths()
        AddonApprovalsCounter.objects.create(
            addon=self.addon, counter=1, last_human_review=self.days_ago(42)
        )

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_AWAITING_REVIEW
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        self.helper.handler.approve_latest_version()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == ('%s Updated' % self.preamble)
        assert 'has been updated' in message.body

        # AddonApprovalsCounter counter is now at 2 for this addon since there
        # was another human review. The last human review date should have been
        # updated.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 2
        self.assertCloseToNow(approval_counter.last_human_review)

        self.sign_file_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file.path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self.addon.reviewerflags.reload()
        assert not self.addon.reviewerflags.auto_approval_disabled_until_next_approval

    def test_public_addon_with_version_need_human_review_to_public(self):
        self.old_version = self.addon.current_version
        self.old_version.update(created=self.days_ago(1))
        NeedsHumanReview.objects.create(version=self.old_version)
        self.review_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            version='3.0.42',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.file = self.review_version.file
        self.setup_data(amo.STATUS_APPROVED, human_review=True)

        self.helper.handler.approve_latest_version()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)
        self.old_version.reload()
        assert not self.old_version.needshumanreview_set.filter(is_active=True).exists()
        assert self.review_version.human_review_date

    def test_public_addon_with_auto_approval_temporarily_disabled_to_public(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval=True
        )
        self.review_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            version='3.0.42',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.file = self.review_version.file
        self.setup_data(amo.STATUS_APPROVED)

        self.helper.handler.approve_latest_version()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)
        self.addon.reviewerflags.reload()
        assert not self.addon.reviewerflags.auto_approval_disabled_until_next_approval

    def test_public_addon_with_version_awaiting_review_to_sandbox(self):
        self.sign_file_mock.reset()
        self.addon.current_version.update(created=self.days_ago(1))
        self.review_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            version='3.0.42',
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'filename': 'webextension.xpi',
            },
        )
        self.preamble = 'Mozilla Add-ons: Delicious Bookmarks 3.0.42'
        self.file = self.review_version.file
        self.setup_data(amo.STATUS_APPROVED)
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=101
        )
        AddonApprovalsCounter.objects.create(addon=self.addon, counter=1)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_AWAITING_REVIEW
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        self.helper.handler.reject_latest_version()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_DISABLED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == ("%s didn't pass review" % self.preamble)
        assert 'reviewed and did not meet the criteria' in message.body

        # AddonApprovalsCounter counter is still at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1

        assert not self.sign_file_mock.called
        assert storage.exists(self.file.file.path)
        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    def test_public_addon_with_version_need_human_review_to_sandbox(self):
        self.old_version = self.addon.current_version
        self.old_version.update(created=self.days_ago(1))
        NeedsHumanReview.objects.create(version=self.old_version)
        self.review_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            version='3.0.42',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        NeedsHumanReview.objects.create(version=self.review_version)
        self.file = self.review_version.file
        self.setup_data(amo.STATUS_APPROVED, human_review=True)

        self.helper.handler.reject_latest_version()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_DISABLED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        # Both version awaiting review and current public version had been
        # flagged as needing human review. Only the newer version has been
        # reviewed and rejected, so we leave the flag on past versions (unlike
        # approvals, we can't be sure the current version is safe now).
        self.addon.current_version.reload()
        assert self.addon.current_version.needshumanreview_set.filter(
            is_active=True
        ).exists()
        assert not self.addon.current_version.human_review_date

        self.review_version.reload()
        assert not self.review_version.needshumanreview_set.filter(
            is_active=True
        ).exists()
        assert self.review_version.human_review_date

    def test_public_addon_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        summary = AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=151
        )
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED, human_review=True
        )
        self.create_paths()

        # Safeguards.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)
        assert not self.review_version.human_review_date
        assert summary.confirmed is None

        self.helper.handler.data['action'] = 'confirm_auto_approved'
        self.helper.process()

        summary.reload()
        assert summary.confirmed is True
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        self.assertCloseToNow(approvals_counter.last_human_review)
        assert self.check_log_count(amo.LOG.APPROVE_CONTENT.id) == 0
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
            .get()
        )
        assert activity.arguments == [self.addon, self.review_version]
        assert activity.details['comments'] == ''
        assert self.review_version.reload().human_review_date

    def test_public_with_unreviewed_version_addon_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.current_version = self.review_version
        summary = AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=152
        )
        self.review_version = version_factory(
            addon=self.addon,
            version='3.0',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.file = self.review_version.file
        self.helper = self.get_helper()  # To make it pick up the new version.
        self.helper.set_data(self.get_data())

        # Confirm approval action should be available even if the latest
        # version is not public, what we care about is the current_version.
        assert 'confirm_auto_approved' in self.helper.actions

        self.helper.handler.data['action'] = 'confirm_auto_approved'
        self.helper.process()

        summary.reload()
        assert summary.confirmed is True
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        self.assertCloseToNow(approvals_counter.last_human_review)
        assert self.check_log_count(amo.LOG.APPROVE_CONTENT.id) == 0
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
            .get()
        )
        assert activity.arguments == [self.addon, self.current_version]
        assert activity.details['comments'] == ''

    def test_public_with_disabled_version_addon_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.current_version = self.review_version
        summary = AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=153
        )
        self.review_version = version_factory(
            addon=self.addon, version='3.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        self.file = self.review_version.file
        self.helper = self.get_helper()  # To make it pick up the new version.
        self.helper.set_data(self.get_data())

        # Confirm approval action should be available even if the latest
        # version is not public, what we care about is the current_version.
        assert 'confirm_auto_approved' in self.helper.actions

        self.helper.handler.data['action'] = 'confirm_auto_approved'
        self.helper.process()

        summary.reload()
        assert summary.confirmed is True
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        self.assertCloseToNow(approvals_counter.last_human_review)
        assert self.check_log_count(amo.LOG.APPROVE_CONTENT.id) == 0
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
            .get()
        )
        assert activity.arguments == [self.addon, self.current_version]
        assert activity.details['comments'] == ''

    def test_addon_with_versions_pending_rejection_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.review_version = version_factory(
            addon=self.addon, version='3.0', file_kw={'status': amo.STATUS_APPROVED}
        )
        self.file = self.review_version.file
        summary = AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=153
        )

        for version in self.addon.versions.all():
            version_review_flags_factory(
                version=version,
                pending_rejection=datetime.now() + timedelta(days=7),
                pending_rejection_by=user_factory(),
                pending_content_rejection=False,
            )

        self.helper = self.get_helper()  # To make it pick up the new version.
        self.helper.set_data(self.get_data())

        # We're an admin, so we can confirm auto approval even if the current
        # version is pending rejection.
        assert 'confirm_auto_approved' in self.helper.actions
        self.helper.handler.data['action'] = 'confirm_auto_approved'
        self.helper.process()

        summary.reload()
        assert summary.confirmed is True
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        self.assertCloseToNow(approvals_counter.last_human_review)
        assert self.check_log_count(amo.LOG.APPROVE_CONTENT.id) == 0
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
            .get()
        )
        assert activity.arguments == [self.addon, self.review_version]
        assert activity.details['comments'] == ''

        # None of the versions should be pending rejection anymore.
        assert not VersionReviewerFlags.objects.filter(
            version__addon=self.addon, pending_rejection__isnull=False
        ).exists()
        # pending_rejection_by should be cleared as well.
        assert not VersionReviewerFlags.objects.filter(
            version__addon=self.addon, pending_rejection_by__isnull=False
        ).exists()
        # pending_content_rejection should be cleared too
        assert not VersionReviewerFlags.objects.filter(
            version__addon=self.addon, pending_content_rejection__isnull=False
        ).exists()

    def test_confirm_auto_approved_approves_for_promoted(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        PromotedAddon.objects.create(addon=self.addon, group_id=NOTABLE.id)
        self.create_paths()

        # Safeguards.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        self.helper.handler.confirm_auto_approved()

        self.addon.reload()
        self.addon.promotedaddon.reload()
        assert self.addon.promoted_group() == NOTABLE, self.addon.promotedaddon
        assert self.review_version.reload().approved_for_groups == [
            (NOTABLE, amo.FIREFOX),
            (NOTABLE, amo.ANDROID),
        ]

    def test_addon_with_version_need_human_review_confirm_auto_approval(self):
        NeedsHumanReview.objects.create(version=self.addon.current_version)
        assert self.addon.current_version.due_date
        self.test_public_addon_confirm_auto_approval()
        self.addon.current_version.reload()
        assert not self.addon.current_version.needshumanreview_set.filter(
            is_active=True
        ).exists()
        assert not self.addon.current_version.due_date
        assert self.addon.current_version.human_review_date

    def test_addon_with_old_versions_needing_human_review_confirm_auto_approval(self):
        previous_version = self.addon.current_version
        NeedsHumanReview.objects.create(version=self.addon.current_version)
        assert self.addon.current_version.due_date
        self.review_version = version_factory(addon=self.addon)
        self.test_public_addon_confirm_auto_approval()
        self.review_version.reload()
        previous_version.reload()
        assert not self.review_version.needshumanreview_set.filter(
            is_active=True
        ).exists()
        assert not self.review_version.due_date
        assert not previous_version.needshumanreview_set.filter(is_active=True).exists()
        assert not previous_version.due_date

    def test_addon_with_version_and_scanner_flag_confirm_auto_approvals(self):
        flags = version_review_flags_factory(
            version=self.addon.current_version,
            needs_human_review_by_mad=True,
        )
        assert flags.needs_human_review_by_mad

        self.test_public_addon_confirm_auto_approval()

        flags.refresh_from_db()
        assert not flags.needs_human_review_by_mad

    def test_deleted_addon_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.review_version = self.addon.current_version
        self.addon.delete()
        self.review_version.reload()
        self.file = self.review_version.file
        summary = AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=42
        )
        self.helper = self.get_helper()
        self.helper.set_data(self.get_data())

        assert 'confirm_auto_approved' in self.helper.actions
        self.helper.handler.confirm_auto_approved()

        summary.reload()
        assert summary.confirmed
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        self.assertCloseToNow(approvals_counter.last_human_review)
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1

    def test_disabled_by_user_addon_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.review_version = self.addon.current_version
        self.addon.update(disabled_by_user=True)
        self.review_version.reload()
        self.file = self.review_version.file
        summary = AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=42
        )
        self.helper = self.get_helper()
        self.helper.set_data(self.get_data())

        assert 'confirm_auto_approved' in self.helper.actions
        self.helper.handler.confirm_auto_approved()

        summary.reload()
        assert summary.confirmed
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        self.assertCloseToNow(approvals_counter.last_human_review)
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1

    def test_current_version_not_auto_approved_confirm_auto_approval_not_present(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.review_version = version_factory(
            # Prevent new version from becoming the current_version...
            addon=self.addon,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        # ... But pretend it was auto-approved initially.
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=666
        )
        self.helper = self.get_helper()
        self.helper.set_data(self.get_data())

        assert 'confirm_auto_approved' not in self.helper.actions

    def test_confirm_multiple_versions_with_version_scanner_flags(self):
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.review_version.update(channel=amo.CHANNEL_UNLISTED)
        flags = version_review_flags_factory(
            version=self.review_version,
            needs_human_review_by_mad=True,
        )
        assert flags.needs_human_review_by_mad
        helper = self.get_helper()  # pick the updated version
        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        helper.set_data(data)

        helper.handler.confirm_multiple_versions()

        flags.refresh_from_db()
        assert not flags.needs_human_review_by_mad

    def test_unlisted_version_addon_confirm_multiple_versions(self):
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

        # This add-on will have 4 versions:
        # - one listed (the initial one from setup)
        # - one unlisted we'll confirm approval of (has an AutoApprovalSummary)
        # - one unlisted we'll confirm approval of (no AutoApprovalSummary) and
        #   flagged by scanners
        # - one unlisted flagged by scanners we'll leave alone
        first_unlisted = version_factory(
            addon=self.addon,
            version='3.0',
            channel=amo.CHANNEL_UNLISTED,
            created=self.days_ago(7),
        )
        summary = AutoApprovalSummary.objects.create(
            version=first_unlisted, verdict=amo.AUTO_APPROVED
        )
        second_unlisted = version_factory(
            addon=self.addon,
            version='4.0',
            channel=amo.CHANNEL_UNLISTED,
            created=self.days_ago(6),
        )
        NeedsHumanReview.objects.create(version=second_unlisted)

        self.review_version = version_factory(
            addon=self.addon,
            version='5.0',
            channel=amo.CHANNEL_UNLISTED,
            created=self.days_ago(5),
        )
        NeedsHumanReview.objects.create(version=self.review_version)
        self.file = self.review_version.file
        self.helper = self.get_helper()  # To make it pick up the new version.
        data = self.get_data().copy()
        data['versions'] = self.addon.versions.filter(
            pk__in=(first_unlisted.pk, second_unlisted.pk)
        )
        self.helper.set_data(data)

        # Confirm multiple versions action should be available since we're
        # looking at an unlisted version and the reviewer has permission.
        assert 'confirm_multiple_versions' in self.helper.actions

        self.helper.handler.confirm_multiple_versions()

        summary.reload()
        assert summary.confirmed is True

        self.review_version.reload()
        assert self.review_version.needshumanreview_set.filter(
            is_active=True
        ).exists()  # Untouched.
        assert not self.review_version.human_review_date  # Not set.

        second_unlisted.reload()
        assert not second_unlisted.needshumanreview_set.filter(
            is_active=True
        ).exists()  # Cleared.
        assert second_unlisted.human_review_date  # Set.

        assert (
            AddonApprovalsCounter.objects.filter(addon=self.addon).count() == 0
        )  # Not incremented since it was unlisted.

        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
            .get()
        )
        assert activity.arguments == [self.addon, second_unlisted, first_unlisted]

    def test_unlisted_manual_approval_clear_pending_rejection(self):
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(
            amo.STATUS_NULL, channel=amo.CHANNEL_UNLISTED, human_review=True
        )
        self.review_version.update(channel=amo.CHANNEL_UNLISTED)
        flags = version_review_flags_factory(
            version=self.review_version,
            pending_rejection=datetime.now() + timedelta(days=7),
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )

        assert flags.pending_rejection
        assert flags.pending_rejection_by
        assert not flags.pending_content_rejection

        self.helper.handler.approve_latest_version()

        flags.refresh_from_db()
        assert not flags.pending_rejection
        assert not flags.pending_rejection_by
        assert flags.pending_content_rejection is None

    def test_null_to_public_unlisted(self):
        self.sign_file_mock.reset()
        self.setup_data(amo.STATUS_NULL, channel=amo.CHANNEL_UNLISTED)

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        # AddonApprovalsCounter was not touched since the version we made
        # public is unlisted.
        assert not AddonApprovalsCounter.objects.filter(addon=self.addon).exists()

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == ('%s signed and ready to download' % self.preamble)
        assert (
            '%s is now signed and ready for you to download'
            % self.review_version.version
            in message.body
        )
        assert 'You received this email because' not in message.body

        self.sign_file_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file.path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    def test_nomination_to_public_failed_signing(self):
        self.sign_file_mock.side_effect = SigningError
        self.sign_file_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)

        with self.assertRaises(SigningError):
            self.helper.handler.approve_latest_version()

        # AddonApprovalsCounter was not touched since we failed signing.
        assert not AddonApprovalsCounter.objects.filter(addon=self.addon).exists()

        # Status unchanged.
        assert self.addon.status == amo.STATUS_NOMINATED
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_AWAITING_REVIEW)

        assert len(mail.outbox) == 0
        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 0

    def test_nomination_to_sandbox(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.reject_latest_version()

        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_DISABLED)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == ("%s didn't pass review" % self.preamble)
        assert 'did not meet the criteria' in message.body

        # AddonApprovalsCounter was not touched since we didn't approve.
        assert not AddonApprovalsCounter.objects.filter(addon=self.addon).exists()

        assert not self.sign_file_mock.called
        assert storage.exists(self.file.file.path)
        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    def test_email_unicode_monster(self):
        self.addon.name = 'TaobaoShopping淘宝网导航按钮'
        self.addon.save()
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.reject_latest_version()
        message = mail.outbox[0]
        assert 'TaobaoShopping淘宝网导航按钮' in message.subject

    def test_auto_approved_admin_theme_review(self):
        self.setup_data(
            amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED,
            type=amo.ADDON_STATICTHEME,
        )
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        self.helper.handler.request_admin_review()

        assert self.addon.needs_admin_theme_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_THEME.id) == 1
        assert getattr(amo.LOG.REQUEST_ADMIN_REVIEW_THEME, 'sanitize', '')

    def test_clear_admin_review(self):
        self.setup_data(
            amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED,
            type=amo.ADDON_STATICTHEME,
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_theme_review=True
        )
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        self.helper.handler.clear_admin_review()

        assert not self.addon.reviewerflags.reload().needs_admin_theme_review
        assert self.check_log_count(amo.LOG.CLEAR_ADMIN_REVIEW_THEME.id) == 1

    def test_operating_system_present(self):
        self.setup_data(amo.STATUS_APPROVED)
        self.helper.handler.reject_latest_version()
        message = mail.outbox[0]
        assert 'Tested on osx with Firefox' in message.body

    def test_operating_system_not_present(self):
        self.setup_data(amo.STATUS_APPROVED)
        data = self.get_data().copy()
        data['operating_systems'] = ''
        self.helper.set_data(data)
        self.helper.handler.reject_latest_version()
        message = mail.outbox[0]
        assert 'Tested with Firefox' in message.body

    def test_application_not_present(self):
        self.setup_data(amo.STATUS_APPROVED)
        data = self.get_data().copy()
        data['applications'] = ''
        self.helper.set_data(data)
        self.helper.handler.reject_latest_version()
        message = mail.outbox[0]
        assert 'Tested on osx' in message.body

    def test_both_not_present(self):
        self.setup_data(amo.STATUS_APPROVED)
        data = self.get_data().copy()
        data['applications'] = ''
        data['operating_systems'] = ''
        self.helper.set_data(data)
        self.helper.handler.reject_latest_version()
        message = mail.outbox[0]
        assert 'Tested' not in message.body

    def test_nominated_human_review_date_set_version_approve_latest_version(self):
        self.review_version.update(human_review_date=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()
        assert self.review_version.reload().human_review_date

    def test_nominated_human_review_date_set_version_reject_latest_version(self):
        self.review_version.update(human_review_date=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.reject_latest_version()
        assert self.review_version.reload().human_review_date

    def test_nominated_approval_date_set_file_approve_latest_version(self):
        self.file.update(approval_date=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()
        assert File.objects.get(pk=self.file.pk).approval_date

    def test_nominated_approval_date_set_file_reject_latest_version(self):
        self.file.update(approval_date=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.reject_latest_version()
        assert not File.objects.get(pk=self.file.pk).approval_date

    def test_review_unlisted_while_a_listed_version_is_awaiting_review(self):
        self.make_addon_unlisted(self.addon)
        self.review_version.reload()
        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.addon.update(status=amo.STATUS_NOMINATED)
        assert self.get_helper()

    def _test_reject_multiple_versions(self, extra_data):
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=101
        )
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        self.helper.set_data(
            {**self.get_data(), 'versions': self.addon.versions.all(), **extra_data}
        )
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.review_version, old_version]
        assert self.file.status == amo.STATUS_DISABLED

        # The versions are not pending rejection.
        for version in self.addon.versions.all():
            assert version.pending_rejection is None
            assert version.pending_rejection_by is None
            assert version.reviewerflags.pending_content_rejection is None
            assert version.reload().human_review_date

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.addon.authors.all()[0].email]
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.REJECT_VERSION.id)
            .get()
        )
        assert log.arguments == [self.addon, self.review_version, old_version]

        # listed auto approvals should be disabled until the next manual approval.
        flags = self.addon.reviewerflags
        flags.reload()
        assert not flags.auto_approval_disabled_until_next_approval_unlisted
        assert flags.auto_approval_disabled_until_next_approval

    def test_reject_multiple_versions(self):
        self._test_reject_multiple_versions({})
        message = mail.outbox[0]
        assert message.subject == (
            'Mozilla Add-ons: Delicious Bookmarks has been disabled on '
            'addons.mozilla.org'
        )
        assert 'your add-on Delicious Bookmarks has been disabled' in message.body

    def test_reject_multiple_versions_resolving_abuse_report(self):
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': '12345'},
            status=201,
        )
        cinder_job = CinderJob.objects.create(job_id='1')
        AbuseReport.objects.create(guid=self.addon.guid, cinder_job=cinder_job)
        self._test_reject_multiple_versions({'resolve_cinder_jobs': [cinder_job]})
        message = mail.outbox[0]
        assert message.subject == ('Mozilla Add-ons: Delicious Bookmarks [ref:12345]')
        assert 'Extension Delicious Bookmarks was manually reviewed' in message.body
        assert 'those versions of your Extension have been disabled' in message.body

    def test_reject_multiple_versions_with_delay(self):
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=101
        )
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

        in_the_future = datetime.now() + timedelta(days=14)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        data = self.get_data().copy()
        data.update(
            {
                'versions': self.addon.versions.all(),
                'delayed_rejection': True,
                'delayed_rejection_days': 14,
            }
        )
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        # File/addon status didn't change.
        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.current_version == self.review_version
        assert list(self.addon.versions.all()) == [self.review_version, old_version]
        assert self.file.status == amo.STATUS_APPROVED

        # The versions are now pending rejection.
        for version in self.addon.versions.all():
            assert version.pending_rejection
            self.assertCloseToNow(version.pending_rejection, now=in_the_future)
            assert version.pending_rejection_by == self.user
            assert version.reviewerflags.pending_content_rejection is False
            assert version.reload().human_review_date

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.addon.authors.all()[0].email]
        assert message.subject == (
            'Mozilla Add-ons: Delicious Bookmarks will be disabled on '
            'addons.mozilla.org'
        )
        assert 'your add-on Delicious Bookmarks will be disabled' in message.body
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 0
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0
        assert self.check_log_count(amo.LOG.REJECT_CONTENT_DELAYED.id) == 0
        assert self.check_log_count(amo.LOG.REJECT_VERSION_DELAYED.id) == 1

        log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.REJECT_VERSION_DELAYED.id)
            .get()
        )
        assert log.arguments == [self.addon, self.review_version, old_version]

        # The flag to prevent the authors from being notified several times
        # about pending rejections should have been reset, and auto approvals
        # should have been disabled until the next manual approval.
        flags = self.addon.reviewerflags
        flags.reload()
        assert not flags.notified_about_expiring_delayed_rejections
        assert flags.auto_approval_disabled_until_next_approval

    def test_reject_multiple_versions_except_latest(self):
        old_version = self.review_version
        extra_version = version_factory(addon=self.addon, version='3.1')
        # Add yet another version we don't want to reject.
        self.review_version = version_factory(addon=self.addon, version='42.0')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=91
        )
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all().exclude(pk=self.review_version.pk)
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        # latest_version is still public so the add-on is still public.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.current_version == self.review_version
        assert list(self.addon.versions.all().order_by('-pk')) == [
            self.review_version,
            extra_version,
            old_version,
        ]
        assert self.file.status == amo.STATUS_DISABLED

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.addon.authors.all()[0].email]
        assert message.subject == (
            'Mozilla Add-ons: Versions disabled for Delicious Bookmarks'
        )
        assert 'Version(s) affected and disabled:\n3.1, 2.1.072' in message.body
        log_token = ActivityLogToken.objects.filter(version=self.review_version).get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        assert old_version.reload().human_review_date
        assert extra_version.reload().human_review_date
        assert not self.review_version.reload().human_review_date

    def test_reject_multiple_versions_need_human_review(self):
        old_version = self.review_version
        NeedsHumanReview.objects.create(version=old_version)
        self.review_version = version_factory(addon=self.addon, version='3.0')
        NeedsHumanReview.objects.create(version=self.review_version)

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.review_version, old_version]
        # We rejected all versions so there aren't any left that need human
        # review.
        assert not NeedsHumanReview.objects.filter(
            version__addon=self.addon, is_active=True
        ).exists()
        assert self.file.status == amo.STATUS_DISABLED

    def test_reject_multiple_versions_content_review(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED, content_review=True
        )

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.review_version, old_version]
        assert self.file.status == amo.STATUS_DISABLED

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.addon.authors.all()[0].email]
        assert message.subject == (
            'Mozilla Add-ons: Delicious Bookmarks has been disabled on '
            'addons.mozilla.org'
        )
        assert 'your add-on Delicious Bookmarks has been disabled' in message.body
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 0
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 1

    def test_reject_multiple_versions_content_review_with_delay(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED, content_review=True
        )

        in_the_future = datetime.now() + timedelta(days=14)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        data = self.get_data().copy()
        data.update(
            {
                'versions': self.addon.versions.all(),
                'delayed_rejection': True,
                'delayed_rejection_days': 14,
            }
        )
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        # File/addon status didn't change.
        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.current_version == self.review_version
        assert list(self.addon.versions.all()) == [self.review_version, old_version]
        assert self.file.status == amo.STATUS_APPROVED

        # The versions are now pending rejection.
        for version in self.addon.versions.all():
            assert version.pending_rejection
            self.assertCloseToNow(version.pending_rejection, now=in_the_future)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.addon.authors.all()[0].email]
        assert message.subject == (
            'Mozilla Add-ons: Delicious Bookmarks will be disabled on '
            'addons.mozilla.org'
        )
        assert 'your add-on Delicious Bookmarks will be disabled' in message.body
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 0
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0
        assert self.check_log_count(amo.LOG.REJECT_CONTENT_DELAYED.id) == 1
        assert self.check_log_count(amo.LOG.REJECT_VERSION_DELAYED.id) == 0

        log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.REJECT_CONTENT_DELAYED.id)
            .get()
        )
        assert log.arguments == [self.addon, self.review_version, old_version]

    def test_unreject_latest_version_approved_addon(self):
        first_version = self.review_version
        self.review_version = version_factory(
            addon=self.addon, version='3.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        self.file = self.review_version.file
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_DISABLED)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert first_version.file.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_DISABLED
        assert self.addon.current_version.is_public()
        assert self.addon.current_version == first_version

        self.helper.handler.unreject_latest_version()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.current_version == first_version
        assert list(self.addon.versions.all()) == [self.review_version, first_version]
        assert self.file.status == amo.STATUS_AWAITING_REVIEW

        assert len(mail.outbox) == 0

        assert self.check_log_count(amo.LOG.UNREJECT_VERSION.id) == 1

    def test_unreject_multiple_versions_with_unlisted(self):
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        self.file = self.review_version.file
        self.setup_data(
            amo.STATUS_NULL,
            file_status=amo.STATUS_DISABLED,
            channel=amo.CHANNEL_UNLISTED,
        )

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewUnlisted)
        assert self.addon.status == amo.STATUS_NULL
        assert old_version.file.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_DISABLED
        assert self.addon.current_version is None

        data = self.get_data().copy()
        data['versions'] = [self.review_version]
        self.helper.set_data(data)
        self.helper.handler.unreject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.review_version, old_version]
        assert self.file.status == amo.STATUS_AWAITING_REVIEW

        assert len(mail.outbox) == 0

        assert self.check_log_count(amo.LOG.UNREJECT_VERSION.id) == 1

    def test_unreject_latest_version_incomplete_addon(self):
        old_version = self.review_version
        old_version.file.update(status=amo.STATUS_DISABLED)
        self.review_version = version_factory(
            addon=self.addon, version='3.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        self.file = self.review_version.file
        self.setup_data(amo.STATUS_NULL, file_status=amo.STATUS_DISABLED)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_NULL
        assert old_version.file.status == amo.STATUS_DISABLED
        assert self.file.status == amo.STATUS_DISABLED
        assert self.addon.current_version is None

        self.helper.handler.unreject_latest_version()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NOMINATED
        assert self.addon.current_version == self.review_version
        assert list(self.addon.versions.all()) == [self.review_version, old_version]
        assert self.file.status == amo.STATUS_AWAITING_REVIEW

        assert len(mail.outbox) == 0

        assert self.check_log_count(amo.LOG.UNREJECT_VERSION.id) == 1

    def test_approve_multiple_versions_unlisted(self):
        old_version = self.review_version
        self.make_addon_unlisted(self.addon)
        self.review_version = version_factory(
            addon=self.addon,
            version='3.0',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.setup_data(amo.STATUS_NULL, file_status=amo.STATUS_AWAITING_REVIEW)
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled_until_next_approval=True,
            auto_approval_disabled_until_next_approval_unlisted=True,
        )

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewUnlisted)
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_AWAITING_REVIEW

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.approve_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.review_version, old_version]
        assert self.file.status == amo.STATUS_APPROVED

        # unlisted auto approvals should be enabled again
        flags = self.addon.reviewerflags
        flags.reload()
        assert flags.auto_approval_disabled_until_next_approval
        assert not flags.auto_approval_disabled_until_next_approval_unlisted

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.addon.authors.all()[0].email]
        assert message.subject == (
            'Mozilla Add-ons: Delicious Bookmarks signed and ready to download'
        )
        assert (
            'versions of your add-on Delicious Bookmarks are now signed '
            in message.body
        )
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert log.arguments == [self.addon, self.review_version, old_version]

    def test_reject_multiple_versions_unlisted(self):
        old_version = self.review_version
        self.make_addon_unlisted(self.addon)
        self.review_version = version_factory(
            addon=self.addon,
            version='3.0',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=101
        )
        self.setup_data(amo.STATUS_NULL, file_status=amo.STATUS_AWAITING_REVIEW)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewUnlisted)
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_AWAITING_REVIEW

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.review_version, old_version]
        assert self.file.status == amo.STATUS_DISABLED

        # unlisted auto approvals should be disabled until the next manual approval.
        flags = self.addon.reviewerflags
        flags.reload()
        assert not flags.auto_approval_disabled_until_next_approval
        assert flags.auto_approval_disabled_until_next_approval_unlisted

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.addon.authors.all()[0].email]
        assert message.subject == (
            'Mozilla Add-ons: Versions disabled for Delicious Bookmarks'
        )
        assert (
            'versions of your add-on Delicious Bookmarks have been disabled'
            in message.body
        )
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.REJECT_VERSION.id)
            .get()
        )
        assert log.arguments == [self.addon, self.review_version, old_version]

    def _setup_reject_multiple_versions_delayed(self, content_review):
        # Do a rejection with delay.
        original_user = self.user
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=101
        )
        self.setup_data(
            amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED,
            content_review=content_review,
        )

        assert self.addon.status == amo.STATUS_APPROVED

        data = self.get_data().copy()
        data.update(
            {
                'versions': self.addon.versions.all(),
                'delayed_rejection': True,
                'delayed_rejection_days': 14,
            }
        )
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        # Addon status didn't change.
        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED

        # The versions are now pending rejection.
        for version in self.addon.versions.all():
            assert version.pending_rejection
            assert version.pending_rejection_by == original_user
            assert version.reviewerflags.pending_content_rejection == content_review

        delayed_action = (
            amo.LOG.REJECT_VERSION_DELAYED
            if not content_review
            else amo.LOG.REJECT_CONTENT_DELAYED
        )
        assert self.check_log_count(delayed_action.id) == 1
        log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=delayed_action.id)
            .get()
        )
        assert log.arguments == [self.addon, self.review_version, old_version]
        # The request user is recorded as scheduling the rejection.
        assert log.user == original_user

    def _test_reject_multiple_versions_delayed(self, content_review):
        self._setup_reject_multiple_versions_delayed(content_review)
        original_user = self.user
        # Now reject without delay, running as the task user.
        self.user = get_task_user()
        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper = self.get_helper(human_review=False)
        self.helper.set_data(data)

        # Clear our the ActivityLogs.
        ActivityLog.objects.all().delete()

        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_NULL

        action = (
            amo.LOG.REJECT_VERSION if not content_review else amo.LOG.REJECT_CONTENT
        )
        # The request user is recorded as scheduling the rejection.
        assert self.check_log_count(action.id, original_user) == 1

    def test_reject_multiple_versions_delayed_code_review(self):
        self._test_reject_multiple_versions_delayed(content_review=False)

    def test_reject_multiple_versions_delayed_content_review(self):
        self._test_reject_multiple_versions_delayed(content_review=True)

    def _test_reject_multiple_versions_delayed_with_human(self, content_review):
        self._setup_reject_multiple_versions_delayed(content_review)
        # Now reject without delay, as a different reviewer
        self.user = user_factory()
        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper = self.get_helper(human_review=True, content_review=content_review)
        self.helper.set_data(data)

        # Clear our the ActivityLogs.
        ActivityLog.objects.all().delete()

        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_NULL

        action = (
            amo.LOG.REJECT_VERSION if not content_review else amo.LOG.REJECT_CONTENT
        )
        # The new user is recorded as scheduling the rejection.
        assert self.check_log_count(action.id, self.user) == 1

    def test_reject_multiple_versions_delayed_with_human_code_review(self):
        self._test_reject_multiple_versions_delayed_with_human(content_review=False)

    def test_reject_multiple_versions_delayed_with_human_content_review(self):
        self._test_reject_multiple_versions_delayed_with_human(content_review=True)

    def test_approve_content_content_review(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED, content_review=True
        )
        summary = AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED
        )
        self.create_paths()

        # Safeguards.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        self.helper.handler.data['action'] = 'approve_content'
        self.helper.process()

        summary.reload()
        assert summary.confirmed is None  # unchanged.
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approvals_counter.counter == 0
        assert approvals_counter.last_human_review is None
        self.assertCloseToNow(approvals_counter.last_content_review)
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 0
        assert self.check_log_count(amo.LOG.APPROVE_CONTENT.id) == 1
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_CONTENT.id)
            .get()
        )
        assert activity.arguments == [self.addon, self.review_version]
        assert activity.details['comments'] == ''
        assert not self.review_version.human_review_date

    def test_dev_versions_url_in_context(self):
        self.helper.set_data(self.get_data())
        context_data = self.helper.handler.get_context_data()
        assert context_data['dev_versions_url'] == absolutify(
            self.addon.get_dev_url('versions')
        )

        self.review_version.update(channel=amo.CHANNEL_UNLISTED)
        context_data = self.helper.handler.get_context_data()
        assert context_data['dev_versions_url'] == absolutify(
            reverse('devhub.addons.versions', args=[self.addon.id])
        )

    def test_nominated_to_approved_recommended(self):
        self.make_addon_promoted(self.addon, RECOMMENDED)
        assert not self.addon.promoted_group()
        self.test_nomination_to_public()
        assert self.addon.current_version.promoted_approvals.filter(
            group_id=RECOMMENDED.id
        ).exists()
        assert self.addon.promoted_group() == RECOMMENDED

    def test_nominated_to_approved_other_promoted(self):
        self.make_addon_promoted(self.addon, LINE)
        assert not self.addon.promoted_group()
        self.test_nomination_to_public()
        assert self.addon.current_version.promoted_approvals.filter(
            group_id=LINE.id
        ).exists()
        assert self.addon.promoted_group() == LINE

    def test_approved_update_recommended(self):
        self.make_addon_promoted(self.addon, RECOMMENDED)
        assert not self.addon.promoted_group()
        self.test_public_addon_with_version_awaiting_review_to_public()
        assert self.addon.current_version.promoted_approvals.filter(
            group_id=RECOMMENDED.id
        ).exists()
        assert self.addon.promoted_group() == RECOMMENDED

    def test_approved_update_other_promoted(self):
        self.make_addon_promoted(self.addon, LINE)
        assert not self.addon.promoted_group()
        self.test_public_addon_with_version_awaiting_review_to_public()
        assert self.addon.current_version.promoted_approvals.filter(
            group_id=LINE.id
        ).exists()
        assert self.addon.promoted_group() == LINE

    def test_autoapprove_fails_for_promoted(self):
        self.make_addon_promoted(self.addon, RECOMMENDED)
        assert not self.addon.promoted_group()
        self.user = UserProfile.objects.get(id=settings.TASK_USER_ID)

        with self.assertRaises(AssertionError):
            self.test_nomination_to_public()
        assert not PromotedApproval.objects.filter(
            version=self.addon.current_version
        ).exists()
        assert not self.addon.promoted_group()

        # change to other type of promoted; same should happen
        self.addon.promotedaddon.update(group_id=LINE.id)
        with self.assertRaises(AssertionError):
            self.test_nomination_to_public()
        assert not PromotedApproval.objects.filter(
            version=self.addon.current_version
        ).exists()
        assert not self.addon.promoted_group()

        # except for a group that doesn't require prereview
        self.addon.promotedaddon.update(group_id=STRATEGIC.id)
        assert self.addon.promoted_group() == STRATEGIC
        self.test_nomination_to_public()
        # But no promotedapproval though
        assert not PromotedApproval.objects.filter(
            version=self.addon.current_version
        ).exists()
        assert self.addon.promoted_group() == STRATEGIC

    def _test_block_multiple_unlisted_versions(self, redirect_url):
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        NeedsHumanReview.objects.create(version=self.review_version)
        self.setup_data(
            amo.STATUS_NULL,
            file_status=amo.STATUS_APPROVED,
            channel=amo.CHANNEL_UNLISTED,
        )
        # Add a needs_human_review_by_mad flag that should be cleared later.
        version_review_flags_factory(
            version=self.review_version, needs_human_review_by_mad=True
        )
        # Safeguards.
        assert isinstance(self.helper.handler, ReviewUnlisted)
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.block_multiple_versions()

        self.addon.reload()
        self.file.reload()
        # Nothing has changed as we change the statuses as part of the Block
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED
        assert NeedsHumanReview.objects.filter(
            version__addon=self.addon, is_active=True
        ).exists()
        assert VersionReviewerFlags.objects.filter(
            version__addon=self.addon, needs_human_review_by_mad=True
        ).exists()

        # No mails or logging either
        assert len(mail.outbox) == 0
        assert not ActivityLog.objects.for_addons(self.addon).exists()

        # We should have set redirect_url to point to the Block admin page
        if '%s' in redirect_url:
            redirect_url = redirect_url % (self.review_version.pk, old_version.pk)
        assert self.helper.redirect_url == redirect_url

    def test_pending_blocklistsubmission_multiple_unlisted_versions(self):
        BlocklistSubmission.objects.create(
            input_guids=self.addon.guid, updated_by=user_factory()
        )
        redirect_url = (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.id,))
            + '?v=%s&v=%s'
        )
        assert Block.objects.count() == 0
        self._test_block_multiple_unlisted_versions(redirect_url)

    def test_new_block_multiple_unlisted_versions(self):
        redirect_url = (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.id,))
            + '?v=%s&v=%s'
        )
        assert Block.objects.count() == 0
        self._test_block_multiple_unlisted_versions(redirect_url)

    def test_existing_block_multiple_unlisted_versions(self):
        block_factory(guid=self.addon.guid, updated_by=user_factory())
        redirect_url = (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.id,))
            + '?v=%s&v=%s'
        )
        self._test_block_multiple_unlisted_versions(redirect_url)

    def test_approve_latest_version_fails_for_blocked_version(self):
        block_factory(addon=self.addon, updated_by=user_factory())
        self.review_version.refresh_from_db()
        self.setup_data(amo.STATUS_NOMINATED)

        with self.assertRaises(AssertionError):
            self.helper.handler.approve_latest_version()

    def test_clear_needs_human_review_multiple_versions(self):
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        NeedsHumanReview.objects.create(version=self.review_version)
        # set needs_human_review_by_mad - it shouldn't be cleared
        flags = VersionReviewerFlags.objects.create(
            version=self.review_version, needs_human_review_by_mad=True
        )
        # some other versions that are also needs_human_review
        disabled = version_factory(
            addon=self.review_version.addon,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        NeedsHumanReview.objects.create(version=disabled)
        deleted = version_factory(
            addon=self.review_version.addon,
        )
        NeedsHumanReview.objects.create(version=deleted)
        deleted.delete()
        # We won't select that one so it shouldn't be cleared
        unselected = version_factory(
            addon=self.review_version.addon,
        )
        NeedsHumanReview.objects.create(version=unselected)

        data = self.get_data().copy()
        data['versions'] = (
            self.addon.versions(manager='unfiltered_for_relations')
            .all()
            .exclude(pk=unselected.pk)
            .order_by('pk')
        )
        self.helper.set_data(data)
        self.helper.handler.clear_needs_human_review_multiple_versions()

        log_type_id = amo.LOG.CLEAR_NEEDS_HUMAN_REVIEW.id
        assert self.check_log_count(log_type_id) == 1
        assert ActivityLog.objects.for_addons(self.helper.addon).get(
            action=log_type_id
        ).details.get('versions') == [
            self.review_version.version,
            disabled.version,
            deleted.version,
        ]
        assert len(mail.outbox) == 0
        self.review_version.reload()
        assert not self.review_version.human_review_date  # its not been reviewed
        assert not self.review_version.needshumanreview_set.filter(
            is_active=True
        ).exists()
        assert not disabled.needshumanreview_set.filter(is_active=True).exists()
        assert not deleted.needshumanreview_set.filter(is_active=True).exists()
        assert not self.review_version.due_date
        assert not disabled.due_date
        assert not deleted.due_date
        assert unselected.needshumanreview_set.filter(is_active=True).exists()
        assert unselected.due_date

        # mad flag has changed too.
        assert not flags.reload().needs_human_review_by_mad
        assert not self.review_version.needs_human_review_by_mad

    def test_set_needs_human_review_multiple_versions(self):
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        selected = version_factory(addon=self.review_version.addon)
        unselected = version_factory(addon=self.review_version.addon)
        data = self.get_data().copy()
        data['versions'] = (
            self.addon.versions(manager='unfiltered_for_relations')
            .all()
            .exclude(pk=unselected.pk)
            .order_by('pk')
        )
        self.helper.set_data(data)
        self.helper.handler.set_needs_human_review_multiple_versions()

        log_type_id = amo.LOG.NEEDS_HUMAN_REVIEW.id
        assert self.check_log_count(log_type_id) == 1
        assert ActivityLog.objects.for_addons(self.helper.addon).get(
            action=log_type_id
        ).details.get('versions') == [
            self.review_version.version,
            selected.version,
        ]
        assert self.check_log_count(amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id) == 0
        assert len(mail.outbox) == 0

        self.review_version.reload()
        assert not self.review_version.human_review_date
        assert self.review_version.needshumanreview_set.filter(is_active=True).exists()
        assert self.review_version.due_date

        selected.reload()
        assert not selected.human_review_date
        assert selected.needshumanreview_set.filter(is_active=True).exists()
        assert selected.due_date

        unselected.reload()
        assert not selected.human_review_date
        assert not unselected.needshumanreview_set.filter(is_active=True).exists()
        assert not unselected.due_date

    def test_clear_pending_rejection_multiple_versions(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        VersionReviewerFlags.objects.create(
            version=self.review_version,
            pending_rejection=datetime.now() + timedelta(days=1),
            pending_rejection_by=self.user,
            pending_content_rejection=False,
        )
        selected = version_factory(addon=self.review_version.addon)
        VersionReviewerFlags.objects.create(
            version=selected,
            pending_rejection=datetime.now() + timedelta(days=2),
            pending_rejection_by=self.user,
            pending_content_rejection=True,
        )
        unselected = version_factory(addon=self.review_version.addon)
        VersionReviewerFlags.objects.create(
            version=unselected,
            pending_rejection=datetime.now() + timedelta(days=3),
            pending_rejection_by=self.user,
            pending_content_rejection=False,
        )
        data = self.get_data().copy()
        data['versions'] = (
            self.addon.versions(manager='unfiltered_for_relations')
            .all()
            .exclude(pk=unselected.pk)
            .order_by('pk')
        )
        data['action'] = 'clear_pending_rejection_multiple_versions'
        self.helper.set_data(data)
        self.helper.process()

        log_type_id = amo.LOG.CLEAR_PENDING_REJECTION.id
        assert self.check_log_count(log_type_id) == 1
        activity = ActivityLog.objects.for_addons(self.helper.addon).get(
            action=log_type_id
        )
        assert activity.details['comments'] == ''
        assert activity.details['versions'] == [
            self.review_version.version,
            selected.version,
        ]
        assert len(mail.outbox) == 0

        self.review_version.reload()
        self.review_version.reviewerflags.reload()
        assert not self.review_version.human_review_date
        assert self.review_version.reviewerflags.pending_content_rejection is None
        assert self.review_version.reviewerflags.pending_rejection_by is None
        assert self.review_version.reviewerflags.pending_rejection is None

        selected.reload()
        selected.reviewerflags.reload()
        assert not selected.human_review_date
        assert selected.reviewerflags.pending_content_rejection is None
        assert selected.reviewerflags.pending_rejection_by is None
        assert selected.reviewerflags.pending_rejection is None

        unselected.reload()
        unselected.reviewerflags.reload()
        assert not unselected.human_review_date
        assert unselected.reviewerflags.pending_content_rejection is False
        assert unselected.reviewerflags.pending_rejection_by
        assert unselected.reviewerflags.pending_rejection is not None

    def test_disable_addon(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.helper.handler.disable_addon()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 1
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.FORCE_DISABLE.id
        assert activity_log.arguments[0] == self.addon

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == ('%s has been disabled' % self.preamble)
        assert 'disabled' in message.body

    def test_enable_addon(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_DISABLED, file_status=amo.STATUS_APPROVED)
        self.helper.handler.enable_addon()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 1
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.FORCE_ENABLE.id
        assert activity_log.arguments[0] == self.addon

        assert len(mail.outbox) == 0

    def test_enable_addon_no_public_versions_should_fall_back_to_incomplete(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_DISABLED, file_status=amo.STATUS_APPROVED)
        self.addon.versions.all().delete()

        self.helper.handler.enable_addon()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert len(mail.outbox) == 0

    def test_enable_addon_version_is_awaiting_review_fall_back_to_nominated(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_DISABLED, file_status=amo.STATUS_AWAITING_REVIEW)

        self.helper.handler.enable_addon()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_NOMINATED
        assert len(mail.outbox) == 0

    def _resolve_abuse_reports_called_everywhere_checkbox_shown(self, actions):
        # these two functions are to verify we call log_action before it's accessed
        def log_check():
            assert self.helper.handler.log_entry

        def log_action(*args, **kwargs):
            self.helper.handler.log_entry = object()

        self.helper.handler.data = {'versions': [self.review_version]}
        resolves_actions = {
            key: action
            for key, action in self.helper.actions.items()
            if action.get('resolves_abuse_reports', False)
        }
        should_email = dict(actions)
        assert list(resolves_actions) == list(should_email)

        self.helper.handler.notify_email = lambda *arg, **kwarg: None
        with (
            patch.object(
                self.helper.handler, 'resolve_abuse_reports', wraps=log_check
            ) as resolve_mock,
            patch.object(
                self.helper.handler, 'log_action', wraps=log_action
            ) as log_action_mock,
        ):
            for action_name, action in resolves_actions.items():
                action['method']()
                resolve_mock.assert_called_once()
                resolve_mock.reset_mock()
                log_entry = log_action_mock.call_args.args[0]
                assert (
                    getattr(log_entry, 'hide_developer', False)
                    != should_email[action_name]
                )
                assert hasattr(log_entry, 'cinder_action')
                log_action_mock.assert_called_once()
                log_action_mock.reset_mock()
                self.helper.handler.log_entry = None
                self.helper.handler.version = self.review_version

    def test_resolve_abuse_reports_called_everywhere_checkbox_shown_listed(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.grant_permission(self.user, 'Addons:Review')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=42
        )
        self.setup_data(amo.STATUS_APPROVED, channel=amo.CHANNEL_LISTED)
        self._resolve_abuse_reports_called_everywhere_checkbox_shown(
            [
                ('public', True),
                ('reject', True),
                ('confirm_auto_approved', False),
                ('reject_multiple_versions', True),
                ('clear_needs_human_review_multiple_versions', False),
                ('disable_addon', True),
            ]
        )
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_DISABLED)
        assert self.addon.status == amo.STATUS_APPROVED
        self._resolve_abuse_reports_called_everywhere_checkbox_shown(
            [
                ('confirm_auto_approved', False),
                ('reject_multiple_versions', True),
                ('unreject_latest_version', True),
                ('clear_needs_human_review_multiple_versions', False),
                ('disable_addon', True),
            ]
        )
        self.setup_data(amo.STATUS_DISABLED, file_status=amo.STATUS_DISABLED)
        self._resolve_abuse_reports_called_everywhere_checkbox_shown(
            [
                ('confirm_auto_approved', False),
                ('clear_needs_human_review_multiple_versions', False),
                ('enable_addon', True),
            ]
        )

    def test_resolve_abuse_reports_called_everywhere_checkbox_shown_unlisted(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=42
        )
        self.setup_data(amo.STATUS_APPROVED, channel=amo.CHANNEL_UNLISTED)
        self._resolve_abuse_reports_called_everywhere_checkbox_shown(
            [
                ('public', True),
                ('approve_multiple_versions', True),
                ('reject_multiple_versions', True),
                ('unreject_multiple_versions', True),
                ('confirm_multiple_versions', False),
                ('clear_needs_human_review_multiple_versions', False),
                ('disable_addon', True),
            ]
        )
        self.setup_data(amo.STATUS_DISABLED, file_status=amo.STATUS_DISABLED)
        self._resolve_abuse_reports_called_everywhere_checkbox_shown(
            [
                ('approve_multiple_versions', True),
                ('reject_multiple_versions', True),
                ('confirm_multiple_versions', False),
                ('clear_needs_human_review_multiple_versions', False),
                ('enable_addon', True),
            ]
        )


@override_settings(ENABLE_ADDON_SIGNING=True)
class TestReviewHelperSigning(TestReviewHelperBase):
    """Tests that call signing but don't mock the actual call.

    Instead tests will have to check the end-result to see if the signing
    calls succeeded.
    """

    __test__ = True

    def setUp(self):
        super().setUp()
        responses.add_passthru(settings.AUTOGRAPH_CONFIG['server_url'])

        self.addon = addon_factory(
            guid='test@local',
            file_kw={'filename': 'webextension.xpi'},
            users=[self.user],
        )
        self.review_version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.review_version.file

    def test_nomination_to_public(self):
        self.setup_data(amo.STATUS_NOMINATED)

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1

        # AddonApprovalsCounter counter is now at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1

        assert storage.exists(self.file.file.path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        signature_info, manifest = _get_signature_details(self.file.file.path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'test@local'
        assert manifest.count('Name: ') == 4

        assert 'Name: index.js' in manifest
        assert 'Name: manifest.json' in manifest
        assert 'Name: META-INF/cose.manifest' in manifest
        assert 'Name: META-INF/cose.sig' in manifest

    def test_nominated_to_public_recommended(self):
        self.setup_data(amo.STATUS_NOMINATED)

        self.make_addon_promoted(self.addon, RECOMMENDED)
        assert not self.addon.promoted_group()

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        assert self.addon.current_version.promoted_approvals.filter(
            group_id=RECOMMENDED.id
        ).exists()
        assert self.addon.promoted_group() == RECOMMENDED

        signature_info, manifest = _get_signature_details(self.file.file.path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'test@local'
        assert manifest.count('Name: ') == 5

        assert 'Name: index.js' in manifest
        assert 'Name: manifest.json' in manifest
        assert 'Name: META-INF/cose.manifest' in manifest
        assert 'Name: META-INF/cose.sig' in manifest
        assert 'Name: mozilla-recommendation.json' in manifest

        recommendation_data = _get_recommendation_data(self.file.file.path)
        assert recommendation_data['addon_id'] == 'test@local'
        assert sorted(recommendation_data['states']) == [
            'recommended',
            'recommended-android',
        ]


def test_send_email_autoescape():
    s = 'woo&&<>\'""'

    # Make sure HTML is not auto-escaped.
    send_mail(
        'Random subject with %s',
        s,
        recipient_list=['nobody@mozilla.org'],
        from_email='nobody@mozilla.org',
        use_deny_list=False,
    )
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.body == s
