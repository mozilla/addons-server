import json
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.db.transaction import atomic
from django.db.utils import IntegrityError

from olympia import amo, core
from olympia.abuse.models import AbuseReport
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import (
    Addon,
    AddonApprovalsCounter,
    AddonReviewerFlags,
    AddonUser,
)
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)
from olympia.blocklist.models import BlockVersion
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.files.models import File, FileValidation, WebextPermission
from olympia.promoted.models import (
    PromotedAddon,
)
from olympia.ratings.models import Rating
from olympia.reviewers.models import (
    AutoApprovalNoValidationResultError,
    AutoApprovalSummary,
    NeedsHumanReview,
    ReviewActionReason,
    ReviewerSubscription,
    UsageTier,
    get_flags,
    send_notifications,
    set_reviewing_cache,
)
from olympia.users.models import UserProfile
from olympia.versions.models import Version, VersionReviewerFlags, version_uploaded
from olympia.zadmin.models import set_config


class TestReviewerSubscription(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super().setUp()
        self.addon = addon_factory(name='SubscribingTest')
        self.listed_version = version_factory(addon=self.addon)
        self.unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )

        self.listed_reviewer = user_factory(email='listed@reviewer')
        self.listed_reviewer_group = Group.objects.create(
            name='Listed Reviewers', rules='Addons:Review'
        )
        GroupUser.objects.create(
            group=self.listed_reviewer_group, user=self.listed_reviewer
        )
        ReviewerSubscription.objects.create(
            addon=self.addon,
            user=self.listed_reviewer,
            channel=amo.CHANNEL_LISTED,
        )

        self.unlisted_reviewer = user_factory(email='unlisted@reviewer')
        self.unlisted_reviewer_group = Group.objects.create(
            name='Unlisted Reviewers', rules='Addons:ReviewUnlisted'
        )
        GroupUser.objects.create(
            group=self.unlisted_reviewer_group, user=self.unlisted_reviewer
        )
        ReviewerSubscription.objects.create(
            addon=self.addon,
            user=self.unlisted_reviewer,
            channel=amo.CHANNEL_UNLISTED,
        )

        self.admin_reviewer = user_factory(email='admin@reviewer')
        GroupUser.objects.create(
            group=self.listed_reviewer_group, user=self.admin_reviewer
        )
        GroupUser.objects.create(
            group=self.unlisted_reviewer_group, user=self.admin_reviewer
        )
        # Don't subscribe admin to updates yet, will be done in tests.

    def test_send_notification(self):
        subscription = ReviewerSubscription.objects.get(user=self.listed_reviewer)
        subscription.send_notification(self.listed_version)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['listed@reviewer']
        assert mail.outbox[0].subject == ('Mozilla Add-ons: SubscribingTest Updated')

    def test_send_notifications(self):
        another_listed_reviewer = user_factory(email='listed2@reviewer')
        GroupUser.objects.create(
            group=self.listed_reviewer_group, user=another_listed_reviewer
        )
        ReviewerSubscription.objects.create(
            addon=self.addon,
            user=another_listed_reviewer,
            channel=amo.CHANNEL_LISTED,
        )

        send_notifications(sender=Version, instance=self.listed_version)
        assert len(mail.outbox) == 2
        emails = sorted(o.to for o in mail.outbox)
        assert emails == [['listed2@reviewer'], ['listed@reviewer']]

    def test_notifications_setting_persists(self):
        send_notifications(Version, self.listed_version)
        assert ReviewerSubscription.objects.count() == 2
        mail.outbox = []
        send_notifications(Version, self.listed_version)
        assert len(mail.outbox) == 1
        mail.outbox = []
        send_notifications(Version, self.unlisted_version)
        assert ReviewerSubscription.objects.count() == 2
        mail.outbox = []
        send_notifications(Version, self.unlisted_version)
        assert len(mail.outbox) == 1

    def test_listed_subscription(self):
        version_uploaded.send(sender=Version, instance=self.listed_version)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['listed@reviewer']
        assert mail.outbox[0].subject == ('Mozilla Add-ons: SubscribingTest Updated')

    def test_unlisted_subscription(self):
        version_uploaded.send(sender=Version, instance=self.unlisted_version)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['unlisted@reviewer']
        assert mail.outbox[0].subject == ('Mozilla Add-ons: SubscribingTest Updated')

    def test_unlisted_subscription_listed_reviewer(self):
        ReviewerSubscription.objects.create(
            addon=self.addon,
            user=self.listed_reviewer,
            channel=amo.CHANNEL_UNLISTED,
        )
        version_uploaded.send(sender=Version, instance=self.unlisted_version)
        # No email should be sent since the reviewer does not have access
        # to unlisted.
        assert len(mail.outbox) == 1
        # Only unlisted@reviewer
        assert mail.outbox[0].to != ['listed@reviewer']

    def test_admin_reviewer_listed_subscription(self):
        ReviewerSubscription.objects.create(
            addon=self.addon,
            user=self.admin_reviewer,
            channel=amo.CHANNEL_LISTED,
        )
        version_uploaded.send(sender=Version, instance=self.listed_version)
        assert len(mail.outbox) == 2
        emails = sorted(o.to for o in mail.outbox)
        assert emails == [['admin@reviewer'], ['listed@reviewer']]

        mail.outbox = []
        version_uploaded.send(sender=Version, instance=self.unlisted_version)
        assert len(mail.outbox) == 1
        # Only unlisted@reviewer
        assert mail.outbox[0].to != ['admin@®reviewer']

    def test_admin_reviewer_unlisted_subscription(self):
        ReviewerSubscription.objects.create(
            addon=self.addon,
            user=self.admin_reviewer,
            channel=amo.CHANNEL_UNLISTED,
        )
        version_uploaded.send(sender=Version, instance=self.unlisted_version)
        assert len(mail.outbox) == 2
        emails = sorted(o.to for o in mail.outbox)
        assert emails == [['admin@reviewer'], ['unlisted@reviewer']]

        mail.outbox = []
        version_uploaded.send(sender=Version, instance=self.listed_version)
        assert len(mail.outbox) == 1
        # Only listed@reviewer
        assert mail.outbox[0].to != ['admin@®reviewer']

    def test_admin_reviewer_both_subscriptions(self):
        ReviewerSubscription.objects.create(
            addon=self.addon,
            user=self.admin_reviewer,
            channel=amo.CHANNEL_LISTED,
        )
        ReviewerSubscription.objects.create(
            addon=self.addon,
            user=self.admin_reviewer,
            channel=amo.CHANNEL_UNLISTED,
        )
        version_uploaded.send(sender=Version, instance=self.listed_version)
        version_uploaded.send(sender=Version, instance=self.unlisted_version)
        assert len(mail.outbox) == 4
        emails = sorted(o.to for o in mail.outbox)
        assert emails == [
            ['admin@reviewer'],
            ['admin@reviewer'],
            ['listed@reviewer'],
            ['unlisted@reviewer'],
        ]

    def test_signal_edit(self):
        self.listed_version.save()
        self.unlisted_version.save()
        assert len(mail.outbox) == 0

    def test_signal_create(self):
        version = version_factory(addon=self.addon)
        version_uploaded.send(sender=Version, instance=version)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == ('Mozilla Add-ons: SubscribingTest Updated')

    def test_signal_create_twice(self):
        version = version_factory(addon=self.addon)
        version_uploaded.send(sender=Version, instance=version)
        mail.outbox = []
        version = version_factory(addon=self.addon)
        version_uploaded.send(sender=Version, instance=version)
        assert len(mail.outbox) == 1

    def test_no_email_for_ex_reviewers(self):
        self.listed_reviewer.delete()
        mail.outbox = []  # deleting the user sends an email for the addon
        # Remove user_one from reviewers.
        GroupUser.objects.get(
            group=self.listed_reviewer_group, user=self.listed_reviewer
        ).delete()
        send_notifications(sender=Version, instance=self.listed_version)
        assert len(mail.outbox) == 0

    def test_no_email_address_for_reviewer(self):
        self.listed_reviewer.update(email=None)
        send_notifications(sender=Version, instance=self.listed_version)
        assert len(mail.outbox) == 0


class TestAutoApprovalSummary(TestCase):
    def setUp(self):
        self.addon = addon_factory(
            average_daily_users=666, version_kw={'version': '1.0'}
        )
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version,
            verdict=amo.AUTO_APPROVED,
            confirmed=True,
        )
        self.current_file_validation = FileValidation.objects.create(
            file=self.addon.current_version.file, validation='{}'
        )
        self.version = version_factory(
            addon=self.addon,
            version='1.1',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.file = self.version.file
        self.file_validation = FileValidation.objects.create(
            file=self.version.file, validation='{}'
        )
        AddonApprovalsCounter.objects.create(addon=self.addon, counter=1)

    def test_negative_weight(self):
        summary = AutoApprovalSummary.objects.create(version=self.version, weight=-300)
        summary = AutoApprovalSummary.objects.get(pk=summary.pk)
        assert summary.weight == -300

    def test_calculate_weight(self):
        summary = AutoApprovalSummary(version=self.version)
        assert summary.weight_info == {}
        weight_info = summary.calculate_weight()
        expected_result = {}
        assert weight_info == expected_result
        assert summary.weight_info == weight_info

    def test_calculate_weight_abuse_reports(self):
        # Extra abuse report for a different add-on, does not count.
        AbuseReport.objects.create(guid=addon_factory().guid)

        # Extra abuse report for a different user, does not count.
        AbuseReport.objects.create(user=user_factory())

        # Extra old abuse report, does not count either.
        old_report = AbuseReport.objects.create(guid=self.addon.guid)
        old_report.update(created=self.days_ago(43))

        # Recent abuse reports.
        AbuseReport.objects.create(guid=self.addon.guid)
        recent_report = AbuseReport.objects.create(guid=self.addon.guid)
        recent_report.update(created=self.days_ago(41))

        # Recent abuse report for one of the developers of the add-on.
        author = user_factory()
        AddonUser.objects.create(addon=self.addon, user=author)
        AbuseReport.objects.create(user=author)

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 45
        assert summary.metadata_weight == 45
        assert summary.code_weight == 0
        assert weight_info['abuse_reports'] == 45

        # Should be capped at 100. We're already at 45, adding 4 more should
        # result in a weight of 100 instead of 105.
        for _i in range(0, 4):
            AbuseReport.objects.create(guid=self.addon.guid)
        weight_info = summary.calculate_weight()
        assert summary.weight == 100
        assert weight_info['abuse_reports'] == 100

    def test_calculate_weight_abuse_reports_use_created_from_instance(self):
        # Create an abuse report 60 days in the past. It should be ignored it
        # we were calculating from today, but use an AutoApprovalSummary
        # instance that is 20 days old, making the abuse report count.
        report = AbuseReport.objects.create(guid=self.addon.guid)
        report.update(created=self.days_ago(60))

        summary = AutoApprovalSummary.objects.create(version=self.version)
        summary.update(created=self.days_ago(20))

        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 15
        assert summary.metadata_weight == 15
        assert summary.code_weight == 0
        assert weight_info['abuse_reports'] == 15

    def test_calculate_weight_negative_ratings(self):
        # Positive rating, does not count.
        Rating.objects.create(
            user=user_factory(), addon=self.addon, version=self.version, rating=5
        )

        # Negative rating, but too old, does not count.
        old_rating = Rating.objects.create(
            user=user_factory(), addon=self.addon, version=self.version, rating=1
        )
        old_rating.update(created=self.days_ago(370))

        # Negative review on a different add-on, does not count either.
        extra_addon = addon_factory()
        Rating.objects.create(
            user=user_factory(),
            addon=extra_addon,
            version=extra_addon.current_version,
            rating=1,
        )

        # Recent negative ratings.
        ratings = [
            Rating(
                user=user_factory(), addon=self.addon, version=self.version, rating=3
            )
            for i in range(0, 49)
        ]
        Rating.objects.bulk_create(ratings)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0  # Not enough negative ratings yet...
        assert summary.metadata_weight == 0
        assert summary.code_weight == 0
        assert weight_info == {}

        # Create one more to get to weight == 1.
        Rating.objects.create(
            user=user_factory(), addon=self.addon, version=self.version, rating=2
        )
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 1
        assert summary.metadata_weight == 1
        assert summary.code_weight == 0
        assert weight_info == {'negative_ratings': 1}

        # Create 5000 more (sorry!) to make sure it's capped at 100.
        ratings = [
            Rating(
                user=user_factory(), addon=self.addon, version=self.version, rating=3
            )
            for i in range(0, 5000)
        ]
        Rating.objects.bulk_create(ratings)

        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert summary.metadata_weight == 100
        assert summary.code_weight == 0
        assert weight_info == {'negative_ratings': 100}

    def test_calculate_weight_reputation(self):
        summary = AutoApprovalSummary(version=self.version)
        self.addon.update(reputation=0)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert summary.metadata_weight == 0
        assert summary.code_weight == 0
        assert weight_info == {}

        self.addon.update(reputation=3)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == -300
        assert summary.metadata_weight == -300
        assert summary.code_weight == 0
        assert weight_info == {'reputation': -300}

        self.addon.update(reputation=1000)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == -300
        assert summary.metadata_weight == -300
        assert summary.code_weight == 0
        assert weight_info == {'reputation': -300}

        self.addon.update(reputation=-1000)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert summary.metadata_weight == 0
        assert summary.code_weight == 0
        assert weight_info == {}

    def test_calculate_weight_average_daily_users(self):
        self.addon.update(average_daily_users=142444)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 14
        assert summary.metadata_weight == 14
        assert summary.code_weight == 0
        assert weight_info == {'average_daily_users': 14}

        self.addon.update(average_daily_users=1756567658)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert summary.metadata_weight == 100
        assert summary.code_weight == 0
        assert weight_info == {'average_daily_users': 100}

    def test_calculate_weight_past_rejection_history(self):
        # Old rejected version, does not count.
        version_factory(
            addon=self.addon,
            human_review_date=self.days_ago(370),
            file_kw={
                'status': amo.STATUS_DISABLED,
            },
        )

        # Version disabled by the developer, not Mozilla
        # (status_disabled_reason is DEVELOPER), does not count.
        version_factory(
            addon=self.addon,
            human_review_date=self.days_ago(15),
            file_kw={
                'status': amo.STATUS_DISABLED,
                'status_disabled_reason': File.STATUS_DISABLED_REASONS.DEVELOPER,
            },
        )

        # Rejected version.
        version_factory(
            addon=self.addon,
            human_review_date=self.days_ago(14),
            file_kw={
                'status': amo.STATUS_DISABLED,
            },
        )

        # Another rejected version
        version_factory(
            addon=self.addon,
            human_review_date=self.days_ago(13),
            file_kw={
                'status': amo.STATUS_DISABLED,
            },
        )

        # Rejected version on a different add-on, does not count.
        version_factory(
            addon=addon_factory(),
            human_review_date=self.days_ago(12),
            file_kw={
                'status': amo.STATUS_DISABLED,
            },
        )

        # Approved version, does not count.
        new_approved_version = version_factory(
            addon=self.addon, human_review_date=self.days_ago(11)
        )
        FileValidation.objects.create(file=new_approved_version.file, validation='{}')

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 20
        assert summary.metadata_weight == 20
        assert summary.code_weight == 0
        assert weight_info == {'past_rejection_history': 20}

        # Should be capped at 100.
        for i in range(0, 10):
            version_factory(
                addon=self.addon,
                version=str(i),
                human_review_date=self.days_ago(10),
                file_kw={'status': amo.STATUS_DISABLED},
            )

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert summary.metadata_weight == 100
        assert summary.code_weight == 0
        assert weight_info == {'past_rejection_history': 100}

    def test_calculate_weight_uses_eval_or_document_write(self):
        validation_data = {
            'messages': [
                {
                    'id': ['DANGEROUS_EVAL'],
                }
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 50
        assert summary.metadata_weight == 0
        assert summary.code_weight == 50
        assert weight_info == {'uses_eval_or_document_write': 50}

        validation_data = {
            'messages': [
                {
                    'id': ['NO_DOCUMENT_WRITE'],
                }
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 50
        assert summary.metadata_weight == 0
        assert summary.code_weight == 50
        assert weight_info == {'uses_eval_or_document_write': 50}

        # Still only 20 if both appear.
        validation_data = {
            'messages': [
                {
                    'id': ['DANGEROUS_EVAL'],
                },
                {
                    'id': ['NO_DOCUMENT_WRITE'],
                },
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 50
        assert summary.metadata_weight == 0
        assert summary.code_weight == 50
        assert weight_info == {'uses_eval_or_document_write': 50}

    def test_calculate_weight_uses_implied_eval(self):
        validation_data = {
            'messages': [
                {
                    'id': ['NO_IMPLIED_EVAL'],
                }
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 5
        assert summary.metadata_weight == 0
        assert summary.code_weight == 5
        assert weight_info == {'uses_implied_eval': 5}

    def test_calculate_weight_uses_innerhtml(self):
        validation_data = {
            'messages': [
                {
                    'id': ['UNSAFE_VAR_ASSIGNMENT'],
                }
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 50
        assert summary.metadata_weight == 0
        assert summary.code_weight == 50
        assert weight_info == {'uses_innerhtml': 50}

    def test_calculate_weight_uses_innerhtml_multiple_times(self):
        validation_data = {
            'messages': [
                {
                    'id': ['UNSAFE_VAR_ASSIGNMENT'],
                },
                {
                    'id': ['IGNORE_ME'],
                },
                {
                    'id': ['UNSAFE_VAR_ASSIGNMENT'],
                },
                {
                    'id': ['UNSAFE_VAR_ASSIGNMENT'],
                },
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        # 50 base, + 10 per additional instance.
        assert summary.weight == 70
        assert summary.metadata_weight == 0
        assert summary.code_weight == 70
        assert weight_info == {'uses_innerhtml': 70}

    def test_calculate_weight_uses_custom_csp(self):
        validation_data = {
            'messages': [
                {
                    'id': ['MANIFEST_CSP'],
                }
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 90
        assert summary.metadata_weight == 0
        assert summary.code_weight == 90
        assert weight_info == {'uses_custom_csp': 90}

    def test_calculate_weight_uses_native_messaging(self):
        WebextPermission.objects.create(file=self.file, permissions=['nativeMessaging'])

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert summary.metadata_weight == 0
        assert summary.code_weight == 100
        assert weight_info == {'uses_native_messaging': 100}

    def test_calculate_weight_uses_remote_scripts(self):
        validation_data = {
            'messages': [
                {
                    'id': ['REMOTE_SCRIPT'],
                }
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert summary.metadata_weight == 0
        assert summary.code_weight == 100
        assert weight_info == {'uses_remote_scripts': 100}

    def test_calculate_weight_violates_mozilla_conditions_of_use(self):
        validation_data = {
            'messages': [
                {
                    'id': ['MOZILLA_COND_OF_USE'],
                }
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 20
        assert summary.metadata_weight == 0
        assert summary.code_weight == 20
        assert weight_info == {'violates_mozilla_conditions': 20}

    def test_calculate_weight_uses_unknown_minified_code_nothing(self):
        validation_data = {
            'metadata': {'unknownMinifiedFiles': []}  # Empty list: no weight.
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert summary.metadata_weight == 0
        assert summary.code_weight == 0
        assert weight_info == {}

        validation_data = {
            'metadata': {
                # Missing property: no weight.
            }
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert summary.metadata_weight == 0
        assert summary.code_weight == 0
        assert weight_info == {}

        validation_data = {
            # Missing metadata: no weight.
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert summary.metadata_weight == 0
        assert summary.code_weight == 0
        assert weight_info == {}

    def test_calculate_weight_uses_unknown_minified_code(self):
        validation_data = {'metadata': {'unknownMinifiedFiles': ['something']}}
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert summary.metadata_weight == 0
        assert summary.code_weight == 100
        assert weight_info == {'uses_unknown_minified_code': 100}

    def test_calculate_weight_uses_unknown_minified_code_multiple_times(self):
        validation_data = {
            'metadata': {'unknownMinifiedFiles': ['something', 'foobar', 'another']}
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        # 100 base, + 20 per additional instance.
        assert summary.weight == 120
        assert summary.metadata_weight == 0
        assert summary.code_weight == 120
        assert weight_info == {'uses_unknown_minified_code': 120}

    def test_calculate_size_of_code_changes_no_current_validation(self):
        # Delete the validation for the previously confirmed version and reload
        # the version we're testing (otherwise the file validation has already
        # been loaded and is still attached to the instance...)
        self.current_file_validation.delete()
        self.version = Version.objects.get(pk=self.version.pk)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 500
        assert summary.metadata_weight == 0
        assert summary.code_weight == 500
        assert weight_info == {'no_validation_result': 500}

    def test_calculate_size_of_code_changes_no_new_validation(self):
        # Delete the validation for the new version and reload that version.
        # (otherwise the file validation has already been loaded and is still
        # attached to the instance...)
        self.file_validation.delete()
        self.version = Version.objects.get(pk=self.version.pk)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 500
        assert summary.metadata_weight == 0
        assert summary.code_weight == 500
        assert weight_info == {'no_validation_result': 500}

    def test_calculate_size_of_code_changes_no_reported_size(self):
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.calculate_size_of_code_changes() == 0
        assert summary.weight == 0
        assert summary.metadata_weight == 0
        assert summary.code_weight == 0
        assert weight_info == {}

    def test_calculate_size_of_code_changes_no_previous_version_size(self):
        validation_data = {
            'metadata': {
                'totalScannedFileSize': 15000,
            }
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        assert summary.calculate_size_of_code_changes() == 15000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 3
        assert summary.metadata_weight == 0
        assert summary.code_weight == 3
        assert weight_info == {'size_of_code_changes': 3}

    def test_calculate_size_of_code_changes(self):
        old_validation_data = {
            'metadata': {
                'totalScannedFileSize': 5000,
            }
        }
        self.current_file_validation.update(validation=json.dumps(old_validation_data))
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 15000,
            }
        }
        self.file_validation.update(validation=json.dumps(new_validation_data))
        summary = AutoApprovalSummary(version=self.version)
        assert summary.calculate_size_of_code_changes() == 10000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 2
        assert summary.metadata_weight == 0
        assert summary.code_weight == 2
        assert weight_info == {'size_of_code_changes': 2}

    def test_calculate_size_of_code_change_use_previously_confirmed(self):
        old_validation_data = {
            'metadata': {
                'totalScannedFileSize': 5000,
            }
        }
        self.current_file_validation.update(validation=json.dumps(old_validation_data))
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 15000,
            }
        }
        self.file_validation.update(validation=json.dumps(new_validation_data))

        # Add a new current_version, unconfirmed. This version will be ignored
        # for the comparison as all we care about is the previous confirmed
        # version.
        self.addon.current_version.update(created=self.days_ago(2))
        new_version = version_factory(addon=self.addon)
        self.addon.reload()
        assert self.addon.current_version == new_version
        AutoApprovalSummary.objects.create(
            version=new_version, verdict=amo.AUTO_APPROVED
        )
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 14999,
            }
        }
        FileValidation.objects.create(
            file=new_version.file, validation=json.dumps(new_validation_data)
        )

        summary = AutoApprovalSummary(version=self.version)
        # Size of code changes should be 10000 and not 1, proving that it
        # compared with the old, confirmed version.
        assert summary.calculate_size_of_code_changes() == 10000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 2
        assert summary.metadata_weight == 0
        assert summary.code_weight == 2
        assert weight_info == {'size_of_code_changes': 2}

    def test_calculate_size_of_code_changes_no_negative(self):
        old_validation_data = {
            'metadata': {
                'totalScannedFileSize': 20000,
            }
        }
        self.current_file_validation.update(validation=json.dumps(old_validation_data))
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 5000,
            }
        }
        self.file_validation.update(validation=json.dumps(new_validation_data))
        summary = AutoApprovalSummary(version=self.version)
        assert summary.calculate_size_of_code_changes() == 15000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 3
        assert summary.metadata_weight == 0
        assert summary.code_weight == 3
        assert weight_info == {'size_of_code_changes': 3}

    def test_calculate_size_of_code_changes_max(self):
        old_validation_data = {
            'metadata': {
                'totalScannedFileSize': 50000000,
            }
        }
        self.current_file_validation.update(validation=json.dumps(old_validation_data))
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 0,
            }
        }
        self.file_validation.update(validation=json.dumps(new_validation_data))
        summary = AutoApprovalSummary(version=self.version)
        assert summary.calculate_size_of_code_changes() == 50000000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert summary.metadata_weight == 0
        assert summary.code_weight == 100
        assert weight_info == {'size_of_code_changes': 100}

    def test_calculate_weight_sum(self):
        validation_data = {
            'messages': [
                {'id': ['MANIFEST_CSP']},
                {'id': ['UNSAFE_VAR_ASSIGNMENT']},
                {'id': ['NO_IMPLIED_EVAL']},
                {'id': ['DANGEROUS_EVAL']},
                {'id': ['UNSAFE_VAR_ASSIGNMENT']},  # Another one.
                {'id': ['NOTHING_TO_SEE_HERE_MOVE_ON']},
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.metadata_weight == 0
        assert summary.code_weight == 205
        assert summary.weight == 205
        expected_result = {
            'uses_custom_csp': 90,
            'uses_eval_or_document_write': 50,
            'uses_implied_eval': 5,
            'uses_innerhtml': 60,  # There is one extra.
        }
        assert weight_info == expected_result

    def test_count_uses_custom_csp(self):
        assert AutoApprovalSummary.count_uses_custom_csp(self.version) == 0

        validation_data = {
            'messages': [
                {
                    'id': ['MANIFEST_CSP'],
                }
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        assert AutoApprovalSummary.count_uses_custom_csp(self.version) == 1

    def test_count_uses_custom_csp_file_validation_missing(self):
        self.file_validation.delete()
        self.version.file.refresh_from_db()
        with self.assertRaises(AutoApprovalNoValidationResultError):
            AutoApprovalSummary.count_uses_custom_csp(self.version)

    def test_check_uses_native_messaging(self):
        assert AutoApprovalSummary.check_uses_native_messaging(self.version) == 0

        webext_permissions = WebextPermission.objects.create(
            file=self.file, permissions=['foobar']
        )
        del self.file.permissions
        assert AutoApprovalSummary.check_uses_native_messaging(self.version) == 0

        webext_permissions.update(permissions=['nativeMessaging', 'foobar'])
        del self.file.permissions
        assert AutoApprovalSummary.check_uses_native_messaging(self.version) == 1

    def test_calculate_weight_uses_coinminer(self):
        validation_data = {
            'messages': [
                {
                    'id': ['COINMINER_USAGE_DETECTED'],
                }
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 2000
        assert weight_info['uses_coinminer'] == 2000

    def test_get_pretty_weight_info(self):
        summary = AutoApprovalSummary(version=self.version)
        assert summary.weight_info == {}
        pretty_weight_info = summary.get_pretty_weight_info()
        assert pretty_weight_info == ['Weight breakdown not available.']

        summary.weight_info = {
            'key1': 666,
            'key2': None,
            'key3': 0,
            'key4': -1,
        }
        pretty_weight_info = summary.get_pretty_weight_info()
        assert pretty_weight_info == ['key1: 666', 'key4: -1']

    def test_check_has_auto_approval_disabled(self):
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags = AddonReviewerFlags.objects.create(addon=self.addon)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags.update(auto_approval_disabled=True)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is True
        )

        # The auto_approval_disabled flag only applies to listed.
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

    def test_check_has_auto_approval_disabled_unlisted(self):
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags = AddonReviewerFlags.objects.create(addon=self.addon)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags.update(auto_approval_disabled_unlisted=True)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is True
        )

        # The auto_approval_disabled_unlisted flag only applies to unlisted.
        self.version.update(channel=amo.CHANNEL_LISTED)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

    def test_check_has_auto_approval_disabled_until_next_approval(self):
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags = AddonReviewerFlags.objects.create(addon=self.addon)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags.update(auto_approval_disabled_until_next_approval=True)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is True
        )

        # That flag only applies to listed.
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

    def test_check_has_auto_approval_disabled_until_next_approval_unlisted(self):
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags = AddonReviewerFlags.objects.create(addon=self.addon)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags.update(auto_approval_disabled_until_next_approval_unlisted=True)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is True
        )
        # That flag only applies to unlisted.
        self.version.update(channel=amo.CHANNEL_LISTED)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

    def test_check_has_auto_approval_delayed_until(self):
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags = AddonReviewerFlags.objects.create(addon=self.addon)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        past_date = datetime.now() - timedelta(hours=1)
        flags.update(auto_approval_delayed_until=past_date)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        future_date = datetime.now() + timedelta(hours=1)
        flags.update(auto_approval_delayed_until=future_date)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is True
        )

        # That flag only applies to listed.
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

    def test_check_has_auto_approval_delayed_until_unlisted(self):
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        flags = AddonReviewerFlags.objects.create(addon=self.addon)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        past_date = datetime.now() - timedelta(hours=1)
        flags.update(auto_approval_delayed_until_unlisted=past_date)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

        future_date = datetime.now() + timedelta(hours=1)
        flags.update(auto_approval_delayed_until_unlisted=future_date)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is True
        )

        # That flag only applies to unlisted.
        self.version.update(channel=amo.CHANNEL_LISTED)
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

    def test_check_is_promoted_prereview(self):
        assert AutoApprovalSummary.check_is_promoted_prereview(self.version) is False

        assert AutoApprovalSummary.check_is_promoted_prereview(self.version) is False

        self.make_addon_promoted(
            addon=self.addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        assert AutoApprovalSummary.check_is_promoted_prereview(self.version) is True

        PromotedAddon.objects.filter(addon=self.addon).delete()
        self.make_addon_promoted(
            addon=self.addon, group_id=PROMOTED_GROUP_CHOICES.STRATEGIC
        )  # STRATEGIC isn't prereview
        assert AutoApprovalSummary.check_is_promoted_prereview(self.version) is False

        PromotedAddon.objects.filter(addon=self.addon).delete()
        self.make_addon_promoted(
            addon=self.addon, group_id=PROMOTED_GROUP_CHOICES.LINE
        )  # LINE is though
        assert AutoApprovalSummary.check_is_promoted_prereview(self.version) is True

        self.version.update(channel=amo.CHANNEL_UNLISTED)  # not for unlisted though
        assert AutoApprovalSummary.check_is_promoted_prereview(self.version) is False

        PromotedAddon.objects.filter(addon=self.addon).delete()
        self.make_addon_promoted(
            addon=self.addon, group_id=PROMOTED_GROUP_CHOICES.NOTABLE
        )  # NOTABLE is
        assert AutoApprovalSummary.check_is_promoted_prereview(self.version) is True

        self.version.update(channel=amo.CHANNEL_LISTED)  # and for listed too
        assert AutoApprovalSummary.check_is_promoted_prereview(self.version) is True

    def test_check_should_be_delayed(self):
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False

        # Delete current_version, making self.version the first listed version
        # submitted and add-on creation date recent.
        self.addon.current_version.delete()
        self.addon.update(created=datetime.now())
        self.addon.update_status()

        # First test - the version was created recently so it should be delayed.
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is True

        # Update the creation date so it's old enough to be not delayed.
        self.version.update(created=datetime.now() - timedelta(hours=24, seconds=1))
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False

        # Unlisted shouldn't be affected.
        self.version.update(
            created=datetime.now() - timedelta(hours=22),
            channel=amo.CHANNEL_UNLISTED,
        )
        assert (
            AutoApprovalSummary.check_has_auto_approval_disabled(self.version) is False
        )

    def test_check_should_be_delayed_dynamic(self):
        # The delay defaults to 24 hours (see test above) but can be configured
        # by admins.
        target_delay = 666
        set_config('INITIAL_AUTO_APPROVAL_DELAY_FOR_LISTED', target_delay)
        # Delete current_version, making self.version the first listed version
        # submitted and add-on creation date recent.
        self.addon.current_version.delete()
        self.addon.update(created=datetime.now())
        self.addon.update_status()
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is True

        self.version.update(
            created=datetime.now() - timedelta(seconds=target_delay - 1)
        )
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is True
        self.version.update(
            created=datetime.now() - timedelta(seconds=target_delay + 1)
        )
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False

        # Goes back to 24 hours if the value is invalid.
        set_config('INITIAL_AUTO_APPROVAL_DELAY_FOR_LISTED', 'nonsense')
        self.version.update(created=datetime.now() - timedelta(hours=23, seconds=1))
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is True
        self.version.update(created=datetime.now() - timedelta(hours=24, seconds=1))
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False

    def test_check_should_be_delayed_only_until_first_content_review(self):
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False

        # Delete current_version, making self.version the first listed version
        # submitted and add-on creation date recent.
        self.addon.current_version.delete()
        self.addon.update(created=datetime.now())
        self.addon.update_status()

        # Also remove AddonApprovalsCounter to start fresh.
        self.addon.addonapprovalscounter.delete()

        # Set a recent created date. It should be delayed.
        self.version.update(created=datetime.now() - timedelta(hours=12))
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is True

        # Add AddonApprovalsCounter with default values, it should still be
        # delayed.
        self.addon.addonapprovalscounter = AddonApprovalsCounter.objects.create(
            addon=self.addon
        )
        assert self.addon.addonapprovalscounter.last_content_review is None
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is True

        # Once there is a content review, it should no longer be delayed.
        self.addon.addonapprovalscounter.update(last_content_review=datetime.now())
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False

    def test_check_should_be_delayed_langpacks_are_exempted(self):
        self.addon.update(type=amo.ADDON_LPAPP)
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False

        # Delete current_version, making self.version the first listed version
        # submitted and add-on creation date recent.
        self.addon.current_version.delete()
        self.addon.update(created=datetime.now())
        self.addon.update_status()

        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False
        self.addon.update(created=self.days_ago(2))
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False
        self.version.update(created=datetime.now() - timedelta(hours=22))
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False
        self.version.update(created=self.days_ago(2))
        assert AutoApprovalSummary.check_should_be_delayed(self.version) is False

    def test_check_is_blocked(self):
        assert AutoApprovalSummary.check_is_blocked(self.version) is False

        block_factory(
            addon=self.addon, updated_by=user_factory(), version_ids=[self.version.id]
        )
        self.version.refresh_from_db()
        assert AutoApprovalSummary.check_is_blocked(self.version) is True

        BlockVersion.objects.get().update(
            version=version_factory(addon=self.version.addon)
        )
        self.version.refresh_from_db()
        assert AutoApprovalSummary.check_is_blocked(self.version) is False

    def test_check_is_locked(self):
        assert AutoApprovalSummary.check_is_locked(self.version) is False

        set_reviewing_cache(self.version.addon.pk, settings.TASK_USER_ID)
        assert AutoApprovalSummary.check_is_locked(self.version) is False

        set_reviewing_cache(self.version.addon.pk, settings.TASK_USER_ID + 42)
        assert AutoApprovalSummary.check_is_locked(self.version) is True

        # Langpacks are never considered locked.
        self.addon.update(type=amo.ADDON_LPAPP)
        assert AutoApprovalSummary.check_is_locked(self.version) is False

    def test_check_is_pending_rejection(self):
        assert AutoApprovalSummary.check_is_pending_rejection(self.version) is False

        flags = VersionReviewerFlags.objects.create(version=self.version)
        assert AutoApprovalSummary.check_is_pending_rejection(self.version) is False

        flags.update(
            pending_rejection=datetime.now() + timedelta(hours=1),
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )
        assert AutoApprovalSummary.check_is_pending_rejection(self.version) is True

        flags.update(pending_content_rejection=True)
        assert AutoApprovalSummary.check_is_pending_rejection(self.version) is True

    @mock.patch.object(AutoApprovalSummary, 'calculate_weight', spec=True)
    @mock.patch.object(AutoApprovalSummary, 'calculate_verdict', spec=True)
    def test_create_summary_for_version(
        self, calculate_verdict_mock, calculate_weight_mock
    ):
        def create_dynamic_patch(name):
            patcher = mock.patch.object(
                AutoApprovalSummary, name, spec=getattr(AutoApprovalSummary, name)
            )
            thing = patcher.start()
            thing.return_value = False
            self.addCleanup(patcher.stop)
            return thing

        calculate_verdict_mock.return_value = {'dummy_verdict': True}
        dynamic_mocks = [
            create_dynamic_patch(f'check_{field}')
            for field in AutoApprovalSummary.auto_approval_verdict_fields
        ]

        summary, info = AutoApprovalSummary.create_summary_for_version(
            self.version,
        )

        for mocked_method in dynamic_mocks:
            assert mocked_method.call_count == 1
            mocked_method.assert_called_with(self.version)
        assert calculate_weight_mock.call_count == 1
        assert calculate_verdict_mock.call_count == 1
        assert calculate_verdict_mock.call_args == (
            {
                'dry_run': False,
            },
        )
        assert summary.pk
        assert summary.version == self.version
        assert info == {'dummy_verdict': True}

    def test_create_summary_for_version_no_mocks(self):
        self.addon.update(average_daily_users=1000000)
        AddonReviewerFlags.objects.create(addon=self.addon)
        self.file_validation.update(
            validation=json.dumps(
                {
                    'messages': [
                        {'id': ['DANGEROUS_EVAL']},
                    ]
                }
            )
        )
        summary, info = AutoApprovalSummary.create_summary_for_version(
            self.version,
        )
        assert summary.verdict == amo.AUTO_APPROVED
        assert summary.weight == 150
        assert summary.code_weight == 50
        assert summary.metadata_weight == 100
        assert summary.weight_info == {
            'average_daily_users': 100,
            'uses_eval_or_document_write': 50,
        }

    @mock.patch.object(AutoApprovalSummary, 'calculate_verdict', spec=True)
    def test_create_summary_no_previously_approved_versions(
        self, calculate_verdict_mock
    ):
        AddonApprovalsCounter.objects.all().delete()
        self.version.reload()
        calculate_verdict_mock.return_value = {'dummy_verdict': True}
        summary, info = AutoApprovalSummary.create_summary_for_version(self.version)
        assert summary.pk
        assert info == {'dummy_verdict': True}

    def test_create_summary_already_existing(self):
        # Create a dummy summary manually, then call the method to create a
        # real one. It should have just updated the previous instance.
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_locked=True
        )
        assert summary.pk
        assert summary.version == self.version
        assert summary.verdict == amo.NOT_AUTO_APPROVED

        previous_summary_pk = summary.pk

        summary, info = AutoApprovalSummary.create_summary_for_version(self.version)

        assert summary.pk == previous_summary_pk
        assert summary.version == self.version
        assert summary.is_locked is False
        assert summary.verdict == amo.AUTO_APPROVED
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
            'is_pending_rejection': False,
        }

    def test_calculate_verdict_failure_dry_run(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_locked=True
        )
        info = summary.calculate_verdict(dry_run=True)
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': True,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
            'is_pending_rejection': False,
        }
        assert summary.verdict == amo.WOULD_NOT_HAVE_BEEN_AUTO_APPROVED

    def test_calculate_verdict_failure(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_locked=True
        )
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': True,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
            'is_pending_rejection': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_calculate_verdict_success(self):
        summary = AutoApprovalSummary.objects.create(version=self.version)
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
            'is_pending_rejection': False,
        }
        assert summary.verdict == amo.AUTO_APPROVED

    def test_calculate_verdict_success_dry_run(self):
        summary = AutoApprovalSummary.objects.create(version=self.version)
        info = summary.calculate_verdict(dry_run=True)
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
            'is_pending_rejection': False,
        }
        assert summary.verdict == amo.WOULD_HAVE_BEEN_AUTO_APPROVED

    def test_calculate_verdict_has_auto_approval_disabled(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, has_auto_approval_disabled=True
        )
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': True,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
            'is_pending_rejection': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_calculate_verdict_is_promoted_prereview(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_promoted_prereview=True
        )
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': True,
            'should_be_delayed': False,
            'is_blocked': False,
            'is_pending_rejection': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_calculate_verdict_is_blocked(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_blocked=True
        )
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': True,
            'is_pending_rejection': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_calculate_verdict_should_be_delayed(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, should_be_delayed=True
        )
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': True,
            'is_blocked': False,
            'is_pending_rejection': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_verdict_info_prettifier(self):
        verdict_info = {
            'has_auto_approval_disabled': True,
            'is_locked': True,
            'is_promoted_prereview': True,
            'should_be_delayed': True,
            'is_blocked': True,
            'is_pending_rejection': True,
        }
        result = list(AutoApprovalSummary.verdict_info_prettifier(verdict_info))
        assert result == [
            'Has auto-approval disabled/delayed flag set',
            'Version string and guid match a blocklist Block',
            'Is locked by a reviewer',
            'Is pending rejection',
            'Is in a promoted add-on group that requires pre-review',
            "Delayed because it's the first listed version",
        ]

        result = list(AutoApprovalSummary.verdict_info_prettifier({}))
        assert result == []

    def test_verdict_display(self):
        assert (
            AutoApprovalSummary(verdict=amo.AUTO_APPROVED).get_verdict_display()
            == 'Was auto-approved'
        )
        assert (
            AutoApprovalSummary(verdict=amo.NOT_AUTO_APPROVED).get_verdict_display()
            == 'Was *not* auto-approved'
        )
        assert (
            AutoApprovalSummary(
                verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED
            ).get_verdict_display()
            == 'Would have been auto-approved (dry-run mode was in effect)'
        )
        assert (
            AutoApprovalSummary(
                verdict=amo.WOULD_NOT_HAVE_BEEN_AUTO_APPROVED
            ).get_verdict_display()
            == 'Would *not* have been auto-approved (dry-run mode was in effect)'
        )


class TestReviewActionReason(TestCase):
    def test_basic(self):
        reason = ReviewActionReason.objects.create(
            canned_response='Some canned response text.',
            is_active=False,
            name='Test reason',
        )

        assert reason.__str__() == reason.name
        assert not reason.is_active
        assert reason.labelled_name() == f'(** inactive **) {reason.name}'

        reason.update(is_active=True)
        assert reason.labelled_name() == reason.name

    def test_constraint(self):
        reason = ReviewActionReason(name='foo')

        with self.assertRaises(ValidationError):
            reason.full_clean()
        with atomic():
            with self.assertRaises(IntegrityError):
                reason.save()

        reason.canned_response = 'something'
        reason.full_clean()
        reason.save()

        reason.canned_block_reason = 'something else'
        reason.full_clean()
        reason.save()

        reason.canned_response = ''
        reason.full_clean()
        reason.save()


class TestGetFlags(TestCase):
    def setUp(self):
        self.addon = addon_factory()

    def test_none(self):
        assert get_flags(self.addon, self.addon.current_version) == []
        AddonReviewerFlags.objects.create(addon=self.addon)
        assert get_flags(self.addon, self.addon.current_version) == []

    def test_listed_version_single_flag(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled=True,
        )
        expected_flags = [
            ('auto-approval-disabled', 'Auto-approval disabled'),
        ]
        assert get_flags(self.addon, self.addon.current_version) == expected_flags

    def test_listed_version(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled=True,
            auto_approval_delayed_until=datetime.now() + timedelta(hours=2),
            needs_admin_theme_review=True,
        )
        self.addon.current_version.update(source='something.zip')
        expected_flags = [
            ('needs-admin-theme-review', 'Needs Admin Static Theme Review'),
            ('sources-provided', 'Source Code Provided'),
            ('auto-approval-disabled', 'Auto-approval disabled'),
            ('auto-approval-delayed-temporarily', 'Auto-approval delayed temporarily'),
        ]
        assert get_flags(self.addon, self.addon.current_version) == expected_flags

        # With infinite delay.
        self.addon.reviewerflags.update(auto_approval_delayed_until=datetime.max)
        expected_flags = [
            ('needs-admin-theme-review', 'Needs Admin Static Theme Review'),
            ('sources-provided', 'Source Code Provided'),
            ('auto-approval-disabled', 'Auto-approval disabled'),
            (
                'auto-approval-delayed-indefinitely',
                'Auto-approval delayed indefinitely',
            ),
        ]
        assert get_flags(self.addon, self.addon.current_version) == expected_flags

        # Adding unlisted flags doesn't matter.
        self.addon.reviewerflags.update(
            auto_approval_disabled_unlisted=True,
            auto_approval_delayed_until_unlisted=datetime.now() + timedelta(hours=2),
        )
        assert get_flags(self.addon, self.addon.current_version) == expected_flags

    def test_unlisted_version(self):
        version = self.addon.current_version
        version.update(
            channel=amo.CHANNEL_UNLISTED,
            source='something.zip',
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled_unlisted=True,
            auto_approval_delayed_until_unlisted=datetime.now() + timedelta(hours=2),
            needs_admin_theme_review=True,
        )
        expected_flags = [
            ('needs-admin-theme-review', 'Needs Admin Static Theme Review'),
            ('sources-provided', 'Source Code Provided'),
            ('auto-approval-disabled-unlisted', 'Unlisted Auto-approval disabled'),
            (
                'auto-approval-delayed-temporarily-unlisted',
                'Unlisted Auto-approval delayed temporarily',
            ),
        ]
        assert get_flags(self.addon, version) == expected_flags

        # With infinite delay.
        self.addon.reviewerflags.update(
            auto_approval_delayed_until_unlisted=datetime.max
        )
        expected_flags = [
            ('needs-admin-theme-review', 'Needs Admin Static Theme Review'),
            ('sources-provided', 'Source Code Provided'),
            ('auto-approval-disabled-unlisted', 'Unlisted Auto-approval disabled'),
            (
                'auto-approval-delayed-indefinitely-unlisted',
                'Unlisted Auto-approval delayed indefinitely',
            ),
        ]
        assert get_flags(self.addon, version) == expected_flags

        # Adding listed flags doesn't matter.
        self.addon.reviewerflags.update(
            auto_approval_disabled=True,
            auto_approval_delayed_until=datetime.now() + timedelta(hours=2),
        )
        assert get_flags(self.addon, version) == expected_flags

    def test_listed_version_no_flags(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled_unlisted=True,
            auto_approval_delayed_until_unlisted=datetime.now() + timedelta(hours=2),
        )
        assert get_flags(self.addon, self.addon.current_version) == []

    def test_unlisted_version_no_flags(self):
        version = self.addon.current_version
        version.update(channel=amo.CHANNEL_UNLISTED)
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled=True,
            auto_approval_delayed_until=datetime.now() + timedelta(hours=2),
        )
        assert get_flags(self.addon, version) == []

    def test_version_none(self):
        assert get_flags(self.addon, None) == []

    def test_due_date_reason_flags(self):
        def reset_all_flags_to_false():
            for entry in NeedsHumanReview.REASONS:
                setattr(self.addon, entry.annotation, False)

        assert get_flags(self.addon, self.addon.current_version) == []
        reset_all_flags_to_false()
        assert get_flags(self.addon, self.addon.current_version) == []
        for entry in NeedsHumanReview.REASONS:
            reset_all_flags_to_false()
            setattr(self.addon, entry.annotation, True)
            assert get_flags(self.addon, self.addon.current_version) == [
                (entry.annotation.replace('_', '-'), entry.label)
            ]


class TestNeedsHumanReview(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        self.version = self.addon.current_version
        ActivityLog.objects.all().delete()
        UserProfile.objects.create(pk=settings.TASK_USER_ID)

    def tearDown(self):
        core.set_user(None)

    def test_save_new_record_activity(self):
        needs_human_review = NeedsHumanReview.objects.create(
            version=self.version, reason=NeedsHumanReview.REASONS.UNKNOWN
        )
        assert needs_human_review.is_active  # Defaults to active.
        assert ActivityLog.objects.for_versions(self.version).count() == 1
        activity = ActivityLog.objects.for_versions(self.version).get()
        assert activity.action == amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id
        assert activity.user.pk == settings.TASK_USER_ID

    def test_save_new_record_activity_with_core_get_user(self):
        self.user = user_factory()
        core.set_user(self.user)
        needs_human_review = NeedsHumanReview.objects.create(
            version=self.version, reason=NeedsHumanReview.REASONS.UNKNOWN
        )
        assert needs_human_review.is_active  # Defaults to active.
        assert ActivityLog.objects.for_versions(self.version).count() == 1
        activity = ActivityLog.objects.for_versions(self.version).get()
        assert activity.action == amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id
        assert activity.user.pk == self.user.pk

    def test_save_existing_does_not_record_an_activity(self):
        flagged = NeedsHumanReview.objects.create(
            version=self.version, reason=NeedsHumanReview.REASONS.UNKNOWN
        )
        ActivityLog.objects.all().delete()
        flagged.reason = NeedsHumanReview.REASONS.DEVELOPER_REPLY
        flagged.save()
        assert ActivityLog.objects.count() == 0

    def test_reasons_have_annotation_property(self):
        for entry in NeedsHumanReview.REASONS:
            assert entry.annotation == f'needs_human_review_{entry.name.lower()}'


class UsageTierTests(TestCase):
    def setUp(self):
        self.tier = UsageTier.objects.create(
            lower_adu_threshold=100,
            upper_adu_threshold=1000,
            growth_threshold_before_flagging=50,
        )

    def test_get_base_addons(self):
        addon_factory(status=amo.STATUS_DISABLED)
        addon_factory(type=amo.ADDON_STATICTHEME)
        expected = {addon_factory()}
        assert set(self.tier.get_base_addons()) == expected

    def test_get_tier_boundaries(self):
        assert self.tier.get_tier_boundaries() == {
            'average_daily_users__gte': 100,
            'average_daily_users__lt': 1000,
        }

    def test_get_tier_boundaries_no_lower_threshold(self):
        self.tier.lower_adu_threshold = None
        assert self.tier.get_tier_boundaries() == {
            'average_daily_users__gte': 0,
            'average_daily_users__lt': 1000,
        }

    def test_get_tier_boundaries_no_upper_threshold(self):
        self.tier.upper_adu_threshold = None
        assert self.tier.get_tier_boundaries() == {
            'average_daily_users__gte': 100,
        }

    def test_average_growth(self):
        addon_factory(hotness=0.5, average_daily_users=1000)  # Different tier
        addon_factory(
            hotness=0.5, average_daily_users=999, status=amo.STATUS_DISABLED
        )  # Right tier but disabled
        addon_factory(
            hotness=0.5, average_daily_users=999, type=amo.ADDON_STATICTHEME
        )  # Right tier but not an extension
        addon_factory(hotness=0.1, average_daily_users=100)
        addon_factory(hotness=0.2, average_daily_users=999)
        assert round(self.tier.average_growth, ndigits=2) == 0.15

        # Value is cached on the instance
        addon_factory(hotness=0.3, average_daily_users=500)
        assert round(self.tier.average_growth, ndigits=2) == 0.15
        del self.tier.average_growth
        assert round(self.tier.average_growth, ndigits=2) == 0.2

    def test_get_growth_threshold(self):
        assert round(self.tier.get_growth_threshold(), ndigits=2) == 0.5
        addon_factory(hotness=0.01, average_daily_users=100)
        addon_factory(hotness=0.01, average_daily_users=999)
        del self.tier.average_growth
        assert round(self.tier.get_growth_threshold(), ndigits=2) == 0.51

        addon_factory(hotness=0.78, average_daily_users=999)
        del self.tier.average_growth
        assert round(self.tier.get_growth_threshold(), ndigits=2) == 0.77

    def test_get_growth_threshold_not_set(self):
        self.tier.growth_threshold_before_flagging = None
        assert self.tier.get_growth_threshold() == 0

    def test_get_growth_threshold_zero_floor_instead_of_negative(self):
        addon_factory(hotness=-0.4, average_daily_users=100)
        addon_factory(hotness=-0.4, average_daily_users=999)
        assert round(self.tier.get_growth_threshold(), ndigits=2) == 0.1

        addon_factory(hotness=-0.9, average_daily_users=999)
        addon_factory(hotness=-0.9, average_daily_users=999)
        del self.tier.average_growth
        assert round(self.tier.get_growth_threshold(), ndigits=2) == 0  # Not -0.15

    def test_get_growth_threshold_q_object(self):
        addon_factory(hotness=0.01, average_daily_users=100)
        addon_factory(hotness=0.01, average_daily_users=999)
        expected = [addon_factory(hotness=0.78, average_daily_users=999)]

        assert (
            list(Addon.objects.filter(self.tier.get_growth_threshold_q_object()))
            == expected
        )

    def test_get_growth_threshold_q_object_hotness_needs_to_be_higher_than(self):
        addon_factory(hotness=0.5, average_daily_users=999)
        expected = [addon_factory(hotness=0.501, average_daily_users=999)]

        # Override computed average growth to force the growth threshold to
        # 0.5 (0.0 + 50/100)
        self.tier.average_growth = 0.0
        assert self.tier.get_growth_threshold() == 0.5

        # We filter on hotness_gt in get_growth_threshold_q_object() so the
        # first add-on shouldn't be returned, only the second one.
        assert (
            list(Addon.objects.filter(self.tier.get_growth_threshold_q_object()))
            == expected
        )
