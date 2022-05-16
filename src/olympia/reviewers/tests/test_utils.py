from datetime import datetime, timedelta
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import translation

import pytest
import responses

from olympia import amo
from olympia.activity.models import ActivityLog, ActivityLogToken, ReviewActionReasonLog
from olympia.addons.models import Addon, AddonApprovalsCounter, AddonReviewerFlags
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
    version_review_flags_factory,
)
from olympia.amo.utils import send_mail
from olympia.blocklist.models import Block, BlocklistSubmission
from olympia.constants.promoted import (
    LINE,
    RECOMMENDED,
    SPOTLIGHT,
    STRATEGIC,
    SPONSORED,
)
from olympia.files.models import File
from olympia.lib.crypto.tests.test_signing import (
    _get_recommendation_data,
    _get_signature_details,
)
from olympia.promoted.models import PromotedApproval
from olympia.reviewers.models import (
    AutoApprovalSummary,
    ReviewActionReason,
    ReviewerScore,
    ReviewerSubscription,
)
from olympia.reviewers.utils import (
    ReviewAddon,
    ReviewFiles,
    ReviewHelper,
    ReviewUnlisted,
)
from olympia.users.models import UserProfile
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
        self.version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.version.file

        self.create_paths()

    def _check_score(self, reviewed_type, bonus=0):
        scores = ReviewerScore.objects.all()
        assert len(scores) > 0
        assert scores[0].score == amo.REVIEWED_SCORES[reviewed_type] + bonus
        assert scores[0].note_key == reviewed_type

    def remove_paths(self):
        if self.file.file and not storage.exists(self.file.file_path):
            storage.delete(self.file.file_path)

    def create_paths(self):
        if not storage.exists(self.file.file_path):
            with storage.open(self.file.file_path, 'w') as f:
                f.write('test data\n')
        self.addCleanup(self.remove_paths)

    def setup_data(
        self,
        status,
        file_status=amo.STATUS_AWAITING_REVIEW,
        channel=amo.RELEASE_CHANNEL_LISTED,
        content_review=False,
        type=amo.ADDON_EXTENSION,
        human_review=True,
    ):
        mail.outbox = []
        ActivityLog.objects.for_addons(self.helper.addon).delete()
        self.addon.update(status=status, type=type)
        self.file.update(status=file_status)
        if channel == amo.RELEASE_CHANNEL_UNLISTED:
            self.make_addon_unlisted(self.addon)
            self.version.reload()
            self.file.reload()
        self.helper = self.get_helper(
            content_review=content_review, human_review=human_review
        )
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
            version=self.version,
            user=self.user,
            human_review=human_review,
            content_review=content_review,
        )

    def setup_type(self, status):
        self.addon.update(status=status)
        return self.get_helper().handler.review_type

    def check_log_count(self, id):
        return (
            ActivityLog.objects.for_addons(self.helper.addon).filter(action=id).count()
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
            created=self.version.created - timedelta(days=1),
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
        with self.assertRaises(Exception):
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
            'reply',
            'super',
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
            'reply',
            'super',
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
        expected = ['reject_multiple_versions', 'reply', 'super', 'comment']
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
        expected = ['reject_multiple_versions', 'reply', 'super', 'comment']
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
            'reply',
            'super',
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
        # approve/reject actions.
        self.make_addon_promoted(self.addon, RECOMMENDED)
        expected = ['reply', 'super', 'comment']
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
            'reply',
            'super',
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
            'reply',
            'super',
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
            'reply',
            'super',
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
        """Deleted addons and addons with no versions in that channel have no
        version set."""
        expected = []
        self.version = None
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
        expected = ['reply', 'super', 'comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
                ).keys()
            )
            == expected
        )

        expected = ['reply', 'super', 'comment']
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
            'reply',
            'super',
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
        expected = ['reply', 'super', 'comment']
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
            'reply',
            'super',
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
        expected = ['super', 'comment']
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
            'reply',
            'super',
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
        expected = ['super', 'comment']
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
            'reply',
            'super',
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
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.grant_permission(self.user, 'Addons:Review')
        expected = ['reply', 'super', 'comment']
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
            'reject_multiple_versions',
            'block_multiple_versions',
            'confirm_multiple_versions',
            'reply',
            'super',
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

    def test_actions_version_blocked(self):
        self.grant_permission(self.user, 'Addons:Review')
        # default case
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'reply',
            'super',
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
        block = Block.objects.create(addon=self.addon, updated_by=self.user)
        del self.addon.block
        expected = ['reject', 'reject_multiple_versions', 'reply', 'super', 'comment']
        assert (
            list(
                self.get_review_actions(
                    addon_status=amo.STATUS_APPROVED,
                    file_status=amo.STATUS_AWAITING_REVIEW,
                ).keys()
            )
            == expected
        )

        # it's okay if the version is outside the blocked range though
        block.update(min_version=self.version.version + '.1')
        expected = [
            'public',
            'reject',
            'reject_multiple_versions',
            'reply',
            'super',
            'comment',
        ]
        del self.addon.block

    def test_actions_pending_rejection(self):
        # An addon having its latest version pending rejection won't be
        # reviewable by regular reviewers...
        self.grant_permission(self.user, 'Addons:Review')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        version_review_flags_factory(
            version=self.version, pending_rejection=datetime.now()
        )
        expected = ['reply', 'super', 'comment']
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
            'reply',
            'super',
            'comment',
        ]
        self.version = version_factory(addon=self.addon)
        self.file = self.version.file

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
            version=self.version, pending_rejection=datetime.now()
        )
        expected = [
            'confirm_auto_approved',
            'reject_multiple_versions',
            'reply',
            'super',
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
            'reply',
            'super',
            'comment',
        ]
        self.version = version_factory(addon=self.addon)
        self.file = self.version.file
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
        expected = ['reply', 'super', 'comment']
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

    def test_actions_non_human_reviewer(self):
        # Note that we aren't granting permissions to our user.
        assert not self.user.groups.all()
        expected = ['public', 'reject_multiple_versions']
        actions = list(
            self.get_review_actions(
                addon_status=amo.STATUS_APPROVED,
                file_status=amo.STATUS_AWAITING_REVIEW,
                human_review=False,
            ).keys()
        )
        assert expected == actions

    def test_set_file(self):
        self.file.update(datestatuschanged=yesterday)
        self.helper.handler.set_file(amo.STATUS_APPROVED, self.version.file)

        self.file = self.version.file
        assert self.file.status == amo.STATUS_APPROVED
        assert self.file.datestatuschanged.date() > yesterday.date()

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
        ActivityLogToken.objects.create(version=self.version, user=user)
        uuid = self.version.token.get(user=user).uuid.hex
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
            version=self.version, verdict=amo.AUTO_APPROVED, weight=101
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

        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_nomination_to_public_need_human_review(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.version.update(needs_human_review=True)
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.version.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert not self.version.needs_human_review

    def test_nomination_to_public_need_human_review_not_human(self):
        self.setup_data(amo.STATUS_NOMINATED, human_review=False)
        self.version.update(needs_human_review=True)
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.version.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.version.needs_human_review

    def test_unlisted_approve_latest_version_need_human_review(self):
        self.setup_data(amo.STATUS_NULL, channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.version.update(needs_human_review=True)
        flags = version_review_flags_factory(
            version=self.version,
            needs_human_review_by_mad=True,
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval_unlisted=True
        )
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.version.reload()
        self.file.reload()
        flags.reload()
        addon_flags = self.addon.reviewerflags.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED
        assert not self.version.needs_human_review
        assert not flags.needs_human_review_by_mad
        assert not addon_flags.auto_approval_disabled_until_next_approval_unlisted

    def test_unlisted_approve_latest_version_need_human_review_not_human(self):
        self.setup_data(
            amo.STATUS_NULL, channel=amo.RELEASE_CHANNEL_UNLISTED, human_review=False
        )
        self.version.update(needs_human_review=True)
        flags = version_review_flags_factory(
            version=self.version, needs_human_review_by_mad=True
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval_unlisted=True
        )
        self.helper.handler.approve_latest_version()
        self.addon.reload()
        self.version.reload()
        self.file.reload()
        flags.reload()
        addon_flags = self.addon.reviewerflags.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED
        assert self.version.needs_human_review
        assert flags.needs_human_review_by_mad

        # Not changed this this is not a human approval.
        assert addon_flags.auto_approval_disabled_until_next_approval_unlisted

    def test_nomination_to_public_with_version_reviewer_flags(self):
        flags = version_review_flags_factory(
            version=self.addon.current_version,
            needs_human_review_by_mad=True,
            pending_rejection=datetime.now() + timedelta(days=2),
            pending_rejection_by=user_factory(),
        )
        assert flags.needs_human_review_by_mad

        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()

        flags.refresh_from_db()
        assert not flags.needs_human_review_by_mad
        assert not flags.pending_rejection
        assert not flags.pending_rejection_by

    def test_nomination_to_public(self):
        self.sign_file_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)
        AutoApprovalSummary.objects.update_or_create(
            version=self.version, defaults={'verdict': amo.AUTO_APPROVED, 'weight': 101}
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
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_old_nomination_to_public_bonus_score(self):
        self.sign_file_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED, type=amo.ADDON_PLUGIN)
        self.version.update(nomination=self.days_ago(9))

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
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        # Score has bonus points added for reviewing an old add-on.
        # 2 days over the limit = 4 points
        self._check_score(amo.REVIEWED_ADDON_FULL, bonus=4)

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
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        # No request, no user, therefore no score.
        assert ReviewerScore.objects.count() == 0

    def test_public_addon_with_version_awaiting_review_to_public(self):
        self.sign_file_mock.reset()
        self.addon.current_version.update(created=self.days_ago(1))
        self.version = version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            version='3.0.42',
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'filename': 'webextension.xpi',
            },
        )
        self.preamble = 'Mozilla Add-ons: Delicious Bookmarks 3.0.42'
        self.file = self.version.file
        self.setup_data(amo.STATUS_APPROVED)
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=101
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
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)
        self.addon.reviewerflags.reload()
        assert not self.addon.reviewerflags.auto_approval_disabled_until_next_approval

    def test_public_addon_with_version_need_human_review_to_public(self):
        self.old_version = self.addon.current_version
        self.old_version.update(created=self.days_ago(1), needs_human_review=True)
        self.version = version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            version='3.0.42',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.file = self.version.file
        self.setup_data(amo.STATUS_APPROVED)

        self.helper.handler.approve_latest_version()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)
        self.old_version.reload()
        assert not self.old_version.needs_human_review

    def test_public_addon_with_auto_approval_temporarily_disabled_to_public(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval=True
        )
        self.version = version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            version='3.0.42',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.file = self.version.file
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
        self.version = version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            version='3.0.42',
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'filename': 'webextension.xpi',
            },
        )
        self.preamble = 'Mozilla Add-ons: Delicious Bookmarks 3.0.42'
        self.file = self.version.file
        self.setup_data(amo.STATUS_APPROVED)
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=101
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
        assert storage.exists(self.file.file_path)
        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_public_addon_with_version_need_human_review_to_sandbox(self):
        self.old_version = self.addon.current_version
        self.old_version.update(created=self.days_ago(1), needs_human_review=True)
        self.version = version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            version='3.0.42',
            needs_human_review=True,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.file = self.version.file
        self.setup_data(amo.STATUS_APPROVED)

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
        assert self.addon.current_version.needs_human_review

        self.version.reload()
        assert not self.version.needs_human_review

    def test_public_addon_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        summary = AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=151
        )
        assert summary.confirmed is None
        self.create_paths()

        # Safeguards.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        self.helper.handler.confirm_auto_approved()

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
        assert activity.arguments == [self.addon, self.version]
        assert activity.details['comments'] == ''

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_public_with_unreviewed_version_addon_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.current_version = self.version
        summary = AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=152
        )
        self.version = version_factory(
            addon=self.addon,
            version='3.0',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.file = self.version.file
        self.helper = self.get_helper()  # To make it pick up the new version.
        self.helper.set_data(self.get_data())

        # Confirm approval action should be available even if the latest
        # version is not public, what we care about is the current_version.
        assert 'confirm_auto_approved' in self.helper.actions

        self.helper.handler.confirm_auto_approved()

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

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_public_with_disabled_version_addon_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.current_version = self.version
        summary = AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=153
        )
        self.version = version_factory(
            addon=self.addon, version='3.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        self.file = self.version.file
        self.helper = self.get_helper()  # To make it pick up the new version.
        self.helper.set_data(self.get_data())

        # Confirm approval action should be available even if the latest
        # version is not public, what we care about is the current_version.
        assert 'confirm_auto_approved' in self.helper.actions

        self.helper.handler.confirm_auto_approved()

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

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_addon_with_versions_pending_rejection_confirm_auto_approval(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Reviews:Admin')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.version = version_factory(
            addon=self.addon, version='3.0', file_kw={'status': amo.STATUS_APPROVED}
        )
        self.file = self.version.file
        summary = AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=153
        )

        for version in self.addon.versions.all():
            version_review_flags_factory(
                version=version,
                pending_rejection=datetime.now() + timedelta(days=7),
                pending_rejection_by=user_factory(),
            )

        self.helper = self.get_helper()  # To make it pick up the new version.
        self.helper.set_data(self.get_data())

        # We're an admin, so we can confirm auto approval even if the current
        # version is pending rejection.
        assert 'confirm_auto_approved' in self.helper.actions
        self.helper.handler.confirm_auto_approved()

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
        assert activity.arguments == [self.addon, self.version]
        assert activity.details['comments'] == ''

        # None of the versions should be pending rejection anymore.
        assert not VersionReviewerFlags.objects.filter(
            version__addon=self.addon, pending_rejection__isnull=False
        ).exists()
        # pending_rejection_by should be cleared as well.
        assert not VersionReviewerFlags.objects.filter(
            version__addon=self.addon, pending_rejection_by__isnull=False
        ).exists()

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_addon_with_version_need_human_review_confirm_auto_approval(self):
        self.addon.current_version.update(needs_human_review=True)
        self.test_public_addon_confirm_auto_approval()
        self.addon.current_version.reload()
        assert self.addon.current_version.needs_human_review is False

    def test_addon_with_version_and_scanner_flag_confirm_auto_approvals(self):
        flags = version_review_flags_factory(
            version=self.addon.current_version,
            needs_human_review_by_mad=True,
        )
        assert flags.needs_human_review_by_mad

        self.test_public_addon_confirm_auto_approval()

        flags.refresh_from_db()
        assert not flags.needs_human_review_by_mad

    def test_confirm_multiple_versions_with_version_scanner_flags(self):
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        flags = version_review_flags_factory(
            version=self.version,
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
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            created=self.days_ago(7),
        )
        summary = AutoApprovalSummary.objects.create(
            version=first_unlisted, verdict=amo.AUTO_APPROVED
        )
        second_unlisted = version_factory(
            addon=self.addon,
            version='4.0',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            needs_human_review=True,
            created=self.days_ago(6),
        )
        self.version = version_factory(
            addon=self.addon,
            version='5.0',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            needs_human_review=True,
            created=self.days_ago(5),
        )
        self.file = self.version.file
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

        self.version.reload()
        assert self.version.needs_human_review  # Untouched.

        second_unlisted.reload()
        assert not second_unlisted.needs_human_review  # Cleared.

        assert (
            AddonApprovalsCounter.objects.filter(addon=self.addon).count() == 0
        )  # Not incremented since it was unlisted.

        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 2
        activities = (
            ActivityLog.objects.for_addons(self.addon)
            .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
            .order_by('-pk')
        )
        activity = activities[0]
        assert activity.arguments == [self.addon, first_unlisted]
        activity = activities[1]
        assert activity.arguments == [self.addon, second_unlisted]

    def test_null_to_public_unlisted(self):
        self.sign_file_mock.reset()
        self.setup_data(amo.STATUS_NULL, channel=amo.RELEASE_CHANNEL_UNLISTED)

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
            '%s is now signed and ready for you to download' % self.version.version
            in message.body
        )
        assert 'You received this email because' not in message.body

        self.sign_file_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    def test_nomination_to_public_failed_signing(self):
        self.sign_file_mock.side_effect = Exception
        self.sign_file_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)

        with self.assertRaises(Exception):
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
        assert storage.exists(self.file.file_path)
        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    def test_email_unicode_monster(self):
        self.addon.name = 'TaobaoShopping淘宝网导航按钮'
        self.addon.save()
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.reject_latest_version()
        message = mail.outbox[0]
        assert 'TaobaoShopping淘宝网导航按钮' in message.subject

    def test_nomination_to_super_review(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_code_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_CODE.id) == 1
        # Make sure we used an activity log that has the special `sanitize`
        # property so that comments aren't shown to the developer (a generic
        # message is shown instead)
        assert getattr(amo.LOG.REQUEST_ADMIN_REVIEW_CODE, 'sanitize', '')

    def test_auto_approved_admin_code_review(self):
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_code_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_CODE.id) == 1

    def test_auto_approved_admin_content_review(self):
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED, content_review=True
        )
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_content_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_CONTENT.id) == 1
        assert getattr(amo.LOG.REQUEST_ADMIN_REVIEW_CONTENT, 'sanitize', '')

    def test_auto_approved_admin_theme_review(self):
        self.setup_data(
            amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED,
            type=amo.ADDON_STATICTHEME,
        )
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_theme_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_THEME.id) == 1
        assert getattr(amo.LOG.REQUEST_ADMIN_REVIEW_THEME, 'sanitize', '')

    def test_nomination_to_super_review_and_escalate(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_code_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_CODE.id) == 1

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

    def test_pending_to_super_review(self):
        for status in (amo.STATUS_DISABLED, amo.STATUS_NULL):
            self.setup_data(status)
            self.helper.handler.process_super_review()

            assert self.addon.needs_admin_code_review

    def test_nominated_review_time_set_version_approve_latest_version(self):
        self.version.update(reviewed=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()
        assert self.version.reload().reviewed

    def test_nominated_review_time_set_version_reject_latest_version(self):
        self.version.update(reviewed=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.reject_latest_version()
        assert self.version.reload().reviewed

    def test_nominated_review_time_set_file_approve_latest_version(self):
        self.file.update(reviewed=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.approve_latest_version()
        assert File.objects.get(pk=self.file.pk).reviewed

    def test_nominated_review_time_set_file_reject_latest_version(self):
        self.file.update(reviewed=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.reject_latest_version()
        assert File.objects.get(pk=self.file.pk).reviewed

    def test_review_unlisted_while_a_listed_version_is_awaiting_review(self):
        self.make_addon_unlisted(self.addon)
        self.version.reload()
        version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.addon.update(status=amo.STATUS_NOMINATED)
        assert self.get_helper()

    def test_reject_multiple_versions(self):
        old_version = self.version
        self.version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=101
        )
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

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
        assert list(self.addon.versions.all()) == [self.version, old_version]
        assert self.file.status == amo.STATUS_DISABLED

        # The versions are not pending rejection.
        for version in self.addon.versions.all():
            assert version.pending_rejection is None
            assert version.pending_rejection_by is None

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

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 2
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        logs = ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.REJECT_VERSION.id
        )
        assert logs[0].created == logs[1].created

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

        # listed auto approvals should be disabled until the next manual approval.
        flags = self.addon.reviewerflags
        flags.reload()
        assert not flags.auto_approval_disabled_until_next_approval_unlisted
        assert flags.auto_approval_disabled_until_next_approval

        # The reviewer should have been automatically subscribed to new listed
        # versions.
        assert ReviewerSubscription.objects.filter(
            addon=self.addon, user=self.user, channel=self.version.channel
        ).exists()

    def test_reject_multiple_versions_with_delay(self):
        old_version = self.version
        self.version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=101
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
        assert self.addon.current_version == self.version
        assert list(self.addon.versions.all()) == [self.version, old_version]
        assert self.file.status == amo.STATUS_APPROVED

        # The versions are now pending rejection.
        for version in self.addon.versions.all():
            assert version.pending_rejection
            self.assertCloseToNow(version.pending_rejection, now=in_the_future)
            assert version.pending_rejection_by == self.user

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
        assert self.check_log_count(amo.LOG.REJECT_VERSION_DELAYED.id) == 2

        logs = ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.REJECT_VERSION_DELAYED.id
        )
        assert logs[0].created == logs[1].created

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

        # The flag to prevent the authors from being notified several times
        # about pending rejections should have been reset, and auto approvals
        # should have been disabled until the next manual approval.
        flags = self.addon.reviewerflags
        flags.reload()
        assert not flags.notified_about_expiring_delayed_rejections
        assert flags.auto_approval_disabled_until_next_approval

        # The reviewer should have been automatically subscribed to new listed
        # versions.
        assert ReviewerSubscription.objects.filter(
            addon=self.addon, user=self.user, channel=self.version.channel
        ).exists()

    def test_reject_multiple_versions_except_latest(self):
        old_version = self.version
        extra_version = version_factory(addon=self.addon, version='3.1')
        # Add yet another version we don't want to reject.
        self.version = version_factory(addon=self.addon, version='42.0')
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=91
        )
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all().exclude(pk=self.version.pk)
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        # latest_version is still public so the add-on is still public.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.current_version == self.version
        assert list(self.addon.versions.all().order_by('-pk')) == [
            self.version,
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
        log_token = ActivityLogToken.objects.filter(version=self.version).get()
        assert log_token.uuid.hex in message.reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 2
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_reject_multiple_versions_need_human_review(self):
        old_version = self.version
        old_version.update(needs_human_review=True)
        self.version = version_factory(
            addon=self.addon, version='3.0', needs_human_review=True
        )

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.version, old_version]
        # We rejected all versions so there aren't any left that need human
        # review.
        assert not self.addon.versions.filter(needs_human_review=True).exists()
        assert self.file.status == amo.STATUS_DISABLED

    def test_reject_multiple_versions_content_review(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        old_version = self.version
        self.version = version_factory(addon=self.addon, version='3.0')
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
        assert list(self.addon.versions.all()) == [self.version, old_version]
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
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 2

        # Check points awarded.
        self._check_score(amo.REVIEWED_CONTENT_REVIEW)

    def test_reject_multiple_versions_content_review_with_delay(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        old_version = self.version
        self.version = version_factory(addon=self.addon, version='3.0')
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED, content_review=True
        )

        # Pre-subscribe the user to new listed versions of this add-on, it
        # shouldn't matter.
        ReviewerSubscription.objects.create(
            addon=self.addon, user=self.user, channel=self.version.channel
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
        assert self.addon.current_version == self.version
        assert list(self.addon.versions.all()) == [self.version, old_version]
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
        assert self.check_log_count(amo.LOG.REJECT_CONTENT_DELAYED.id) == 2
        assert self.check_log_count(amo.LOG.REJECT_VERSION_DELAYED.id) == 0

        logs = ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.REJECT_CONTENT_DELAYED.id
        )
        assert logs[0].created == logs[1].created

        # Check points awarded.
        self._check_score(amo.REVIEWED_CONTENT_REVIEW)

        # The reviewer was already subscribed to new listed versions for this
        # addon, nothing has changed.
        assert ReviewerSubscription.objects.filter(
            addon=self.addon, user=self.user, channel=self.version.channel
        ).exists()

    def test_reject_multiple_versions_unlisted(self):
        old_version = self.version
        self.make_addon_unlisted(self.addon)
        self.version = version_factory(
            addon=self.addon,
            version='3.0',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=101
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
        assert list(self.addon.versions.all()) == [self.version, old_version]
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

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 2
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        logs = ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.REJECT_VERSION.id
        )
        assert logs[0].created == logs[1].created

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_reject_multiple_versions_delayed_uses_original_user(self):
        # Do a rejection with delay.
        original_user = self.user
        self.version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=101
        )
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

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

        assert self.check_log_count(amo.LOG.REJECT_VERSION_DELAYED.id) == 2

        # The request user is recorded as scheduling the rejection.
        for log in ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.REJECT_VERSION.id
        ):
            assert log.user == original_user

        # Now reject without delay, running as the task user.
        task_user = UserProfile.objects.get(id=settings.TASK_USER_ID)
        self.user = task_user
        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper = self.get_helper()
        self.helper.set_data(data)

        # Clear our the ActivityLogs.
        ActivityLog.objects.all().delete()

        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_NULL

        # The versions are not pending rejection.
        for version in self.addon.versions.all():
            assert version.pending_rejection is None
            assert version.pending_rejection_by is None

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 2

        # The request user is recorded as scheduling the rejection.
        for log in ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.REJECT_VERSION.id
        ):
            assert log.user == original_user

    def test_approve_content_content_review(self):
        self.grant_permission(self.user, 'Addons:ContentReview')
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED, content_review=True
        )
        summary = AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED
        )
        self.create_paths()

        # Safeguards.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.file.status == (amo.STATUS_APPROVED)

        self.helper.handler.approve_content()

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
        assert activity.arguments == [self.addon, self.version]
        assert activity.details['comments'] == ''

        # Check points awarded.
        self._check_score(amo.REVIEWED_CONTENT_REVIEW)

    def test_dev_versions_url_in_context(self):
        self.helper.set_data(self.get_data())
        context_data = self.helper.handler.get_context_data()
        assert context_data['dev_versions_url'] == absolutify(
            self.addon.get_dev_url('versions')
        )

        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
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
        old_version = self.version
        self.version = version_factory(
            addon=self.addon, version='3.0', needs_human_review=True
        )
        self.setup_data(
            amo.STATUS_NULL,
            file_status=amo.STATUS_APPROVED,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
        )
        # Add a needs_human_review_by_mad flag that should be cleared later.
        version_review_flags_factory(
            version=self.version, needs_human_review_by_mad=True
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
        assert self.addon.versions.filter(needs_human_review=True).exists()
        assert VersionReviewerFlags.objects.filter(
            version__addon=self.addon, needs_human_review_by_mad=True
        ).exists()

        # No mails or logging either
        assert len(mail.outbox) == 0
        assert not ActivityLog.objects.for_addons(self.addon).exists()

        # We should have set redirect_url to point to the Block admin page
        if '%s' in redirect_url:
            redirect_url = redirect_url % (old_version.pk, self.version.pk)
        assert self.helper.redirect_url == redirect_url

    def test_pending_blocklistsubmission_multiple_unlisted_versions(self):
        BlocklistSubmission.objects.create(
            input_guids=self.addon.guid, updated_by=user_factory()
        )
        redirect_url = (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.id,))
            + '?min=%s&max=%s'
        )
        assert Block.objects.count() == 0
        self._test_block_multiple_unlisted_versions(redirect_url)

    def test_new_block_multiple_unlisted_versions(self):
        redirect_url = (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.id,))
            + '?min=%s&max=%s'
        )
        assert Block.objects.count() == 0
        self._test_block_multiple_unlisted_versions(redirect_url)

    def test_existing_block_multiple_unlisted_versions(self):
        Block.objects.create(guid=self.addon.guid, updated_by=user_factory())
        redirect_url = (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.id,))
            + '?min=%s&max=%s'
        )
        self._test_block_multiple_unlisted_versions(redirect_url)

    def test_approve_latest_version_fails_for_blocked_version(self):
        Block.objects.create(addon=self.addon, updated_by=user_factory())
        self.setup_data(amo.STATUS_NOMINATED)
        del self.addon.block

        with self.assertRaises(AssertionError):
            self.helper.handler.approve_latest_version()


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
        self.version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.version.file

    def test_nomination_to_public(self):
        self.setup_data(amo.STATUS_NOMINATED)

        self.helper.handler.approve_latest_version()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].file.status == (amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1

        # AddonApprovalsCounter counter is now at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1

        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        signature_info, manifest = _get_signature_details(self.file.file_path)

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

        signature_info, manifest = _get_signature_details(self.file.file_path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'test@local'
        assert manifest.count('Name: ') == 5

        assert 'Name: index.js' in manifest
        assert 'Name: manifest.json' in manifest
        assert 'Name: META-INF/cose.manifest' in manifest
        assert 'Name: META-INF/cose.sig' in manifest
        assert 'Name: mozilla-recommendation.json' in manifest

        recommendation_data = _get_recommendation_data(self.file.file_path)
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
