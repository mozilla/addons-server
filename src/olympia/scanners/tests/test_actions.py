import json
import uuid
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings

import pytest
import responses

from olympia import amo
from olympia.abuse.models import CinderJob, ContentDecision
from olympia.activity.models import ActivityLog
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.blocklist.models import Block, BlockType, BlockVersion
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.constants.scanners import (
    DELAY_AUTO_APPROVAL,
    DELAY_AUTO_APPROVAL_INDEFINITELY,
    DISABLE_AND_BLOCK,
    FLAG_FOR_HUMAN_REVIEW,
    NO_ACTION,
    YARA,
)
from olympia.files.models import FileUpload
from olympia.promoted.models import PromotedGroup
from olympia.reviewers.models import UsageTier
from olympia.scanners.actions import (
    _delay_auto_approval,
    _delay_auto_approval_indefinitely,
    _delay_auto_approval_indefinitely_and_restrict,
    _delay_auto_approval_indefinitely_and_restrict_future_approvals,
    _disable_and_block,
    _flag_for_human_review,
    _no_action,
)
from olympia.scanners.models import (
    ScannerResult,
    ScannerRule,
)
from olympia.users.models import (
    RESTRICTION_TYPES,
    EmailUserRestriction,
    IPNetworkUserRestriction,
)


class TestActions(TestCase):
    def setUp(self):
        user_factory(pk=settings.TASK_USER_ID)

    def test_action_does_nothing(self):
        version = version_factory(addon=addon_factory())
        _no_action(version=version, rule=None)

    def test_flags_a_version_for_human_review(self):
        version = version_factory(addon=addon_factory())
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        # We'll return True because there is an active scanner NHR (that we created).
        assert _flag_for_human_review(version=version, rule=None)
        assert version.needshumanreview_set.filter(is_active=True).exists()
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_does_not_flag_for_human_review_twice_still_active(self):
        version = version_factory(addon=addon_factory())
        nhr = version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=True,
        )

        # We'll return True because there is an active scanner NHR...
        assert _flag_for_human_review(version=version, rule=None)

        # ... But we haven't added an extra flag.
        assert (
            version.needshumanreview_set.filter(
                reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION
            ).count()
            == 1
        )

        # The original one is still here and still active.
        assert nhr.reload().is_active

    def test_does_not_flag_for_human_review_twice_inactive(self):
        version = version_factory(addon=addon_factory())
        nhr = version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=False,
        )

        # We'll return False because there is a scanner NHR but it's inactive.
        assert not _flag_for_human_review(version=version, rule=None)

        # ... But we haven't added an extra flag.
        assert (
            version.needshumanreview_set.filter(
                reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION
            ).count()
            == 1
        )

        # The original one is still here and still inactive.
        assert not nhr.reload().is_active

    def test_delay_auto_approval(self):
        addon = addon_factory(file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval(version=version, rule=None)
        self.assertCloseToNow(
            addon.auto_approval_delayed_until,
            now=datetime.now() + timedelta(hours=24),
        )
        self.assertCloseToNow(
            addon.auto_approval_delayed_until_unlisted,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.filter(is_active=True).exists()
        self.assertCloseToNow(
            version.due_date,
            now=datetime.now() + timedelta(hours=24),
        )
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_overwrite_null(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval(version=version, rule=None)
        self.assertCloseToNow(
            addon.auto_approval_delayed_until,
            now=datetime.now() + timedelta(hours=24),
        )
        self.assertCloseToNow(
            addon.auto_approval_delayed_until_unlisted,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.filter(is_active=True).exists()
        self.assertCloseToNow(
            version.due_date,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_overwrite_existing_lower_delay_on_right_channels(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={
                'auto_approval_delayed_until': datetime.now() + timedelta(days=2),
                'auto_approval_delayed_until_unlisted': datetime.now()
                - timedelta(days=2),
            },
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        self.assertCloseToNow(
            addon.auto_approval_delayed_until, now=datetime.now() + timedelta(days=2)
        )
        self.assertCloseToNow(
            addon.auto_approval_delayed_until_unlisted,
            now=datetime.now() - timedelta(days=2),
        )
        _delay_auto_approval(version=version, rule=None)
        self.assertCloseToNow(
            addon.auto_approval_delayed_until, now=datetime.now() + timedelta(days=2)
        )
        self.assertCloseToNow(
            addon.auto_approval_delayed_until_unlisted,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.filter(is_active=True).exists()
        # due date _was_ set to in 24 hours no matter what since it's per-version.
        self.assertCloseToNow(
            version.due_date,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_dont_overwrite_existing_higher_delay(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={
                'auto_approval_delayed_until': datetime.now() + timedelta(days=2),
                'auto_approval_delayed_until_unlisted': datetime.now()
                + timedelta(days=2),
            },
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        self.assertCloseToNow(
            addon.auto_approval_delayed_until, now=datetime.now() + timedelta(days=2)
        )
        self.assertCloseToNow(
            addon.auto_approval_delayed_until_unlisted,
            now=datetime.now() + timedelta(days=2),
        )
        _delay_auto_approval(version=version, rule=None)
        self.assertCloseToNow(
            addon.auto_approval_delayed_until, now=datetime.now() + timedelta(days=2)
        )
        self.assertCloseToNow(
            addon.auto_approval_delayed_until_unlisted,
            now=datetime.now() + timedelta(days=2),
        )
        assert version.needshumanreview_set.filter(is_active=True).exists()
        # due date _was_ set to in 24 hours no matter what since it's per-version.
        self.assertCloseToNow(
            version.due_date,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_overwrite_existing_lower_delay(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_delayed_until': datetime.now()},
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        self.assertCloseToNow(addon.auto_approval_delayed_until, now=datetime.now())
        assert addon.auto_approval_delayed_until_unlisted is None
        _delay_auto_approval(version=version, rule=None)
        self.assertCloseToNow(
            addon.auto_approval_delayed_until, now=datetime.now() + timedelta(hours=24)
        )
        self.assertCloseToNow(
            addon.auto_approval_delayed_until_unlisted,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.filter(is_active=True).exists()
        # due date _was_ set to in 24 hours no matter what since it's per-version.
        self.assertCloseToNow(
            version.due_date,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_existing_due_date_older(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_disabled': True},
            version_kw={'due_date': self.days_ago(1)},
        )
        version = addon.current_version
        self.assertCloseToNow(version.due_date, now=self.days_ago(1))
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval(version=version, rule=None)
        addon.reviewerflags.reload()
        self.assertCloseToNow(
            addon.auto_approval_delayed_until,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.filter(is_active=True).exists()
        # We kept the original due date as it's shorter.
        self.assertCloseToNow(version.due_date, now=self.days_ago(1))
        assert version.needshumanreview_set.count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_existing_due_date_newer(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_disabled': True},
            version_kw={'due_date': datetime.now() + timedelta(hours=72)},
        )
        version = addon.current_version
        self.assertCloseToNow(
            version.due_date,
            now=datetime.now() + timedelta(hours=72),
        )
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval(version=version, rule=None)
        addon.reviewerflags.reload()
        self.assertCloseToNow(
            addon.auto_approval_delayed_until,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.filter(is_active=True).exists()
        # We overrode the due date with 24 hours so that it goes back to the
        # top of the queue.
        self.assertCloseToNow(
            version.due_date,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_already_flagged_active(self):
        addon = addon_factory(file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version = addon.current_version
        # Create an existing active flag.
        version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=True,
        )
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval(version=version, rule=None)
        # Everything still happening as normal, an active flag doesn't prevent
        # the action from running.
        self.assertCloseToNow(
            addon.auto_approval_delayed_until,
            now=datetime.now() + timedelta(hours=24),
        )
        self.assertCloseToNow(
            addon.auto_approval_delayed_until_unlisted,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needshumanreview_set.filter(is_active=True).exists()
        self.assertCloseToNow(
            version.due_date,
            now=datetime.now() + timedelta(hours=24),
        )
        # We haven't flagged it multiple times.
        assert version.needshumanreview_set.count() == 1

    def test_delay_auto_approval_already_flagged_inactive(self):
        addon = addon_factory(file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version = addon.current_version
        # Create an existing inactive flag.
        version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=False,
        )
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval(version=version, rule=None)
        # An inactive scanner action NHR flag means we shouldn't execute the
        # action.
        assert not addon.auto_approval_delayed_until
        assert not addon.auto_approval_delayed_until_unlisted

        # We shouldn't re-flag either.
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert not version.due_date

    def test_delay_auto_approval_indefinitely(self):
        addon = addon_factory(file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely(version=version, rule=None)
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        assert version.needshumanreview_set.count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_indefinitely_overwrite_existing(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_delayed_until': datetime.now()},
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        self.assertCloseToNow(addon.auto_approval_delayed_until)
        assert addon.auto_approval_delayed_until_unlisted is None
        _delay_auto_approval_indefinitely(version=version, rule=None)
        addon.reviewerflags.reload()
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        assert version.needshumanreview_set.count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_indefinitely_overwrite_existing_unlisted(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_delayed_until_unlisted': datetime.now()},
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        self.assertCloseToNow(addon.auto_approval_delayed_until_unlisted)
        _delay_auto_approval_indefinitely(version=version, rule=None)
        addon.reviewerflags.reload()
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        assert version.needshumanreview_set.count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.SCANNER_ACTION
        )

    def test_delay_auto_approval_indefinitely_already_flagged_active(self):
        addon = addon_factory(file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version = addon.current_version
        # Create an existing active flag.
        version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=True,
        )
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely(version=version, rule=None)
        # Everything still happening as normal, an active flag doesn't prevent
        # the action from running.
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        assert version.due_date
        # We haven't flagged it multiple times.
        assert version.needshumanreview_set.count() == 1

    def test_delay_auto_approval_indefinitely_already_flagged_inactive(self):
        addon = addon_factory(file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version = addon.current_version
        # Create an existing inactive flag.
        version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=False,
        )
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely(version=version, rule=None)
        # An inactive scanner action NHR flag means we shouldn't execute the
        # action.
        assert not addon.auto_approval_delayed_until
        assert not addon.auto_approval_delayed_until_unlisted

        # We shouldn't re-flag either.
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert not version.due_date

    def test_delay_auto_approval_indefinitely_and_restrict(self):
        user1 = user_factory(last_login_ip='5.6.7.8')
        user2 = user_factory(last_login_ip='')
        user3 = user_factory()
        user4 = user_factory(last_login_ip='4.8.15.16')
        addon = addon_factory(users=[user1, user2])
        FileUpload.objects.create(
            addon=addon,
            user=user3,
            version=addon.current_version.version,
            ip_address='1.2.3.4',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely_and_restrict(version=version, rule=None)
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user1.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user2.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user3.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert not EmailUserRestriction.objects.filter(
            email_pattern=user4.email
        ).exists()
        for restriction in EmailUserRestriction.objects.all():
            assert restriction.reason == (
                'Automatically added because of a match by rule "None" on '
                f'Addon {addon.pk} Version {addon.current_version.pk}.'
            )

        assert IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ).exists()
        assert IPNetworkUserRestriction.objects.filter(
            network='1.2.3.4/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ).exists()
        assert not IPNetworkUserRestriction.objects.filter(network=None).exists()
        assert not IPNetworkUserRestriction.objects.filter(network='').exists()
        assert not IPNetworkUserRestriction.objects.filter(
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert not EmailUserRestriction.objects.filter(
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        for restriction in IPNetworkUserRestriction.objects.all():
            assert restriction.reason == (
                'Automatically added because of a match by rule "None" on '
                f'Addon {addon.pk} Version {addon.current_version.pk}.'
            )

    def test_delay_auto_approval_indefinitely_and_restrict_with_ipv6(self):
        user1 = user_factory(last_login_ip='2001:0db8:4815:1623:4200:1337:cafe:d00d')
        user2 = user_factory(last_login_ip='')
        user3 = user_factory()
        addon = addon_factory(users=[user1, user2])
        FileUpload.objects.create(
            addon=addon,
            user=user3,
            version=addon.current_version.version,
            ip_address='1.2.3.4',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely_and_restrict(version=version, rule=None)

        # For IPv6, the /64 was restricted.
        assert IPNetworkUserRestriction.objects.filter(
            network='2001:db8:4815:1623::/64',
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        # For IPv4, the /32 (equivalent to that single IP) was restricted.
        assert IPNetworkUserRestriction.objects.filter(
            network='1.2.3.4/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ).exists()
        assert not IPNetworkUserRestriction.objects.filter(network=None).exists()
        assert not IPNetworkUserRestriction.objects.filter(network='').exists()
        assert not IPNetworkUserRestriction.objects.filter(
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()

        for restriction in IPNetworkUserRestriction.objects.all():
            assert restriction.reason == (
                'Automatically added because of a match by rule "None" on '
                f'Addon {addon.pk} Version {addon.current_version.pk}.'
            )

    def test_delay_auto_approval_indefinitely_and_restrict_already_restricted(self):
        user1 = user_factory(last_login_ip='5.6.7.8')
        user2 = user_factory(last_login_ip='', email='foo+variant@example.com')
        user3 = user_factory(email='foo@example.com')
        user4 = user_factory(last_login_ip='4.8.15.16')
        existing_restriction1 = EmailUserRestriction.objects.create(
            email_pattern=user1.email
        )
        existing_restriction2 = EmailUserRestriction.objects.create(
            email_pattern=user3.email
        )
        existing_restriction3 = IPNetworkUserRestriction.objects.create(
            network='5.6.7.8/32'
        )
        addon = addon_factory(users=[user1, user2])
        FileUpload.objects.create(
            addon=addon,
            user=user3,
            version=addon.current_version.version,
            ip_address='1.2.3.4',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely_and_restrict(version=version, rule=None)
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user1.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=EmailUserRestriction.normalize_email(user2.email),
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user3.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert not EmailUserRestriction.objects.filter(
            email_pattern=user4.email
        ).exists()
        for restriction in EmailUserRestriction.objects.all():
            if restriction.pk in (existing_restriction1.pk, existing_restriction2.pk):
                assert restriction.reason is None
            else:
                assert restriction.reason == (
                    'Automatically added because of a match by rule "None" on '
                    f'Addon {addon.pk} Version {addon.current_version.pk}.'
                )

        assert IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ).exists()
        assert IPNetworkUserRestriction.objects.filter(
            network='1.2.3.4/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ).exists()
        assert not IPNetworkUserRestriction.objects.filter(network=None).exists()
        assert not IPNetworkUserRestriction.objects.filter(network='').exists()
        for restriction in IPNetworkUserRestriction.objects.all():
            if restriction.pk in (existing_restriction3.pk,):
                assert restriction.reason is None
            else:
                assert restriction.reason == (
                    'Automatically added because of a match by rule "None" on '
                    f'Addon {addon.pk} Version {addon.current_version.pk}.'
                )

    def test_delay_auto_approval_indefinitely_and_restrict_already_restricted_other(
        self,
    ):
        rule = ScannerRule.objects.create(
            scanner=YARA,
            name=(
                'This is a very long rule name that goes over 100 characters, which is '
                'quite a lot but we need to test this scenario to make sure this works '
                'properly even in this case.'
            ),
        )
        user1 = user_factory(last_login_ip='5.6.7.8')
        user2 = user_factory(last_login_ip='')
        user3 = user_factory()
        user4 = user_factory(last_login_ip='4.8.15.16')
        existing_restriction1 = EmailUserRestriction.objects.create(
            email_pattern=user1.email, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )
        existing_restriction2 = EmailUserRestriction.objects.create(
            email_pattern=user3.email, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )
        existing_restriction3 = IPNetworkUserRestriction.objects.create(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        )
        addon = addon_factory(users=[user1, user2])
        FileUpload.objects.create(
            addon=addon,
            user=user3,
            version=addon.current_version.version,
            ip_address='1.2.3.4',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely_and_restrict(version=version, rule=rule)
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        # We added a new restriction for submission without touching the existing one
        # for approval for user1 and user3
        assert EmailUserRestriction.objects.filter(
            email_pattern=user1.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user1.email, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user2.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user3.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user3.email, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert not EmailUserRestriction.objects.filter(
            email_pattern=user4.email
        ).exists()
        for restriction in EmailUserRestriction.objects.all():
            if restriction.pk in (existing_restriction1.pk, existing_restriction2.pk):
                assert restriction.reason is None
            else:
                assert restriction.reason == (
                    'Automatically added because of a match by rule "This is a very '
                    'long rule name that goes over 100 characters, which is quite a '
                    'lot but we need to test this scenario to make sure this works '
                    'properly e" on '
                    f'Addon {addon.pk} Version {addon.current_version.pk}.'
                )

        # Like above, we added a new restriction for submission, this time for the ip,
        # but we left the one for approval.
        assert IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ).exists()
        assert IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert IPNetworkUserRestriction.objects.filter(
            network='1.2.3.4/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ).exists()
        assert not IPNetworkUserRestriction.objects.filter(network=None).exists()
        assert not IPNetworkUserRestriction.objects.filter(network='').exists()
        for restriction in IPNetworkUserRestriction.objects.all():
            if restriction.pk in (existing_restriction3.pk,):
                assert restriction.reason is None
            else:
                assert restriction.reason == (
                    'Automatically added because of a match by rule "This is a very '
                    'long rule name that goes over 100 characters, which is quite a '
                    'lot but we need to test this scenario to make sure this works '
                    'properly e" on '
                    f'Addon {addon.pk} Version {addon.current_version.pk}.'
                )

    def test_delay_auto_approval_indefinitely_and_restrict_already_flagged_active(self):
        user = user_factory(last_login_ip='5.6.7.8')
        addon = addon_factory(users=[user])
        version = addon.current_version
        # Create an existing active flag.
        version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=True,
        )
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely_and_restrict(version=version, rule=None)
        # Everything still happening as normal, an active flag doesn't prevent
        # the action from running.
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ).exists()
        assert version.due_date
        # We haven't flagged it multiple times.
        assert version.needshumanreview_set.count() == 1

    def test_delay_auto_approval_indefinitely_and_restrict_already_flagged_inactive(
        self,
    ):
        user = user_factory(last_login_ip='5.6.7.8')
        addon = addon_factory(users=[user])
        version = addon.current_version
        # Create an existing inactive flag.
        version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=False,
        )
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely_and_restrict(version=version, rule=None)
        # An inactive scanner action NHR flag means we shouldn't execute the
        # action.
        assert not addon.auto_approval_delayed_until
        assert not addon.auto_approval_delayed_until_unlisted
        assert not EmailUserRestriction.objects.filter(
            email_pattern=user.email
        ).exists()
        assert not IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32'
        ).exists()

        # We shouldn't re-flag either.
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert not version.due_date

    def test_delay_auto_approval_indefinitely_and_restrict_future_approvals(self):
        user1 = user_factory(last_login_ip='5.6.7.8')
        user2 = user_factory(last_login_ip='')
        user3 = user_factory()
        user4 = user_factory(last_login_ip='4.8.15.16')
        EmailUserRestriction.objects.create(
            email_pattern=user1.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        )
        EmailUserRestriction.objects.create(
            email_pattern=user3.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        )
        IPNetworkUserRestriction.objects.create(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        )
        addon = addon_factory(users=[user1, user2])
        FileUpload.objects.create(
            addon=addon,
            user=user3,
            version=addon.current_version.version,
            ip_address='1.2.3.4',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely_and_restrict_future_approvals(
            version=version, rule=None
        )
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        # We added a new restriction for approval without touching the existing one
        # for submission for user1 and user3
        assert EmailUserRestriction.objects.filter(
            email_pattern=user1.email, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user1.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user2.email, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user3.email, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user3.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).exists()
        assert not EmailUserRestriction.objects.filter(
            email_pattern=user4.email
        ).exists()

        # Like above, we added a new restriction for approval, this time for the ip,
        # but we left the one for submission.
        assert IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
        ).exists()
        assert IPNetworkUserRestriction.objects.filter(
            network='1.2.3.4/32', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert not IPNetworkUserRestriction.objects.filter(network=None).exists()
        assert not IPNetworkUserRestriction.objects.filter(network='').exists()

    def test_restrict_future_approvals_already_flagged_active(self):
        user = user_factory(last_login_ip='5.6.7.8')
        addon = addon_factory(users=[user])
        version = addon.current_version
        # Create an existing active flag.
        version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=True,
        )
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely_and_restrict_future_approvals(
            version=version, rule=None
        )
        # Everything still happening as normal, an active flag doesn't prevent
        # the action from running.
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()
        assert EmailUserRestriction.objects.filter(
            email_pattern=user.email,
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        ).exists()
        assert IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32', restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
        ).exists()
        assert version.due_date
        # We haven't flagged it multiple times.
        assert version.needshumanreview_set.count() == 1

    def test_restrict_future_approvals_already_flagged_inactive(self):
        user = user_factory(last_login_ip='5.6.7.8')
        addon = addon_factory(users=[user])
        version = addon.current_version
        # Create an existing inactive flag.
        version.needshumanreview_set.create(
            reason=version.needshumanreview_set.model.REASONS.SCANNER_ACTION,
            is_active=False,
        )
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely_and_restrict_future_approvals(
            version=version, rule=None
        )
        # An inactive scanner action NHR flag means we shouldn't execute the
        # action.
        assert not addon.auto_approval_delayed_until
        assert not addon.auto_approval_delayed_until_unlisted
        assert not EmailUserRestriction.objects.filter(
            email_pattern=user.email
        ).exists()
        assert not IPNetworkUserRestriction.objects.filter(
            network='5.6.7.8/32'
        ).exists()

        # We shouldn't re-flag either.
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert not version.due_date

    def test_delay_auto_approval_indefinitely_and_restrict_nothing_to_restrict(self):
        addon = addon_factory()
        version = addon.current_version
        assert not version.needshumanreview_set.filter(is_active=True).exists()
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely(version=version, rule=None)
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        assert version.needshumanreview_set.filter(is_active=True).exists()

    def do_disable_and_block(self, addon):
        existing_decision_count = ContentDecision.objects.count()
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )

        UsageTier.objects.create(
            upper_adu_threshold=10000, disable_and_block_action_available=True
        )
        version1 = addon.current_version
        version2 = version_factory(addon=addon)
        rule = ScannerRule.objects.create(scanner=YARA, name='Test Rule')
        _disable_and_block(version=version2, rule=rule)
        assert addon.reload().status == amo.STATUS_DISABLED
        assert addon.block
        assert version1.is_blocked
        assert version1.file.reload().status == amo.STATUS_DISABLED
        assert version1.blockversion.block_type == BlockType.SOFT_BLOCKED
        assert version2.is_blocked
        assert version2.file.reload().status == amo.STATUS_DISABLED
        assert version2.blockversion.block_type == BlockType.SOFT_BLOCKED
        assert ContentDecision.objects.count() == existing_decision_count + 1

        assert (
            ActivityLog.objects.filter(
                addonlog__addon=addon, action=amo.LOG.FORCE_DISABLE.id
            )
            .get()
            .details['reason']
            == 'Rejected and blocked due to: scanner rule "Test Rule"'
        )

        for author in addon.authors.all():
            assert EmailUserRestriction.objects.filter(
                email_pattern=author.email,
                restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
            ).exists()
            network = IPNetworkUserRestriction.network_from_ip(author.last_login_ip)
            assert IPNetworkUserRestriction.objects.filter(
                network=network, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
            ).exists()

    def test_disable_and_block(self):
        user = user_factory(last_login_ip='172.16.0.1')
        self.do_disable_and_block(addon_factory(average_daily_users=4242, users=[user]))

    @mock.patch('olympia.scanners.actions.reject_and_block_addons')
    def test_disable_and_block_with_mock(self, reject_and_block_addons_mock):
        UsageTier.objects.create(
            upper_adu_threshold=10000, disable_and_block_action_available=True
        )
        user = user_factory(last_login_ip='172.16.0.1')
        addon = addon_factory(average_daily_users=4242, users=[user])
        rule = ScannerRule.objects.create(scanner=YARA, name='Test Rule')
        _disable_and_block(version=addon.current_version, rule=rule)
        assert reject_and_block_addons_mock.call_count == 1
        assert reject_and_block_addons_mock.call_args.args == ([addon],)
        assert reject_and_block_addons_mock.call_args.kwargs == {
            'reject_reason': 'scanner rule "Test Rule"'
        }

    def test_disable_and_block_second_level_approval(self):
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )

        UsageTier.objects.create(
            upper_adu_threshold=10000, disable_and_block_action_available=True
        )
        PromotedGroup.objects.get_or_create(
            group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED, high_profile=True
        )
        addon = addon_factory(
            average_daily_users=4242,
            promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            version_kw={'promotion_approved': False},
        )

        version1 = addon.current_version
        version2 = version_factory(addon=addon)
        rule = ScannerRule.objects.create(scanner=YARA, name='Test Rule')
        _disable_and_block(version=version2, rule=rule)
        assert addon.reload().status == amo.STATUS_APPROVED  # Not disabled yet
        assert not addon.block
        assert not version1.is_blocked
        assert version1.file.reload().status == amo.STATUS_APPROVED  # Not disabled yet
        assert not version2.is_blocked
        assert version2.file.reload().status == amo.STATUS_APPROVED  # Not disabled yet
        assert ContentDecision.objects.count() == 1
        assert not ContentDecision.objects.get().action_date  # Action pending approval
        assert (
            ActivityLog.objects.filter(
                addonlog__addon=addon, action=amo.LOG.HELD_ACTION_FORCE_DISABLE.id
            )
            .get()
            .details['reason']
            == 'Rejected and blocked due to: scanner rule "Test Rule"'
        )

    def test_disable_and_block_not_available_for_that_tier(self):
        tier = UsageTier.objects.create(lower_adu_threshold=1)
        assert not tier.disable_and_block_action_available  # Default is False
        user = user_factory(last_login_ip='172.16.0.1')
        addon = addon_factory(average_daily_users=1234, users=[user])
        assert addon.get_usage_tier() == tier
        version = addon.current_version
        _disable_and_block(version=version, rule=None)
        # Should not have been disabled & blocked, disable_and_block_action_available
        # is False.
        assert addon.status == amo.STATUS_APPROVED
        assert not Block.objects.exists()
        assert not BlockVersion.objects.exists()
        # Should have been flagged for review and auto-approval disabled as a
        # fallback.
        assert version.needshumanreview_set.filter(is_active=True).exists()
        addon.reviewerflags.reload()
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        # We didn't add restrictions.
        assert not EmailUserRestriction.objects.exists()
        assert not IPNetworkUserRestriction.objects.exists()

    def test_disable_and_block_no_usage_tier(self):
        user = user_factory(last_login_ip='172.16.0.1')
        addon = addon_factory(users=[user])
        version = addon.current_version
        _disable_and_block(version=version, rule=None)
        # Should not have been disabled & blocked since it's not in any tier
        assert addon.status == amo.STATUS_APPROVED
        assert not Block.objects.exists()
        assert not BlockVersion.objects.exists()
        # Should have been flagged for review and auto-approval disabled as a
        # fallback.
        assert version.needshumanreview_set.filter(is_active=True).exists()
        addon.reviewerflags.reload()
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        # We didn't add restrictions.
        assert not EmailUserRestriction.objects.exists()
        assert not IPNetworkUserRestriction.objects.exists()

    def _test_disable_and_block_but_previous_successful_appeal(self, appealed_action):
        UsageTier.objects.create(
            upper_adu_threshold=10000, disable_and_block_action_available=True
        )
        user = user_factory(last_login_ip='172.16.0.1')
        addon = addon_factory(average_daily_users=4242, users=[user])
        version2 = version_factory(addon=addon)
        appeal_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            cinder_job=CinderJob.objects.create(target_addon=addon),
        )
        ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_BLOCK_ADDON,
            appeal_job=appeal_decision.cinder_job,
        )

        _disable_and_block(version=version2, rule=None)

        # Should not have been disabled & blocked because of the previous appeal.
        assert addon.status == amo.STATUS_APPROVED
        assert not Block.objects.exists()
        assert not BlockVersion.objects.exists()
        # Should have been flagged for review and auto-approval disabled as a
        # fallback.
        assert version2.needshumanreview_set.filter(is_active=True).exists()
        addon.reviewerflags.reload()
        assert addon.auto_approval_delayed_until == datetime.max
        assert addon.auto_approval_delayed_until_unlisted == datetime.max
        # We didn't add restrictions.
        assert not EmailUserRestriction.objects.exists()
        assert not IPNetworkUserRestriction.objects.exists()

    def test_disable_and_block_but_previous_successful_appeal_on_block(self):
        self._test_disable_and_block_but_previous_successful_appeal(
            DECISION_ACTIONS.AMO_BLOCK_ADDON
        )

    def test_disable_and_block_but_previous_successful_appeal_on_disable(self):
        self._test_disable_and_block_but_previous_successful_appeal(
            DECISION_ACTIONS.AMO_DISABLE_ADDON
        )

    def test_disable_and_block_but_previous_successful_appeal_on_reject(self):
        self._test_disable_and_block_but_previous_successful_appeal(
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON
        )

    def test_disable_and_block_with_unsuccesful_appeal(self):
        user = user_factory(last_login_ip='172.16.0.1')
        addon = addon_factory(average_daily_users=4242, users=[user])
        appeal_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            cinder_job=CinderJob.objects.create(target_addon=addon),
        )
        ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_BLOCK_ADDON,
            appeal_job=appeal_decision.cinder_job,
        )
        self.do_disable_and_block(addon)

    def test_disable_and_block_with_unresolved_appeal(self):
        user = user_factory(last_login_ip='172.16.0.1')
        addon = addon_factory(average_daily_users=4242, users=[user])
        appeal_job = CinderJob.objects.create(target_addon=addon)
        ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_BLOCK_ADDON,
            appeal_job=appeal_job,
        )
        self.do_disable_and_block(addon)

    def test_disable_and_block_with_non_block_appeal(self):
        user = user_factory(last_login_ip='172.16.0.1')
        addon = addon_factory(average_daily_users=4242, users=[user])
        appeal_decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            cinder_job=CinderJob.objects.create(target_addon=addon),
        )
        ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_IGNORE,
            appeal_job=appeal_decision.cinder_job,
        )
        self.do_disable_and_block(addon)


class TestRunAction(TestCase):
    def setUp(self):
        super().setUp()

        self.scanner = YARA
        self.version = version_factory(addon=addon_factory())
        self.scanner_rule = ScannerRule.objects.create(
            name='rule-1', scanner=self.scanner, action=NO_ACTION
        )
        self.scanner_result = ScannerResult.objects.create(
            version=self.version, scanner=self.scanner
        )
        self.scanner_result.matched_rules.add(self.scanner_rule)

    @mock.patch('olympia.scanners.models._no_action')
    def test_runs_no_action(self, no_action_mock):
        self.scanner_rule.update(action=NO_ACTION)

        ScannerResult.run_action(self.version)

        assert no_action_mock.called
        no_action_mock.assert_called_with(version=self.version, rule=self.scanner_rule)

    @mock.patch('olympia.scanners.models._flag_for_human_review')
    def test_runs_flag_for_human_review(self, flag_for_human_review_mock):
        self.scanner_rule.update(action=FLAG_FOR_HUMAN_REVIEW)

        ScannerResult.run_action(self.version)

        assert flag_for_human_review_mock.called
        flag_for_human_review_mock.assert_called_with(
            version=self.version, rule=self.scanner_rule
        )

    @mock.patch('olympia.scanners.models._delay_auto_approval')
    def test_runs_delay_auto_approval(self, _delay_auto_approval_mock):
        self.scanner_rule.update(action=DELAY_AUTO_APPROVAL)

        ScannerResult.run_action(self.version)

        assert _delay_auto_approval_mock.called
        _delay_auto_approval_mock.assert_called_with(
            version=self.version, rule=self.scanner_rule
        )

    @mock.patch('olympia.scanners.models._delay_auto_approval_indefinitely')
    def test_runs_delay_auto_approval_indefinitely(
        self, _delay_auto_approval_indefinitely_mock
    ):
        self.scanner_rule.update(action=DELAY_AUTO_APPROVAL_INDEFINITELY)

        ScannerResult.run_action(self.version)

        assert _delay_auto_approval_indefinitely_mock.called
        _delay_auto_approval_indefinitely_mock.assert_called_with(
            version=self.version, rule=self.scanner_rule
        )

    @mock.patch('olympia.scanners.models._disable_and_block')
    def test_runs_disable_and_block(self, _disable_and_block_mock):
        self.scanner_rule.update(action=DISABLE_AND_BLOCK)

        ScannerResult.run_action(self.version)

        assert _disable_and_block_mock.call_count == 1
        assert _disable_and_block_mock.call_args[1] == {
            'version': self.version,
            'rule': self.scanner_rule,
        }

    @mock.patch('olympia.scanners.models._delay_auto_approval_indefinitely')
    def test_returns_for_non_extension_addons(
        self, _delay_auto_approval_indefinitely_mock
    ):
        self.scanner_rule.update(action=DELAY_AUTO_APPROVAL_INDEFINITELY)
        self.version.addon.update(type=amo.ADDON_DICT)

        ScannerResult.run_action(self.version)

        assert not _delay_auto_approval_indefinitely_mock.called

        self.version.addon.update(type=amo.ADDON_LPAPP)

        ScannerResult.run_action(self.version)

        assert not _delay_auto_approval_indefinitely_mock.called

        self.version.addon.update(type=amo.ADDON_STATICTHEME)

        ScannerResult.run_action(self.version)

        assert not _delay_auto_approval_indefinitely_mock.called

    @mock.patch('olympia.scanners.models.log.info')
    def test_returns_when_no_action_found(self, log_mock):
        self.scanner_rule.delete()

        ScannerResult.run_action(self.version)

        log_mock.assert_called_with(
            'No action to execute for version %s.', self.version.id
        )

    def test_raise_when_action_is_invalid(self):
        # `12345` is an invalid action ID
        self.scanner_rule.update(action=12345)

        with pytest.raises(Exception, match='invalid action 12345'):
            ScannerResult.run_action(self.version)

    @mock.patch('olympia.scanners.models._no_action')
    @mock.patch('olympia.scanners.models._flag_for_human_review')
    def test_selects_the_action_with_the_highest_severity(
        self, flag_for_human_review_mock, no_action_mock
    ):
        # Create another rule and add it to the current scanner result. This
        # rule is more severe than `rule-1` created in `setUp()`.
        rule = ScannerRule.objects.create(
            name='rule-2', scanner=self.scanner, action=FLAG_FOR_HUMAN_REVIEW
        )
        self.scanner_result.matched_rules.add(rule)

        ScannerResult.run_action(self.version)

        assert not no_action_mock.called
        assert flag_for_human_review_mock.called

    @mock.patch('olympia.scanners.models._no_action')
    @mock.patch('olympia.scanners.models._flag_for_human_review')
    def test_skips_actions_with_exclude_promoted_if_the_addon_is_promoted(
        self, flag_for_human_review_mock, no_action_mock
    ):
        self.make_addon_promoted(
            self.version.addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        # Create another rule and add it to the current scanner result, but set to
        # exclude_promoted_addons=True.
        rule = ScannerRule.objects.create(
            name='rule-2',
            scanner=self.scanner,
            action=FLAG_FOR_HUMAN_REVIEW,
            exclude_promoted_addons=True,
        )
        self.scanner_result.matched_rules.add(rule)

        ScannerResult.run_action(self.version)

        assert no_action_mock.called
        assert not flag_for_human_review_mock.called

    @mock.patch('olympia.scanners.models._no_action')
    @mock.patch('olympia.scanners.models._flag_for_human_review')
    def test_does_not_skip_actions_with_exclude_promoted_if_the_addon_is_not_promoted(
        self, flag_for_human_review_mock, no_action_mock
    ):
        # Create another rule and add it to the current scanner result, set to
        # exclude_promoted_addons=True, but it shouldn't be skipped.
        rule = ScannerRule.objects.create(
            name='rule-2',
            scanner=self.scanner,
            action=FLAG_FOR_HUMAN_REVIEW,
            exclude_promoted_addons=True,
        )
        self.scanner_result.matched_rules.add(rule)

        ScannerResult.run_action(self.version)

        assert not no_action_mock.called
        assert flag_for_human_review_mock.called

    @mock.patch('olympia.scanners.models._no_action')
    @mock.patch('olympia.scanners.models._flag_for_human_review')
    def test_selects_active_actions_only(
        self, flag_for_human_review_mock, no_action_mock
    ):
        # Create another rule and add it to the current scanner result. This
        # rule is more severe than `rule-1` created in `setUp()`. In this test
        # case, we disable this rule, though.
        rule = ScannerRule.objects.create(
            name='rule-2',
            scanner=self.scanner,
            action=FLAG_FOR_HUMAN_REVIEW,
            is_active=False,
        )
        self.scanner_result.matched_rules.add(rule)

        ScannerResult.run_action(self.version)

        assert no_action_mock.called
        assert not flag_for_human_review_mock.called
