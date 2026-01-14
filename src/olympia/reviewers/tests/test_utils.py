import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import call, patch

from django.conf import settings
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage as storage
from django.db import transaction
from django.test.utils import override_settings
from django.urls import reverse

import pytest
import responses
from waffle.testutils import override_switch

from olympia import amo
from olympia.abuse.models import AbuseReport, CinderJob, CinderPolicy, ContentDecision
from olympia.activity import log_create
from olympia.activity.models import (
    ActivityLog,
    ActivityLogToken,
    AttachmentLog,
    CinderPolicyLog,
    ReviewActionReasonLog,
    VersionLog,
)
from olympia.addons.models import Addon, AddonApprovalsCounter, AddonReviewerFlags
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
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.files.models import File
from olympia.lib.crypto.signing import SigningError
from olympia.lib.crypto.tests.test_signing import (
    _get_recommendation_data,
    _get_signature_details,
)
from olympia.promoted.models import (
    PromotedAddon,
    PromotedApproval,
)
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

    def setUp(self):
        super().setUp()

        self.user = UserProfile.objects.get(pk=10482)
        self.addon = Addon.objects.get(pk=3615)
        self.review_version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.review_version.file

        self.create_paths()
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )

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
            channel=getattr(self.review_version, 'channel', amo.CHANNEL_LISTED),
        )

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

    def check_subject(self, msg):
        decision = ContentDecision.objects.first() or ContentDecision(
            addon=self.addon, action=DECISION_ACTIONS.AMO_APPROVE
        )
        assert msg.subject == (
            f'Mozilla Add-ons: Delicious Bookmarks [ref:{decision.get_reference_id()}]'
        )

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
        self.helper.set_data(
            {'action': 'reply', 'comments': 'foo', 'versions': [self.review_version]}
        )
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
            'request_legal_review',
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
            'request_legal_review',
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
            'request_legal_review',
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
            'request_legal_review',
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
            'request_legal_review',
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
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
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
            'request_legal_review',
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
            'request_legal_review',
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
            'request_legal_review',
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
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
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
            'request_legal_review',
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
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
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
            'request_legal_review',
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
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.LINE)
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
        self.addon.promotedaddon.all().delete()
        self.make_addon_promoted(
            self.addon, PROMOTED_GROUP_CHOICES.NOTABLE, approve_version=True
        )
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
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
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.SPOTLIGHT)

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

        # You need admin review permission. Also because it's a promoted add-on
        # despite being admin you don't get the enable/disable auto-approval
        # action.
        self.grant_permission(self.user, 'Reviews:Admin')
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'disable_addon',
            'request_legal_review',
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
            'request_legal_review',
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
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.LINE)
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
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
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
            'request_legal_review',
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
            'request_legal_review',
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
            'request_legal_review',
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
            'request_legal_review',
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
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
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
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
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
        expected = ['reply', 'request_legal_review', 'comment']
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
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'enable_addon',
            'request_legal_review',
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
        expected = [
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]

        self.file.update(status=amo.STATUS_DISABLED)
        self.file.version.update(human_review_date=datetime.now())
        self.addon.update(status=amo.STATUS_NULL)
        actions = list(self.get_helper().actions.keys())
        assert expected == actions

        self.grant_permission(self.user, 'Reviews:Admin')
        expected = [
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
        expected = [
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]
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
        expected = [
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_DELETED,
                file_status=amo.STATUS_DISABLED,
            ).keys()
        )
        assert expected == actions

        self.grant_permission(self.user, 'Reviews:Admin')
        expected = [
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'request_legal_review',
            'comment',
        ]
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_DELETED,
                file_status=amo.STATUS_DISABLED,
            ).keys()
        )
        assert expected == actions

    def test_actions_cinder_jobs_to_resolve(self):
        self.grant_permission(self.user, 'Addons:Review')
        job = CinderJob.objects.create(
            target_addon=self.addon, resolvable_in_reviewer_tools=True
        )
        expected = [
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'resolve_reports_job',
            'request_legal_review',
            'comment',
        ]
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_APPROVED,
                file_status=amo.STATUS_APPROVED,
            ).keys()
        )
        assert expected == actions

        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=self.addon, appeal_job=job
        )
        expected = [
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'resolve_appeal_job',
            'request_legal_review',
            'comment',
        ]
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_APPROVED,
                file_status=amo.STATUS_APPROVED,
            ).keys()
        )
        assert expected == actions

    @override_switch('cinder_policy_review_reasons_enabled', active=True)
    def test_actions_with_use_policies_enabled(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        CinderJob.objects.create(
            target_addon=self.addon, resolvable_in_reviewer_tools=True
        )
        actions = self.get_review_actions(
            addon_status=amo.STATUS_NOMINATED, file_status=amo.STATUS_AWAITING_REVIEW
        )
        assert actions['public']['allows_reasons'] is False
        assert actions['public']['requires_reasons'] is False
        assert actions['public']['requires_reasons_for_cinder_jobs'] is False
        assert actions['public']['enforcement_actions'] == (
            DECISION_ACTIONS.AMO_APPROVE,
        )

        assert actions['reject']['allows_reasons'] is False
        assert actions['reject']['requires_reasons'] is False
        assert actions['reject']['requires_reasons_for_cinder_jobs'] is False
        assert actions['reject']['enforcement_actions'] == (
            DECISION_ACTIONS.AMO_DISABLE_ADDON,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
        )

        assert actions['reject_multiple_versions']['allows_reasons'] is False
        assert actions['reject_multiple_versions']['requires_reasons'] is False
        assert (
            actions['reject_multiple_versions']['requires_reasons_for_cinder_jobs']
            is False
        )
        assert actions['reject_multiple_versions']['enforcement_actions'] == (
            DECISION_ACTIONS.AMO_DISABLE_ADDON,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
        )

        assert actions['disable_addon']['allows_reasons'] is False
        assert actions['disable_addon']['requires_reasons'] is False
        assert actions['disable_addon']['requires_reasons_for_cinder_jobs'] is False
        assert actions['disable_addon']['enforcement_actions'] == (
            DECISION_ACTIONS.AMO_DISABLE_ADDON,
        )

        assert 'allow_reasons' not in actions['resolve_reports_job']
        assert 'requires_reasons' not in actions['resolve_reports_job']
        assert 'requires_reasons_for_cinder_jobs' not in actions['resolve_reports_job']
        assert actions['resolve_reports_job']['enforcement_actions'] == (
            DECISION_ACTIONS.AMO_APPROVE,
            DECISION_ACTIONS.AMO_IGNORE,
            DECISION_ACTIONS.AMO_CLOSED_NO_ACTION,
        )

        self.review_version.update(channel=amo.CHANNEL_UNLISTED)
        actions = self.get_review_actions(
            addon_status=amo.STATUS_NOMINATED, file_status=amo.STATUS_AWAITING_REVIEW
        )
        assert actions['approve_multiple_versions']['allows_reasons'] is False
        assert actions['approve_multiple_versions']['requires_reasons'] is False
        assert (
            actions['approve_multiple_versions']['requires_reasons_for_cinder_jobs']
            is False
        )
        assert actions['approve_multiple_versions']['enforcement_actions'] == (
            DECISION_ACTIONS.AMO_APPROVE,
        )

    def test_actions_auto_approval_disabled(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        expected = [
            'reject_multiple_versions',
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'enable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
            'comment',
        ]
        AddonReviewerFlags.objects.create(addon=self.addon, auto_approval_disabled=True)
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_APPROVED,
                file_status=amo.STATUS_APPROVED,
            ).keys()
        )
        assert expected == actions

        self.make_addon_unlisted(self.addon)
        self.review_version.reload()

    def test_actions_auto_approval_disabled_unlisted(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.make_addon_unlisted(self.addon)
        self.review_version.reload()

        # This doesn't affect unlisted.
        AddonReviewerFlags.objects.create(addon=self.addon, auto_approval_disabled=True)

        expected = [
            'approve_multiple_versions',
            'reject_multiple_versions',
            'unreject_multiple_versions',
            'block_multiple_versions',
            'confirm_multiple_versions',
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            # We're looking at unlisted, so the action that should be available
            # is to disable auto-approval, since it's still enabled for that
            # channel.
            'disable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
            'comment',
        ]
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_APPROVED,
                file_status=amo.STATUS_APPROVED,
            ).keys()
        )
        assert expected == actions

        self.addon.reviewerflags.update(auto_approval_disabled_unlisted=True)

        expected = [
            'approve_multiple_versions',
            'reject_multiple_versions',
            'unreject_multiple_versions',
            'block_multiple_versions',
            'confirm_multiple_versions',
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            # Now it flipped.
            'enable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
            'comment',
        ]
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_APPROVED,
                file_status=amo.STATUS_APPROVED,
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
        assert self.file.status_disabled_reason == File.STATUS_DISABLED_REASONS.NONE
        assert self.file.original_status == amo.STATUS_NULL

    def test_set_file_not_approved(self):
        self.file.update(datestatuschanged=yesterday, status=amo.STATUS_AWAITING_REVIEW)
        self.helper.handler.set_file(amo.STATUS_DISABLED, self.review_version.file)

        assert self.review_version.file.status == amo.STATUS_DISABLED
        assert not self.review_version.file.approval_date
        assert self.file.status_disabled_reason == File.STATUS_DISABLED_REASONS.NONE
        assert self.file.original_status == amo.STATUS_AWAITING_REVIEW

    def test_logs(self):
        self.helper.set_data({'comments': 'something'})
        self.helper.handler.log_action(amo.LOG.APPROVE_VERSION)
        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    def test_record_decision_sets_policies_and_reasons_with_allow_reasons(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.helper = self.get_helper()
        data = {
            'reasons': [
                ReviewActionReason.objects.create(
                    name='reason 1', is_active=True, canned_response='.'
                ),
                ReviewActionReason.objects.create(
                    name='reason 2',
                    is_active=True,
                    cinder_policy=CinderPolicy.objects.create(uuid='y'),
                    canned_response='.',
                ),
            ],
            # ignored - the action doesn't have enforcement_actions set
            'cinder_policies': [
                CinderPolicy.objects.create(uuid='x'),
                CinderPolicy.objects.create(uuid='z'),
            ],
        }
        self.helper.set_data(data)
        self.helper.handler.review_action = self.helper.actions.get('public')
        self.helper.handler.record_decision(amo.LOG.APPROVE_VERSION)
        assert ReviewActionReasonLog.objects.count() == 2
        assert CinderPolicyLog.objects.count() == 1
        assert (
            ActivityLog.objects.get(action=amo.LOG.APPROVE_VERSION.id)
            .contentdecisionlog_set.get()
            .decision.action
            == DECISION_ACTIONS.AMO_APPROVE_VERSION
        )

    @patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_record_decision_sets_policies_with_enforcement_actions(self, report_mock):
        self.grant_permission(self.user, 'Addons:Review')
        cinder_job = CinderJob.objects.create(
            target_addon=self.addon, resolvable_in_reviewer_tools=True
        )
        self.helper = self.get_helper()
        data = {
            # ignored - the action doesn't allow_reasons
            'reasons': [
                ReviewActionReason.objects.create(
                    name='reason 1', is_active=True, canned_response='.'
                ),
                ReviewActionReason.objects.create(
                    name='reason 2',
                    is_active=True,
                    cinder_policy=CinderPolicy.objects.create(uuid='y'),
                    canned_response='.',
                ),
            ],
            'cinder_policies': [
                CinderPolicy.objects.create(uuid='x'),
                CinderPolicy.objects.create(
                    uuid='z',
                    enforcement_actions=[DECISION_ACTIONS.AMO_IGNORE.api_value],
                ),
            ],
            'cinder_jobs_to_resolve': [cinder_job],
        }
        self.helper.set_data(data)
        self.helper.handler.review_action = self.helper.actions.get(
            'resolve_reports_job'
        )
        self.helper.handler.record_decision(amo.LOG.RESOLVE_CINDER_JOB_WITH_NO_ACTION)
        assert ReviewActionReasonLog.objects.count() == 0
        assert CinderPolicyLog.objects.count() == 2
        assert (
            ActivityLog.objects.get(action=amo.LOG.RESOLVE_CINDER_JOB_WITH_NO_ACTION.id)
            .contentdecisionlog_set.get()
            .decision.action
            == DECISION_ACTIONS.AMO_IGNORE
        )
        report_mock.assert_called_once()

    @override_switch('cinder_policy_review_reasons_enabled', active=True)
    def test_record_decision_saves_placeholder_values_for_policies(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.helper = self.get_helper()
        data = {
            # ignored - the action doesn't allow_reasons with the waffle enabled
            'reasons': [
                ReviewActionReason.objects.create(
                    name='reason 1', is_active=True, canned_response='.'
                ),
                ReviewActionReason.objects.create(
                    name='reason 2',
                    is_active=True,
                    cinder_policy=CinderPolicy.objects.create(uuid='y'),
                    canned_response='.',
                ),
            ],
            'cinder_policies': [
                CinderPolicy.objects.create(uuid='xxx'),
                CinderPolicy.objects.create(
                    uuid='zzz',
                    enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
                ),
            ],
            'policy_values': {
                'xxx': {'PLACE1': 'some value', 'PLACE2': 'some other value'},
                'zzz': {'@ "" wierdness': ':shrug:'},
            },
        }
        self.helper.set_data(data)
        self.helper.handler.review_action = self.helper.actions[
            'reject_multiple_versions'
        ]

        self.helper.handler.record_decision(amo.LOG.REJECT_VERSION)
        assert ReviewActionReasonLog.objects.count() == 0
        assert CinderPolicyLog.objects.count() == 2
        decision = (
            ActivityLog.objects.get(action=amo.LOG.REJECT_VERSION.id)
            .contentdecisionlog_set.get()
            .decision
        )
        assert decision.action == DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON
        assert (
            decision.metadata[ContentDecision.POLICY_DYNAMIC_VALUES]
            == data['policy_values']
        )

    @patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_record_decision_sets_policies_with_closed_no_action(self, report_mock):
        self.grant_permission(self.user, 'Addons:Review')
        cinder_job = CinderJob.objects.create(
            target_addon=self.addon, resolvable_in_reviewer_tools=True
        )
        self.helper = self.get_helper()
        data = {
            'cinder_policies': [
                CinderPolicy.objects.create(uuid='x'),
                CinderPolicy.objects.create(
                    uuid='z',
                    enforcement_actions=[
                        DECISION_ACTIONS.AMO_CLOSED_NO_ACTION.api_value
                    ],
                ),
            ],
            'cinder_jobs_to_resolve': [cinder_job],
        }
        self.helper.set_data(data)
        self.helper.handler.review_action = self.helper.actions.get(
            'resolve_reports_job'
        )
        self.helper.handler.record_decision(amo.LOG.RESOLVE_CINDER_JOB_WITH_NO_ACTION)
        assert CinderPolicyLog.objects.count() == 2
        assert (
            ActivityLog.objects.get(action=amo.LOG.RESOLVE_CINDER_JOB_WITH_NO_ACTION.id)
            .contentdecisionlog_set.get()
            .decision.action
            == DECISION_ACTIONS.AMO_CLOSED_NO_ACTION
        )
        report_mock.assert_called_once()

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

    def test_log_action_attachment_input(self):
        assert AttachmentLog.objects.count() == 0
        data = self.get_data()
        text = 'This is input'
        data['attachment_input'] = 'This is input'
        self.helper.set_data(data)
        self.helper.handler.log_action(amo.LOG.REJECT_VERSION)
        assert AttachmentLog.objects.count() == 1
        attachment_log = AttachmentLog.objects.first()
        file_content = attachment_log.file.read().decode('utf-8')
        assert file_content == text

    def test_log_action_attachment_file(self):
        assert AttachmentLog.objects.count() == 0
        text = "I'm a text file"
        data = self.get_data()
        data['attachment_file'] = ContentFile(text, name='attachment.txt')
        self.helper.set_data(data)
        self.helper.handler.log_action(amo.LOG.REJECT_VERSION)
        assert AttachmentLog.objects.count() == 1
        attachment_log = AttachmentLog.objects.first()
        file_content = attachment_log.file.read().decode('utf-8')
        assert file_content == text

    def test_logging_is_similar_in_reviewer_tools_and_content_action(self):
        data = {
            **self.get_data(),
            'action': 'reject_multiple_versions',
            'reasons': [
                ReviewActionReason.objects.create(
                    name='reason 1', is_active=True, canned_response='.'
                ),
                ReviewActionReason.objects.create(
                    name='reason 2',
                    is_active=True,
                    cinder_policy=CinderPolicy.objects.create(uuid='y'),
                    canned_response='.',
                ),
            ],
            'versions': [self.review_version],
        }
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.helper = self.get_helper()
        self.helper.set_data(data)
        self.helper.handler.review_action = self.helper.actions[data['action']]

        # First, record_decision but with the action completed so we log in
        # ReviewHelper - In order to mimic what reject_multiple_versions() does
        # we set self.version and self.file to None first.
        self.helper.handler.file = None
        self.helper.handler.version = None
        self.helper.handler.record_decision(
            amo.LOG.REJECT_VERSION, versions=data['versions']
        )
        logs = ActivityLog.objects.filter(action=amo.LOG.REJECT_VERSION.id)
        assert logs.count() == 1
        reviewer_tools_activity = logs.get()
        decision1 = ContentDecision.objects.last()
        assert self.addon in reviewer_tools_activity.arguments
        assert self.review_version in reviewer_tools_activity.arguments
        assert decision1 in reviewer_tools_activity.arguments
        assert data['reasons'][0] in reviewer_tools_activity.arguments
        assert data['reasons'][1] in reviewer_tools_activity.arguments
        assert data['reasons'][1].cinder_policy in reviewer_tools_activity.arguments

        # then repeat with action_completed=False, which will log in ContentAction
        self.helper.handler.record_decision(
            amo.LOG.REJECT_VERSION, versions=data['versions'], action_completed=False
        )
        logs = ActivityLog.objects.filter(action=amo.LOG.REJECT_VERSION.id).exclude(
            id=reviewer_tools_activity.id
        )
        assert logs.count() == 1
        content_action_activity = logs.get()
        decision2 = ContentDecision.objects.last()

        # and compare... reviewer tools adds an extra `files` too which we
        # ignore.
        expected_details = dict(reviewer_tools_activity.details)
        del expected_details['files']
        assert expected_details == content_action_activity.details
        # reasons won't be in the arguments, because they're added afterwards
        assert set(reviewer_tools_activity.arguments) - {
            decision1,
            *data['reasons'],
        } == set(content_action_activity.arguments) - {decision2}
        # but are present as ReviewActionReasonLog
        query_string = 'reviewactionreasonlog__activity_log__contentdecision__id'
        assert list(
            ReviewActionReason.objects.filter(**{query_string: decision1.id})
        ) == list(ReviewActionReason.objects.filter(**{query_string: decision2.id}))

    @patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_record_decision_calls_report_decision_to_cinder_and_notify_no_jobs(
        self, report_decision_to_cinder_and_notify_spy
    ):
        # Without 'cinder_jobs_to_resolve', report_decision_to_cinder_and_notify the
        # decision created is not linked to any job
        self.helper.set_data(self.get_data())
        self.helper.handler.record_decision(amo.LOG.APPROVE_VERSION)
        decision = ContentDecision.objects.get()
        report_decision_to_cinder_and_notify_spy.assert_called_once_with(
            decision_id=decision.id, notify_owners=True
        )
        assert not decision.cinder_job

    @patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_record_decision_calls_report_decision_to_cinder_and_notify_multiple_jobs(
        self, report_decision_to_cinder_and_notify_spy
    ):
        cinder_job1 = CinderJob.objects.create(job_id='1')
        cinder_job2 = CinderJob.objects.create(job_id='2')

        # With 'cinder_jobs_to_resolve', report_decision_to_cinder_and_notify the
        # decision created is linked to a job
        self.helper.set_data(
            {**self.get_data(), 'cinder_jobs_to_resolve': [cinder_job1, cinder_job2]}
        )
        self.helper.handler.record_decision(amo.LOG.APPROVE_VERSION)

        job_decision1, job_decision2 = ContentDecision.objects.all()
        report_decision_to_cinder_and_notify_spy.assert_has_calls(
            [
                call(decision_id=job_decision1.id, notify_owners=True),
                call(decision_id=job_decision2.id, notify_owners=True),
            ]
        )
        assert job_decision1.cinder_job == cinder_job1
        assert job_decision2.cinder_job == cinder_job2

    @patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_disable_calls_report_decision_to_cinder_and_notify_multiple_jobs(
        self, report_decision_to_cinder_and_notify_spy
    ):
        cinder_job1 = CinderJob.objects.create(job_id='1')
        cinder_job2 = CinderJob.objects.create(job_id='2')

        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.helper.handler.data['cinder_jobs_to_resolve'] = [cinder_job1, cinder_job2]
        self.helper.handler.disable_addon()

        job_decision1, job_decision2 = ContentDecision.objects.all()
        report_decision_to_cinder_and_notify_spy.assert_has_calls(
            [
                call(decision_id=job_decision1.id, notify_owners=True),
                # We don't notify the owners on the second decision since it's
                # going to be the same result.
                call(decision_id=job_decision2.id, notify_owners=False),
            ]
        )
        assert job_decision1.cinder_job == cinder_job1
        assert job_decision2.cinder_job == cinder_job2

        # We record 1 activity, but linked to both decisions.
        assert ActivityLog.objects.filter(action=amo.LOG.FORCE_DISABLE.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.FORCE_DISABLE.id).get()
        assert set(activity.contentdecision_set.all()) == {job_decision1, job_decision2}
        assert activity.arguments == [
            self.addon,
            job_decision2,
            job_decision1,
            self.addon.versions.get(),
        ]

    @patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_reject_multiple_calls_report_decision_to_cinder_and_notify_multiple_jobs(
        self, report_decision_to_cinder_and_notify_spy
    ):
        cinder_job1 = CinderJob.objects.create(job_id='1')
        cinder_job2 = CinderJob.objects.create(job_id='2')

        self.grant_permission(self.user, 'Reviews:Admin')
        version_factory(addon=self.addon)
        extra_version = version_factory(addon=self.addon)
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.helper.handler.data['cinder_jobs_to_resolve'] = [cinder_job1, cinder_job2]
        self.helper.handler.data['versions'] = self.addon.versions.exclude(
            pk=extra_version.pk
        )

        self.helper.handler.reject_multiple_versions()

        job_decision1, job_decision2 = ContentDecision.objects.all()
        report_decision_to_cinder_and_notify_spy.assert_has_calls(
            [
                call(decision_id=job_decision1.id, notify_owners=True),
                # We don't notify the owners on the second decision since it's
                # going to be the same result.
                call(decision_id=job_decision2.id, notify_owners=False),
            ]
        )
        assert job_decision1.cinder_job == cinder_job1
        assert job_decision2.cinder_job == cinder_job2

        # We record 1 activity, but linked to both decisions.
        assert ActivityLog.objects.filter(action=amo.LOG.REJECT_VERSION.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.REJECT_VERSION.id).get()
        assert set(activity.contentdecision_set.all()) == {job_decision1, job_decision2}
        assert activity.arguments == [
            self.addon,
            job_decision2,
            job_decision1,
            *self.addon.versions.exclude(pk=extra_version.pk),
        ]

    def test_send_reviewer_reply(self):
        self.setup_data(amo.STATUS_APPROVED)
        self.helper.handler.data['versions'] = [self.addon.versions.get()]
        self.helper.handler.reviewer_reply()

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.subject == 'Mozilla Add-ons: Delicious Bookmarks 2.1.072'

        assert self.check_log_count(amo.LOG.REVIEWER_REPLY_VERSION.id) == 1

    def test_send_reviewer_reply_multiple_versions(self):
        new_version = version_factory(addon=self.addon, version='3.0')
        new_version2 = version_factory(addon=self.addon, version='3.2')
        self.setup_data(amo.STATUS_APPROVED)
        self.helper.handler.data['versions'] = [new_version, new_version2]
        self.helper.handler.reviewer_reply()

        # Should result in a single activity...
        assert self.check_log_count(amo.LOG.REVIEWER_REPLY_VERSION.id) == 1
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.REVIEWER_REPLY_VERSION.id)
            .get()
        )
        assert [new_version, new_version2] == list(
            vlog.version
            for vlog in activity.versionlog_set.all().order_by('version__pk')
        )

        # ... but 2 emails, because we're sending them version per version.
        assert len(mail.outbox) == 2
        assert mail.outbox[0].subject == 'Mozilla Add-ons: Delicious Bookmarks 3.0'
        assert 'foo' in mail.outbox[0].body
        assert mail.outbox[1].subject == 'Mozilla Add-ons: Delicious Bookmarks 3.2'
        assert 'foo' in mail.outbox[1].body

    def test_email_no_name(self):
        self.addon.name.delete()
        self.addon.refresh_from_db()
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        decision = ContentDecision(
            addon=self.addon, action=DECISION_ACTIONS.AMO_APPROVE
        )
        assert (
            message.subject
            == f'Mozilla Add-ons: None [ref:{decision.get_reference_id()}]'
        )
        assert '/addon/a3615' in message.body

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

        # Make sure we have no public files
        self.review_version.file.update(status=amo.STATUS_AWAITING_REVIEW)

        self.helper.handler.approve_latest_version()

        # Re-fetch the add-on
        addon = Addon.objects.get(pk=3615)

        assert addon.status == amo.STATUS_APPROVED

        assert addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        self.check_subject(message)

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
        NeedsHumanReview.objects.create(
            version=self.review_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.review_version.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.review_version.needshumanreview_set.filter(is_active=True).exists()
        assert (
            not self.review_version.needshumanreview_set.filter(is_active=True)
            .exclude(reason__in=NeedsHumanReview.REASONS.ABUSE_OR_APPEAL_RELATED.values)
            .exists()
        )
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
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert activity.details['human_review'] is False

    def test_unlisted_approve_latest_version_need_human_review(self):
        self.setup_data(
            amo.STATUS_NULL, channel=amo.CHANNEL_UNLISTED, human_review=True
        )
        NeedsHumanReview.objects.create(version=self.review_version)
        NeedsHumanReview.objects.create(
            version=self.review_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval_unlisted=True
        )
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.review_version.reload()
        self.file.reload()
        addon_flags = self.addon.reviewerflags.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED
        assert self.review_version.needshumanreview_set.filter(is_active=True).exists()
        assert (
            not self.review_version.needshumanreview_set.filter(is_active=True)
            .exclude(reason__in=NeedsHumanReview.REASONS.ABUSE_OR_APPEAL_RELATED.values)
            .exists()
        )
        assert not addon_flags.auto_approval_disabled_until_next_approval_unlisted
        assert self.review_version.human_review_date
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert activity.details['human_review'] is True

    def test_unlisted_approve_latest_version_need_human_review_not_human(self):
        self.setup_data(
            amo.STATUS_NULL, channel=amo.CHANNEL_UNLISTED, human_review=False
        )
        NeedsHumanReview.objects.create(version=self.review_version)
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval_unlisted=True
        )
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.review_version.reload()
        self.file.reload()
        addon_flags = self.addon.reviewerflags.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED
        assert self.review_version.needshumanreview_set.filter(is_active=True).exists()
        assert not self.review_version.human_review_date

        # Not changed this this is not a human approval.
        assert addon_flags.auto_approval_disabled_until_next_approval_unlisted
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert activity.details['human_review'] is False

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
            pending_rejection=datetime.now() + timedelta(days=2),
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )

        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()

        flags.refresh_from_db()
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
        self.check_subject(message)
        assert 'has been approved' in message.body

        # AddonApprovalsCounter counter is now at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1

        self.sign_file_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file.path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert activity.details['human_review'] is True

    def test_nomination_but_rejected_to_public(self):
        self.sign_file_mock.reset()
        self.setup_data(amo.STATUS_REJECTED)
        AddonApprovalsCounter.objects.create(
            addon=self.addon, last_content_review_pass=False
        )
        AutoApprovalSummary.objects.update_or_create(
            version=self.review_version,
            defaults={'verdict': amo.AUTO_APPROVED, 'weight': 101},
        )

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_REJECTED
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        self.check_subject(message)
        assert 'remains unavailable ' in message.body

        # AddonApprovalsCounter counter is now at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1
        assert approval_counter.last_content_review_pass is False  # hasn't changed

        self.sign_file_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file.path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert activity.details['human_review'] is True

    def _test_nomination_to_public_not_human(self):
        self.sign_file_mock.reset()

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

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
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert activity.details['human_review'] is False

    def test_nomination_to_public_not_human(self):
        self.setup_data(amo.STATUS_NOMINATED, human_review=False)
        self._test_nomination_to_public_not_human()
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        self.check_subject(message)
        assert 'been automatically screened and tentatively approved' in message.body

    def test_nomination_but_listing_rejected_to_public_not_human(self):
        self.setup_data(amo.STATUS_REJECTED, human_review=False)
        approval_counter = AddonApprovalsCounter.objects.create(
            addon=self.addon, last_content_review_pass=False
        )
        self.sign_file_mock.reset()

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_REJECTED  # no change
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        # AddonApprovalsCounter counter is still at 0 for this addon since there
        # was an automatic approval.
        approval_counter.reload()
        assert approval_counter.counter == 0
        assert approval_counter.last_human_review is None

        self.sign_file_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file.path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id, get_task_user()) == 1

        assert not self.review_version.human_review_date
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert activity.details['human_review'] is False

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        self.check_subject(message)
        assert (
            'been automatically screened and tentatively approved' not in message.body
        )
        assert 'remains unavailable' in message.body

    def test_nomination_to_public_not_human_langpack(self):
        self.setup_data(amo.STATUS_NOMINATED, human_review=False, type=amo.ADDON_LPAPP)
        self._test_nomination_to_public_not_human()
        assert len(mail.outbox) == 0

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
        self.check_subject(message)
        assert 'has been approved' in message.body

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
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert activity.details['human_review'] is True

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
        activity = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        assert activity.details['human_review'] is True

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
        self.check_subject(message)
        assert 'that your content violates the following' in message.body

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
        decision = ContentDecision.objects.get()
        assert activity.arguments == [self.addon, self.review_version, decision]
        assert activity.details['comments'] == ''
        assert activity.details['human_review'] is True
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
        decision = ContentDecision.objects.get()
        assert activity.arguments == [self.addon, self.current_version, decision]
        assert activity.details['comments'] == ''
        assert activity.details['human_review'] is True

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
        decision = ContentDecision.objects.get()
        assert activity.arguments == [self.addon, self.current_version, decision]
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
        decision = ContentDecision.objects.get()
        assert activity.arguments == [self.addon, self.review_version, decision]
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
        self.make_addon_promoted(
            addon=self.addon, group_id=PROMOTED_GROUP_CHOICES.NOTABLE
        )
        self.create_paths()

        # Safeguards.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        self.helper.handler.confirm_auto_approved()

        self.addon.reload()
        assert PROMOTED_GROUP_CHOICES.NOTABLE in self.addon.promoted_groups().group_id

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
        decision = ContentDecision.objects.get()
        assert activity.arguments == [
            self.addon,
            second_unlisted,
            first_unlisted,
            decision,
        ]

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
        self.check_subject(message)
        assert f'Approved versions: {self.review_version.version}' in message.body
        assert 'has been approved' in message.body
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
        self.check_subject(message)
        assert 'your content violates' in message.body

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

    def _test_reject_multiple_versions(self, extra_data, human_review=True):
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=101
        )
        self.setup_data(
            amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED,
            human_review=human_review,
        )

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        self.helper.set_data(
            {**self.get_data(), 'versions': self.addon.versions.all(), **extra_data}
        )
        if human_review:
            self.helper.handler.reject_multiple_versions()
        else:
            self.helper.handler.auto_reject_multiple_versions()

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
            assert version.pending_content_rejection is None
            if human_review:
                assert version.reload().human_review_date
            else:
                assert version.reload().human_review_date is None

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.addon.authors.all()[0].email]
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        if human_review:
            assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1
            assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

            log = (
                ActivityLog.objects.for_addons(self.addon)
                .filter(action=amo.LOG.REJECT_VERSION.id)
                .get()
            )
            decision = ContentDecision.objects.get()
            assert log.arguments == [
                self.addon,
                decision,
                self.review_version,
                old_version,
            ]
            assert decision.metadata == {
                'content_review': False,
            }

            # listed auto approvals should be disabled until the next manual
            # approval.
            flags = self.addon.reviewerflags
            flags.reload()
            assert not flags.auto_approval_disabled_until_next_approval_unlisted
            assert flags.auto_approval_disabled_until_next_approval
        else:
            # For non-human, automatic rejections auto approvals should _not_
            # be disabled until the next manual approval.
            assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
            assert not self.addon.auto_approval_disabled_until_next_approval_unlisted
            assert not self.addon.auto_approval_disabled_until_next_approval

    def test_reject_multiple_versions(self):
        self._test_reject_multiple_versions({})
        message = mail.outbox[0]
        self.check_subject(message)
        assert 'versions of your Extension have been disabled' in message.body
        assert 'received from a third party' not in message.body

    def test_reject_multiple_versions_non_human(self):
        self._test_reject_multiple_versions({}, human_review=False)

    def test_reject_multiple_versions_resolving_abuse_report(self):
        cinder_job = CinderJob.objects.create(job_id='1')
        NeedsHumanReview.objects.create(
            version=self.review_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        AbuseReport.objects.create(guid=self.addon.guid, cinder_job=cinder_job)
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/1/decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )
        self._test_reject_multiple_versions({'cinder_jobs_to_resolve': [cinder_job]})
        message = mail.outbox[0]
        self.check_subject(message)
        assert 'Extension Delicious Bookmarks was manually reviewed' in message.body
        assert 'those versions of your Extension have been disabled' in message.body
        assert 'received from a third party' in message.body
        assert not NeedsHumanReview.objects.filter(is_active=True).exists()

    def _test_reject_multiple_versions_with_delay(self, extra_data):
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=101
        )
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

        in_the_future = datetime.now() + timedelta(days=14, hours=1)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        data = {
            **self.get_data(),
            'versions': self.addon.versions.all(),
            'delayed_rejection': True,
            'delayed_rejection_date': in_the_future,
            **extra_data,
        }
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
        decision = ContentDecision.objects.get()
        assert log.arguments == [self.addon, decision, self.review_version, old_version]
        assert decision.metadata == {
            'content_review': False,
            'delayed_rejection_date': in_the_future.isoformat(),
        }

        # The flag to prevent the authors from being notified several times
        # about pending rejections should have been reset, and auto approvals
        # should have been disabled until the next manual approval.
        flags = self.addon.reviewerflags
        flags.reload()
        assert not flags.notified_about_expiring_delayed_rejections
        assert flags.auto_approval_disabled_until_next_approval

    def test_reject_multiple_versions_with_delay(self):
        self._test_reject_multiple_versions_with_delay({})
        message = mail.outbox[0]
        self.check_subject(message)
        assert 'Your Extension Delicious Bookmarks was manually' in message.body
        assert 'will be disabled' in message.body

    def test_reject_multiple_versions_with_delay_resolving_abuse_reports(self):
        cinder_job = CinderJob.objects.create(job_id='1')
        NeedsHumanReview.objects.create(
            version=self.review_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        AbuseReport.objects.create(guid=self.addon.guid, cinder_job=cinder_job)
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/1/decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )
        self._test_reject_multiple_versions_with_delay(
            {'cinder_jobs_to_resolve': [cinder_job]}
        )
        message = mail.outbox[0]
        self.check_subject(message)
        assert 'Your Extension Delicious Bookmarks was manually' in message.body
        assert 'will be disabled' in message.body
        log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.REJECT_VERSION_DELAYED.id)
            .get()
        )
        assert log.details['delayed_rejection_days'] == 14
        assert set(cinder_job.reload().pending_rejections.all()) == set(
            VersionReviewerFlags.objects.filter(version__in=self.addon.versions.all())
        )
        assert not NeedsHumanReview.objects.filter(is_active=True).exists()

    def test_reject_multiple_versions_except_latest(self):
        old_version = self.review_version
        extra_version = version_factory(addon=self.addon, version='3.1')
        # Add yet another version we don't want to reject.
        self.review_version = version_factory(
            addon=self.addon, version=amo.DEFAULT_WEBEXT_MIN_VERSION
        )
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
        self.check_subject(message)
        assert 'Your Extension Delicious Bookmarks was manually' in message.body
        assert 'versions of your Extension have been disabled' in message.body
        assert 'Affected versions: 2.1.072, 3.1' in message.body
        log_token = ActivityLogToken.objects.filter(version=extra_version).get()
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
        self.check_subject(message)
        assert 'Your Extension Delicious Bookmarks was manually' in message.body
        assert 'have been disabled' in message.body
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 0
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 1

        assert ContentDecision.objects.get().metadata == {
            'content_review': True,
        }

    def test_reject_multiple_versions_content_review_with_delay(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED, content_review=True
        )

        in_the_future = datetime.now() + timedelta(days=14, hours=1)

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
                'delayed_rejection_date': in_the_future,
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
        self.check_subject(message)
        assert 'Your Extension Delicious Bookmarks was manually' in message.body
        assert 'will be disabled' in message.body
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
        decision = ContentDecision.objects.get()
        assert log.arguments == [self.addon, decision, self.review_version, old_version]
        assert decision.metadata == {
            'content_review': True,
            'delayed_rejection_date': in_the_future.isoformat(),
        }

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

    def _approve_multiple_versions_unlisted(self):
        self.make_addon_unlisted(self.addon)
        old_version = self.review_version.reload()
        version_pending_rejection = version_factory(
            addon=self.addon,
            version='2.99',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        VersionReviewerFlags.objects.create(
            version=version_pending_rejection,
            pending_rejection=datetime.now() + timedelta(days=1),
            pending_rejection_by=self.user,
            pending_content_rejection=False,
        )
        self.review_version = version_factory(
            addon=self.addon,
            version='3.0',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.setup_data(
            amo.STATUS_NULL,
            file_status=amo.STATUS_AWAITING_REVIEW,
            channel=amo.CHANNEL_UNLISTED,
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled_until_next_approval=True,
            auto_approval_disabled_until_next_approval_unlisted=True,
        )

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewUnlisted)
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_AWAITING_REVIEW

        expected_versions = [
            self.review_version,
            version_pending_rejection,
            old_version,
        ]
        data = self.get_data().copy()
        data['versions'] = expected_versions
        self.helper.set_data(data)
        self.helper.handler.approve_multiple_versions()
        return expected_versions

    def test_approve_multiple_versions_unlisted_skipped_version_awaiting_review(self):
        wont_be_approved_version = version_factory(
            addon=self.addon,
            version='1.987',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self._approve_multiple_versions_unlisted()
        # This version wasn't part of the version we're approving so it should
        # not have changed status, and shouldn't get a human review date.
        assert wont_be_approved_version.reload().human_review_date is None
        assert (
            wont_be_approved_version.file.reload().status == amo.STATUS_AWAITING_REVIEW
        )

    def test_approve_multiple_versions_unlisted(self):
        expected_versions = self._approve_multiple_versions_unlisted()
        for version in expected_versions:
            version.reload()
            version.file.reload()
            try:
                version.reviewerflags.reload()
            except VersionReviewerFlags.DoesNotExist:
                pass
            assert version.file.status == amo.STATUS_APPROVED
            self.assertCloseToNow(version.human_review_date)
            assert version.pending_rejection is None
            assert version.pending_content_rejection is None
            assert version.pending_rejection_by is None

    def test_approve_multiple_versions_unlisted_flags_activity_logs_and_emails(self):
        expected_versions = self._approve_multiple_versions_unlisted()
        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert self.file.status == amo.STATUS_APPROVED
        # unlisted auto approvals should be enabled again
        flags = self.addon.reviewerflags
        flags.reload()
        assert flags.auto_approval_disabled_until_next_approval
        assert not flags.auto_approval_disabled_until_next_approval_unlisted

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.addon.authors.all()[0].email]
        self.check_subject(message)
        assert 'has been approved' in message.body
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.APPROVE_VERSION.id)
            .get()
        )
        decision = ContentDecision.objects.get()
        assert log.arguments == [
            self.addon,
            *expected_versions,
            decision,
        ]

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
        self.check_subject(message)
        assert 'versions of your Extension have been disabled' in message.body
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        log = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.REJECT_VERSION.id)
            .get()
        )
        decision = ContentDecision.objects.get()
        assert log.arguments == [self.addon, decision, self.review_version, old_version]

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

        in_the_future = datetime.now() + timedelta(days=14, hours=1)

        data = self.get_data().copy()
        data.update(
            {
                'versions': self.addon.versions.all(),
                'delayed_rejection': True,
                'delayed_rejection_date': in_the_future,
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
        decision = ContentDecision.objects.get()
        assert log.arguments == [self.addon, decision, self.review_version, old_version]
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

        self.helper.handler.auto_reject_multiple_versions()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_NULL

        action = (
            amo.LOG.AUTO_REJECT_VERSION_AFTER_DELAY_EXPIRED
            if not content_review
            else amo.LOG.AUTO_REJECT_CONTENT_AFTER_DELAY_EXPIRED
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

    def test_nominated_to_approved_recommended(self):
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert not self.addon.promoted_groups()
        self.test_nomination_to_public()
        assert self.addon.current_version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        assert (
            PROMOTED_GROUP_CHOICES.RECOMMENDED in self.addon.promoted_groups().group_id
        )

    def test_nominated_to_approved_other_promoted(self):
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.LINE)
        assert not self.addon.promoted_groups()
        self.test_nomination_to_public()
        assert self.addon.current_version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.LINE
        ).exists()
        assert PROMOTED_GROUP_CHOICES.LINE in self.addon.promoted_groups().group_id

    def test_approved_update_recommended(self):
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert not self.addon.promoted_groups()
        self.test_public_addon_with_version_awaiting_review_to_public()
        assert self.addon.current_version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        assert (
            PROMOTED_GROUP_CHOICES.RECOMMENDED in self.addon.promoted_groups().group_id
        )

    def test_approved_update_other_promoted(self):
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.LINE)
        assert not self.addon.promoted_groups()
        self.test_public_addon_with_version_awaiting_review_to_public()
        assert self.addon.current_version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.LINE
        ).exists()
        assert PROMOTED_GROUP_CHOICES.LINE in self.addon.promoted_groups().group_id

    def test_autoapprove_fails_for_promoted(self):
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert not self.addon.promoted_groups()
        self.user = UserProfile.objects.get(id=settings.TASK_USER_ID)

        with self.assertRaises(AssertionError):
            self.test_nomination_to_public()
        assert not PromotedApproval.objects.filter(
            version=self.addon.current_version
        ).exists()
        assert not self.addon.promoted_groups()

        # change to other type of promoted; same should happen
        PromotedAddon.objects.filter(addon=self.addon).delete()
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.LINE)
        with self.assertRaises(AssertionError):
            self.test_nomination_to_public()
        assert not PromotedApproval.objects.filter(
            version=self.addon.current_version
        ).exists()
        assert not self.addon.promoted_groups()

        # except for a group that doesn't require prereview
        PromotedAddon.objects.filter(addon=self.addon).delete()
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.STRATEGIC)
        assert PROMOTED_GROUP_CHOICES.STRATEGIC in self.addon.promoted_groups().group_id
        self.test_nomination_to_public()
        # But no PromotedApproval though
        assert not PromotedApproval.objects.filter(
            version=self.addon.current_version
        ).exists()
        assert PROMOTED_GROUP_CHOICES.STRATEGIC in self.addon.promoted_groups().group_id

    def _test_block_multiple_unlisted_versions(self, redirect_url):
        old_version = self.review_version
        self.review_version = version_factory(addon=self.addon, version='3.0')
        NeedsHumanReview.objects.create(version=self.review_version)
        self.setup_data(
            amo.STATUS_NULL,
            file_status=amo.STATUS_APPROVED,
            channel=amo.CHANNEL_UNLISTED,
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

    def test_clear_needs_human_review_multiple_versions_not_abuse(self):
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        NeedsHumanReview.objects.create(version=self.review_version)
        # abuse or appeal related NHR are cleared in ContentDecision so aren't cleared
        NeedsHumanReview.objects.create(
            version=self.review_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )

        data = self.get_data().copy()
        data['versions'] = (
            self.addon.versions(manager='unfiltered_for_relations').all().order_by('pk')
        )
        self.helper.set_data(data)
        self.helper.handler.clear_needs_human_review_multiple_versions()

        log_type_id = amo.LOG.CLEAR_NEEDS_HUMAN_REVIEW.id
        assert self.check_log_count(log_type_id) == 1
        assert ActivityLog.objects.for_addons(self.helper.addon).get(
            action=log_type_id
        ).details.get('versions') == [self.review_version.version]
        assert len(mail.outbox) == 0
        self.review_version.reload()
        assert not self.review_version.human_review_date  # its not been reviewed
        assert self.review_version.needshumanreview_set.filter(is_active=True).exists()
        assert (
            not self.review_version.needshumanreview_set.filter(is_active=True)
            .exclude(reason__in=NeedsHumanReview.REASONS.ABUSE_OR_APPEAL_RELATED.values)
            .exists()
        )
        assert self.review_version.due_date

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
        data['action'] = 'change_or_clear_pending_rejection_multiple_versions'
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

    def test_change_pending_rejection_multiple_versions(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        old_pending_rejection_date = datetime.now() + timedelta(days=1)
        VersionReviewerFlags.objects.create(
            version=self.review_version,
            pending_rejection=old_pending_rejection_date,
            pending_rejection_by=self.user,
            pending_content_rejection=False,
        )
        selected = version_factory(addon=self.review_version.addon)
        VersionReviewerFlags.objects.create(
            version=selected,
            pending_rejection=old_pending_rejection_date,
            pending_rejection_by=self.user,
            pending_content_rejection=True,
        )
        unselected = version_factory(addon=self.review_version.addon)
        VersionReviewerFlags.objects.create(
            version=unselected,
            pending_rejection=old_pending_rejection_date,
            pending_rejection_by=self.user,
            pending_content_rejection=False,
        )
        in_the_future = datetime.now().replace(second=0, microsecond=0) + timedelta(
            days=15
        )
        data = self.get_data().copy()
        data['versions'] = (
            self.addon.versions(manager='unfiltered_for_relations')
            .all()
            .exclude(pk=unselected.pk)
            .order_by('pk')
        )
        data['action'] = 'change_or_clear_pending_rejection_multiple_versions'
        data['delayed_rejection'] = 'True'
        data['delayed_rejection_date'] = in_the_future
        self.helper.set_data(data)
        self.helper.process()

        old_deadline = old_pending_rejection_date.isoformat()[:16]
        new_deadline = in_the_future.isoformat()[:16]
        log_type_id = amo.LOG.CHANGE_PENDING_REJECTION.id
        assert self.check_log_count(log_type_id) == 1
        activity = ActivityLog.objects.for_addons(self.helper.addon).get(
            action=log_type_id
        )
        assert activity.details['comments'] == ''
        assert activity.details['versions'] == [
            self.review_version.version,
            selected.version,
        ]
        assert activity.details['old_deadline'] == old_deadline
        assert activity.details['new_deadline'] == new_deadline
        assert len(mail.outbox) == 1
        assert (
            'Our previous correspondence indicated that you would be required '
            f'to correct the violation(s) by {old_deadline}.'
        ) in mail.outbox[0].body
        assert (
            'will now require you to correct your add-on violations no later '
            f'than {new_deadline}'
        ) in mail.outbox[0].body

        self.review_version.reload()
        self.review_version.reviewerflags.reload()
        assert not self.review_version.human_review_date
        assert self.review_version.reviewerflags.pending_content_rejection is False
        assert self.review_version.reviewerflags.pending_rejection_by == self.user
        assert self.review_version.reviewerflags.pending_rejection == in_the_future

        selected.reload()
        selected.reviewerflags.reload()
        assert not selected.human_review_date
        assert selected.reviewerflags.pending_content_rejection is True
        assert selected.reviewerflags.pending_rejection_by == self.user
        assert selected.reviewerflags.pending_rejection == in_the_future

        unselected.reload()
        unselected.reviewerflags.reload()
        assert not unselected.human_review_date
        assert unselected.reviewerflags.pending_content_rejection is False
        assert unselected.reviewerflags.pending_rejection_by
        assert unselected.reviewerflags.pending_rejection
        assert unselected.reviewerflags.pending_rejection != in_the_future

    def test_disable_addon(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        other_version = version_factory(addon=self.addon)
        version_factory(addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        self.helper.handler.disable_addon()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 1
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.FORCE_DISABLE.id
        assert activity_log.arguments[0] == self.addon
        # FIXME: There is an inconsistency between ReviewHelper.log_action()
        # and ContentAction.log_action() regarding where to put the
        # ContentDecision. See test_enable_addon() for comparison.
        assert isinstance(activity_log.arguments[1], ContentDecision)
        assert activity_log.arguments[2] == other_version
        assert activity_log.arguments[3] == self.review_version
        assert {vlog.version for vlog in activity_log.versionlog_set.all()} == {
            other_version,
            self.review_version,
        }
        assert activity_log.details['versions'] == [
            other_version.version,
            self.review_version.version,
        ]
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        self.check_subject(message)
        assert 'disabled' in message.body

    def test_enable_addon(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        other_version = version_factory(addon=self.addon)
        version_factory(addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        Addon.disable_all_files(
            [self.addon], File.STATUS_DISABLED_REASONS.ADDON_DISABLE
        )

        self.helper.handler.enable_addon()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 1
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.FORCE_ENABLE.id
        assert activity_log.arguments[0] == self.addon
        assert activity_log.arguments[1] == other_version
        assert activity_log.arguments[2] == self.review_version
        assert isinstance(activity_log.arguments[3], ContentDecision)
        assert {vlog.version for vlog in activity_log.versionlog_set.all()} == {
            other_version,
            self.review_version,
        }
        assert activity_log.details['versions'] == [
            other_version.version,
            self.review_version.version,
        ]

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        self.check_subject(message)
        assert 'approved' in message.body

    def test_enable_addon_no_public_versions_should_fall_back_to_incomplete(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_DISABLED, file_status=amo.STATUS_APPROVED)
        self.addon.versions.all().delete()

        self.helper.handler.enable_addon()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert len(mail.outbox) == 1

    def test_enable_addon_version_is_awaiting_review_fall_back_to_nominated(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_DISABLED, file_status=amo.STATUS_AWAITING_REVIEW)

        self.helper.handler.enable_addon()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_NOMINATED
        assert len(mail.outbox) == 1

    def _record_decision_called_everywhere_checkbox_shown(self, actions):
        job, _ = CinderJob.objects.get_or_create(job_id='1234')
        policy, _ = CinderPolicy.objects.get_or_create(
            enforcement_actions=[DECISION_ACTIONS.AMO_APPROVE.api_value]
        )
        self.helper.handler.data = {
            'versions': [self.review_version],
            'cinder_jobs_to_resolve': [job],
            'cinder_policies': [policy],
        }
        all_actions = self.helper.actions
        resolves_actions = {
            key: action
            for key, action in all_actions.items()
            if action.get('resolves_cinder_jobs', False)
        }
        assert list(resolves_actions) == list(actions)

        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': uuid.uuid4().hex},
            status=201,
        )

        # Save current db state, we'll roll back there after each iteration.
        sid = transaction.savepoint()

        with (
            patch(
                'olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay'
            ) as report_task_mock,
            patch.object(
                self.helper.handler, 'log_action', wraps=self.helper.handler.log_action
            ) as reviewer_log_mock,
            patch(
                'olympia.abuse.actions.log_create', wraps=log_create
            ) as content_action_log_spy,
        ):
            for action_name, action in resolves_actions.items():
                self.helper.handler.review_action = all_actions[action_name]
                action['method']()

                decision = ContentDecision.objects.get()
                report_task_mock.assert_called_once_with(
                    decision_id=decision.id, notify_owners=True
                )
                report_task_mock.reset_mock()
                if not actions[action_name].get('uses_content_action', False):
                    reviewer_log_mock.assert_called_once()
                    activity_class = reviewer_log_mock.call_args.args[0]
                    content_action_log_spy.assert_not_called()
                else:
                    content_action_log_spy.assert_called_once()
                    activity_class = content_action_log_spy.call_args[0][0]
                    reviewer_log_mock.assert_not_called()
                assert (
                    getattr(activity_class, 'hide_developer', False)
                    != actions[action_name]['should_email']
                )
                assert (
                    decision.action == actions[action_name]['cinder_action']
                    or policy.enforcement_actions
                )
                assert job.decision == decision

                reviewer_log_mock.reset_mock()
                content_action_log_spy.reset_mock()
                self.helper.handler.version = self.review_version

                # Clean up any changes to start next iteration fresh.
                transaction.savepoint_rollback(sid)

    def test_record_decision_called_everywhere_checkbox_shown_listed(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.grant_permission(self.user, 'Addons:Review')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=42
        )
        CinderJob.objects.create(
            target_addon=self.addon, resolvable_in_reviewer_tools=True
        )
        self.setup_data(amo.STATUS_APPROVED)
        self._record_decision_called_everywhere_checkbox_shown(
            {
                'public': {
                    'should_email': True,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE_VERSION,
                },
                'reject': {
                    'should_email': True,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
                },
                'confirm_auto_approved': {
                    'should_email': False,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE,
                },
                'reject_multiple_versions': {
                    'should_email': True,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
                },
                'disable_addon': {
                    'should_email': True,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_DISABLE_ADDON,
                },
                'resolve_reports_job': {'should_email': False, 'cinder_action': None},
                'request_legal_review': {
                    'should_email': False,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_LEGAL_FORWARD,
                },
            }
        )
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        assert self.addon.status == amo.STATUS_APPROVED
        self._record_decision_called_everywhere_checkbox_shown(
            {
                'confirm_auto_approved': {
                    'should_email': False,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE,
                },
                'reject_multiple_versions': {
                    'should_email': True,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
                },
                'disable_addon': {
                    'should_email': True,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_DISABLE_ADDON,
                },
                'resolve_reports_job': {'should_email': False, 'cinder_action': None},
                'request_legal_review': {
                    'should_email': False,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_LEGAL_FORWARD,
                },
            }
        )
        self.setup_data(amo.STATUS_DISABLED, file_status=amo.STATUS_DISABLED)
        self._record_decision_called_everywhere_checkbox_shown(
            {
                'confirm_auto_approved': {
                    'should_email': False,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE,
                },
                'enable_addon': {
                    'should_email': True,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE_VERSION,
                },
                'resolve_reports_job': {'should_email': False, 'cinder_action': None},
                'request_legal_review': {
                    'should_email': False,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_LEGAL_FORWARD,
                },
            }
        )

    def test_record_decision_called_everywhere_checkbox_shown_unlisted(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED, weight=42
        )
        CinderJob.objects.create(
            target_addon=self.addon, resolvable_in_reviewer_tools=True
        )
        self.setup_data(amo.STATUS_APPROVED, channel=amo.CHANNEL_UNLISTED)
        self._record_decision_called_everywhere_checkbox_shown(
            {
                'public': {
                    'should_email': True,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE_VERSION,
                },
                'approve_multiple_versions': {
                    'should_email': True,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE_VERSION,
                },
                'reject_multiple_versions': {
                    'should_email': True,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
                },
                'confirm_multiple_versions': {
                    'should_email': False,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE,
                },
                'disable_addon': {
                    'should_email': True,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_DISABLE_ADDON,
                },
                'resolve_reports_job': {'should_email': False, 'cinder_action': None},
                'request_legal_review': {
                    'should_email': False,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_LEGAL_FORWARD,
                },
            }
        )
        self.setup_data(amo.STATUS_DISABLED, file_status=amo.STATUS_APPROVED)
        self._record_decision_called_everywhere_checkbox_shown(
            {
                'approve_multiple_versions': {
                    'should_email': True,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE_VERSION,
                },
                'reject_multiple_versions': {
                    'should_email': True,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
                },
                'confirm_multiple_versions': {
                    'should_email': False,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE,
                },
                'enable_addon': {
                    'should_email': True,
                    'cinder_action': DECISION_ACTIONS.AMO_APPROVE_VERSION,
                },
                'resolve_reports_job': {'should_email': False, 'cinder_action': None},
                'request_legal_review': {
                    'should_email': False,
                    'uses_content_action': True,
                    'cinder_action': DECISION_ACTIONS.AMO_LEGAL_FORWARD,
                },
            }
        )

    def test_resolve_appeal_job_policies(self):
        policy_a = CinderPolicy.objects.create(
            uuid='a', text='The {THING} with the {OTHER} thing or {SOMETHING}'
        )
        policy_b = CinderPolicy.objects.create(
            uuid='b', text='The {THING} with this {DUNNO}'
        )
        policy_c = CinderPolicy.objects.create(uuid='c', text='{mmm}.')
        policy_d = CinderPolicy.objects.create(uuid='d')

        appeal_job1 = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job1,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=self.addon,
            metadata={
                ContentDecision.POLICY_DYNAMIC_VALUES: {
                    policy_a.uuid: {'THING': 'la la', 'OTHER': 'da da'},
                    policy_b.uuid: {'THING': 'so so'},
                }
            },
        ).policies.add(policy_a, policy_b)
        ContentDecision.objects.create(
            appeal_job=appeal_job1,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            addon=self.addon,
            metadata={
                ContentDecision.POLICY_DYNAMIC_VALUES: {
                    policy_a.uuid: {'THING': 'laa laa', 'SOMETHING': 'else?'},
                    policy_c.uuid: {'mmm': 'no!'},
                }
            },
        ).policies.add(policy_a, policy_c)
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{appeal_job1.job_id}/decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )

        appeal_job2 = CinderJob.objects.create(
            job_id='2', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job2,
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=self.addon,
        ).policies.add(policy_d)
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{appeal_job2.job_id}/decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )

        self.grant_permission(self.user, 'Addons:Review')
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.helper = self.get_helper()
        data = {
            'comments': 'Nope',
            'cinder_jobs_to_resolve': [appeal_job1, appeal_job2],
            'appeal_action': ['deny'],
        }
        self.helper.set_data(data)

        self.helper.handler.resolve_appeal_job()

        assert CinderPolicyLog.objects.count() == 4
        activity_log_qs = ActivityLog.objects.filter(action=amo.LOG.DENY_APPEAL_JOB.id)
        assert activity_log_qs.count() == 2
        decision_qs = ContentDecision.objects.filter(action_date__isnull=False)
        assert decision_qs.count() == 2
        log2, log1 = list(activity_log_qs.all())
        decision1, decision2 = list(decision_qs.all())
        assert decision1.action == DECISION_ACTIONS.AMO_DISABLE_ADDON
        assert decision2.action == DECISION_ACTIONS.AMO_APPROVE
        assert decision1.activities.get() == log1
        assert decision2.activities.get() == log2
        assert set(appeal_job1.reload().decision.policies.all()) == {
            policy_a,
            policy_b,
            policy_c,
        }
        assert set(appeal_job2.reload().decision.policies.all()) == {policy_d}

        assert decision1.metadata[ContentDecision.POLICY_DYNAMIC_VALUES] == {
            policy_a.uuid: {
                'THING': 'la la | laa laa',
                'OTHER': 'da da',
                'SOMETHING': 'else?',
            },
            policy_b.uuid: {'THING': 'so so'},
            policy_c.uuid: {'mmm': 'no!'},
        }

    def test_resolve_appeal_job_versions(self):
        old_version1 = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED}
        )
        old_version2 = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED}
        )

        appeal_job1 = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job1,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            addon=self.addon,
        ).target_versions.add(old_version1)
        ContentDecision.objects.create(
            appeal_job=appeal_job1,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            addon=self.addon,
        ).target_versions.add(old_version2)
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{appeal_job1.job_id}/decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )

        self.grant_permission(self.user, 'Addons:Review')
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.helper = self.get_helper()
        data = {
            'comments': 'Nope',
            'cinder_jobs_to_resolve': [appeal_job1],
            'appeal_action': ['deny'],
        }
        self.helper.set_data(data)

        self.helper.handler.resolve_appeal_job()

        activity_log_qs = ActivityLog.objects.filter(action=amo.LOG.DENY_APPEAL_JOB.id)
        assert activity_log_qs.count() == 1
        decision_qs = ContentDecision.objects.filter(action_date__isnull=False)
        assert decision_qs.count() == 1
        log1 = activity_log_qs.first()
        decision = decision_qs.first()
        assert decision.action == DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON
        assert decision.activities.get() == log1
        assert list(decision.target_versions.all()) == [old_version2, old_version1]
        assert VersionLog.objects.filter(activity_log=log1).count() == 2
        vl1, vl2 = list(VersionLog.objects.filter(activity_log=log1))
        assert [vl1.version, vl2.version] == [old_version2, old_version1]

    def test_reject_multiple_versions_resets_original_status_too(self):
        old_version = self.review_version
        old_version.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            status_disabled_reason=File.STATUS_DISABLED_REASONS.DEVELOPER,
        )
        self.review_version = version_factory(
            addon=self.addon,
            version='3.0',
            file_kw={
                'status': amo.STATUS_DISABLED,
                'original_status': amo.STATUS_AWAITING_REVIEW,
                'status_disabled_reason': File.STATUS_DISABLED_REASONS.DEVELOPER,
            },
        )
        self.file = self.review_version.file

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        assert self.addon.reload().status == amo.STATUS_NULL

        assert old_version.file.reload().status == amo.STATUS_DISABLED
        assert self.review_version.file.reload().status == amo.STATUS_DISABLED
        assert old_version.file.original_status == amo.STATUS_DISABLED
        assert self.review_version.file.original_status == amo.STATUS_DISABLED
        assert (
            old_version.file.status_disabled_reason == File.STATUS_DISABLED_REASONS.NONE
        )
        assert self.review_version.file.status_disabled_reason == (
            File.STATUS_DISABLED_REASONS.NONE
        )

    def _test_request_legal_review(self, *, data=None):
        self.setup_data(
            amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED,
        )
        if data:
            data = {**self.get_data(), **data}
            self.helper.set_data(data)
        report_request = responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '5678'},
            status=201,
        )
        NeedsHumanReview.objects.create(
            version=self.addon.current_version,
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED,
            is_active=True,
        )
        self.helper.handler.request_legal_review()

        assert len(mail.outbox) == 0
        assert report_request.call_count == 1
        assert CinderJob.objects.get(job_id='5678')
        request_body = json.loads(responses.calls[0].request.body)
        assert (
            request_body['reasoning'] == data['comments']
            if data
            else self.get_data()['comments']
        )
        assert not NeedsHumanReview.objects.filter(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED, is_active=True
        ).exists()

    def test_request_legal_review_no_job(self):
        NeedsHumanReview.objects.create(
            version=self.addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        self._test_request_legal_review()

        # is not cleared
        assert NeedsHumanReview.objects.filter(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION, is_active=True
        ).exists()

    def test_request_legal_review_resolve_job(self):
        # Set up a typical job that would be handled in the reviewer tools
        job = CinderJob.objects.create(
            target_addon=self.addon, resolvable_in_reviewer_tools=True, job_id='1234'
        )
        AbuseReport.objects.create(guid=self.addon.guid, cinder_job=job)
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/1234/decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )
        NeedsHumanReview.objects.create(
            version=self.addon.current_version,
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
        )
        self._test_request_legal_review(data={'cinder_jobs_to_resolve': [job]})

        # And check that the job was resolved in the way we expected
        assert job.reload().decision.action == DECISION_ACTIONS.AMO_LEGAL_FORWARD

        # is cleared
        assert not NeedsHumanReview.objects.filter(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION, is_active=True
        ).exists()

    def _test_single_action_remove_from_queue_history(
        self, review_action, log_action, channel=amo.CHANNEL_LISTED
    ):
        self.setup_data(
            amo.STATUS_APPROVED, channel=channel, file_status=amo.STATUS_AWAITING_REVIEW
        )
        self.review_version.needshumanreview_set.all().delete()
        self.review_version.reviewqueuehistory_set.all().delete()
        if 'multiple' in review_action:
            self.helper.handler.data['versions'] = [self.review_version]
        self.review_version.needshumanreview_set.create()
        self.review_version.reload()
        assert self.review_version.due_date
        original_due_date = self.review_version.due_date
        assert self.review_version.reviewqueuehistory_set.count() == 1
        entry_one = self.review_version.reviewqueuehistory_set.get()
        assert entry_one.original_due_date == original_due_date
        assert not entry_one.exit_date
        assert not entry_one.review_decision_log
        # Manually create extra ReviewQueueHistory: It shouldn't matter, they
        # should only gain an exit_date and review_decision_log if there wasn't
        # one already.
        entry_two = self.review_version.reviewqueuehistory_set.create(
            original_due_date=original_due_date
        )
        old_exit_date = self.days_ago(2)
        entry_already_exited = self.review_version.reviewqueuehistory_set.create(
            original_due_date=original_due_date,
            exit_date=old_exit_date,
        )
        some_old_activity = ActivityLog.objects.create(
            amo.LOG.APPROVE_VERSION, self.review_version, user=self.user
        )
        entry_already_logged = self.review_version.reviewqueuehistory_set.create(
            original_due_date=original_due_date, review_decision_log=some_old_activity
        )

        getattr(self.helper.handler, review_action)()
        log_entry = (
            ActivityLog.objects.exclude(id=some_old_activity.id)
            .filter(action=log_action.id)
            .first()
        )

        assert self.review_version.reviewqueuehistory_set.count() == 4
        # First 2 entries gained an exit date and review decision log.
        for entry in [entry_one, entry_two]:
            entry.reload()
            self.assertCloseToNow(entry.exit_date)
            assert entry.original_due_date == original_due_date
            assert entry.review_decision_log
            assert entry.review_decision_log == log_entry
        # The third one already had an exit date that didn't change.
        entry_already_exited.reload()
        assert entry_already_exited.exit_date == old_exit_date
        assert entry_already_exited.original_due_date == original_due_date
        assert entry_already_exited.review_decision_log == log_entry
        # The fourth one gained an exit date but kept its review decision log.
        entry_already_logged.reload()
        self.assertCloseToNow(entry_already_logged.exit_date)
        assert entry_already_logged.original_due_date == original_due_date
        assert entry_already_logged.review_decision_log == some_old_activity

    def test_actions_remove_from_queue_history(self):
        # Pretend the version was auto-approved in the past, it will allow us
        # to confirm auto-approval later.
        AutoApprovalSummary.objects.create(
            version=self.review_version, verdict=amo.AUTO_APPROVED
        )
        for review_action, activity in (
            ('approve_latest_version', amo.LOG.APPROVE_VERSION),
            ('reject_latest_version', amo.LOG.REJECT_VERSION),
            ('confirm_auto_approved', amo.LOG.CONFIRM_AUTO_APPROVED),
            ('reject_multiple_versions', amo.LOG.REJECT_VERSION),
            ('disable_addon', amo.LOG.FORCE_DISABLE),
            (
                'clear_needs_human_review_multiple_versions',
                amo.LOG.CLEAR_NEEDS_HUMAN_REVIEW,
            ),
        ):
            self._test_single_action_remove_from_queue_history(review_action, activity)

        # Unlisted have actions with custom implementations, check those as
        # well.
        for review_action, activity in (
            ('approve_latest_version', amo.LOG.APPROVE_VERSION),
            ('confirm_auto_approved', amo.LOG.CONFIRM_AUTO_APPROVED),
            ('approve_multiple_versions', amo.LOG.APPROVE_VERSION),
        ):
            self._test_single_action_remove_from_queue_history(
                review_action, activity, channel=amo.CHANNEL_UNLISTED
            )

    def test_non_human_approval_does_not_affect_queue_history(self):
        self.setup_data(
            amo.STATUS_APPROVED,
            file_status=amo.STATUS_AWAITING_REVIEW,
            human_review=False,
        )
        self.review_version.needshumanreview_set.all().delete()
        self.review_version.reviewqueuehistory_set.all().delete()
        self.review_version.needshumanreview_set.create()
        self.review_version.reload()
        assert self.review_version.due_date
        assert self.review_version.reviewqueuehistory_set.count() == 1
        entry = self.review_version.reviewqueuehistory_set.get()
        assert not entry.exit_date
        assert not entry.review_decision_log

        self.helper.handler.approve_latest_version()

        # Since the review wasn't performed by a human, queue history should
        # not have been affected and the NHR should still be there
        assert self.review_version.needshumanreview_set.filter(is_active=True).count()
        entry.reload()
        assert not entry.exit_date
        assert not entry.review_decision_log

    def test_remove_from_queue_history_multiple_versions_cleared(self):
        v2 = version_factory(
            addon=self.addon, version='3.0', file_kw={'is_signed': True}
        )
        v3 = version_factory(
            addon=self.addon, version='4.0', file_kw={'is_signed': True}
        )
        self.review_version.file.update(is_signed=True)
        versions = [v3, v2, self.review_version]
        for v in versions:
            v.needshumanreview_set.create()
            v.reload()
            assert v.due_date
            assert v.reviewqueuehistory_set.count() == 1
            entry = v.reviewqueuehistory_set.get()
            assert entry.original_due_date == v.due_date
            assert not entry.exit_date
            assert not entry.review_decision_log
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.helper.handler.data['versions'] = versions
        self.helper.handler.reject_multiple_versions()
        for v in versions:
            v.reload()
            assert not v.due_date
            assert v.reviewqueuehistory_set.count() == 1
            entry = v.reviewqueuehistory_set.get()
            assert entry.original_due_date
            self.assertCloseToNow(entry.exit_date)
            assert entry.review_decision_log

    def test_enable_auto_approval(self):
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        AddonReviewerFlags.objects.create(addon=self.addon, auto_approval_disabled=True)
        self.helper.handler.enable_auto_approval()
        assert not self.addon.reviewerflags.reload().auto_approval_disabled
        activity_log_qs = ActivityLog.objects.filter(
            action=amo.LOG.ENABLE_AUTO_APPROVAL.id
        )
        assert activity_log_qs.count() == 1
        activity = activity_log_qs.get()
        assert activity.arguments == [self.addon]
        assert activity.details == {
            'channel': amo.CHANNEL_LISTED,
            'comments': 'foo',
            'human_review': True,
        }

    def test_enable_auto_approval_unlisted(self):
        self.setup_data(
            amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED,
            channel=amo.CHANNEL_UNLISTED,
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_unlisted=True
        )
        self.helper.handler.enable_auto_approval()
        assert not self.addon.reviewerflags.reload().auto_approval_disabled_unlisted
        activity_log_qs = ActivityLog.objects.filter(
            action=amo.LOG.ENABLE_AUTO_APPROVAL.id
        )
        assert activity_log_qs.count() == 1
        activity = activity_log_qs.get()
        assert activity.arguments == [self.addon]
        assert activity.details == {
            'channel': amo.CHANNEL_UNLISTED,
            'comments': 'foo',
            'human_review': True,
        }

    def test_disable_auto_approval(self):
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.helper.handler.disable_auto_approval()
        self.addon.reviewerflags.reload()
        assert self.addon.reviewerflags.auto_approval_disabled
        # We only touch the channel the reviewer was looking at.
        assert not self.addon.reviewerflags.auto_approval_disabled_unlisted
        activity_log_qs = ActivityLog.objects.filter(
            action=amo.LOG.DISABLE_AUTO_APPROVAL.id
        )
        assert activity_log_qs.count() == 1
        activity = activity_log_qs.get()
        assert activity.arguments == [self.addon]
        assert activity.details == {
            'channel': amo.CHANNEL_LISTED,
            'comments': 'foo',
            'human_review': True,
        }

    def test_disable_auto_approval_unlisted(self):
        self.setup_data(
            amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED,
            channel=amo.CHANNEL_UNLISTED,
        )
        self.helper.handler.disable_auto_approval()
        self.addon.reviewerflags.reload()
        assert self.addon.reviewerflags.auto_approval_disabled_unlisted
        # We only touch the channel the reviewer was looking at.
        assert not self.addon.reviewerflags.auto_approval_disabled
        activity_log_qs = ActivityLog.objects.filter(
            action=amo.LOG.DISABLE_AUTO_APPROVAL.id
        )
        assert activity_log_qs.count() == 1
        activity = activity_log_qs.get()
        assert activity.arguments == [self.addon]
        assert activity.details == {
            'channel': amo.CHANNEL_UNLISTED,
            'comments': 'foo',
            'human_review': True,
        }


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

        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert not self.addon.promoted_groups()

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        assert self.addon.current_version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        assert (
            PROMOTED_GROUP_CHOICES.RECOMMENDED in self.addon.promoted_groups().group_id
        )

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
