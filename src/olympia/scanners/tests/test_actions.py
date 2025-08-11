from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings

import pytest

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
    version_review_flags_factory,
)
from olympia.constants.scanners import (
    CUSTOMS,
    DELAY_AUTO_APPROVAL,
    DELAY_AUTO_APPROVAL_INDEFINITELY,
    FLAG_FOR_HUMAN_REVIEW,
    MAD,
    NO_ACTION,
    YARA,
)
from olympia.files.models import FileUpload
from olympia.scanners.actions import (
    _delay_auto_approval,
    _delay_auto_approval_indefinitely,
    _delay_auto_approval_indefinitely_and_restrict,
    _delay_auto_approval_indefinitely_and_restrict_future_approvals,
    _flag_for_human_review,
    _flag_for_human_review_by_scanner,
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
from olympia.versions.models import VersionReviewerFlags


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
        user2 = user_factory(last_login_ip='')
        user3 = user_factory()
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

    def test_flag_for_human_review_by_scanner(self):
        version = version_factory(addon=addon_factory())
        with self.assertRaises(VersionReviewerFlags.DoesNotExist):
            version.reviewerflags  # noqa: B018

        _flag_for_human_review_by_scanner(version=version, rule=None, scanner=MAD)

        assert version.reviewerflags.needs_human_review_by_mad

    def test_flag_for_human_review_by_scanner_with_existing_flags(self):
        version = version_factory(addon=addon_factory())
        version_review_flags_factory(version=version)

        assert not version.reviewerflags.needs_human_review_by_mad

        _flag_for_human_review_by_scanner(version=version, rule=None, scanner=MAD)
        version.refresh_from_db()

        assert version.reviewerflags.needs_human_review_by_mad

    def test_flag_for_human_review_by_scanner_raises_if_not_mad(self):
        version = version_factory(addon=addon_factory())

        with self.assertRaises(ValueError):
            assert _flag_for_human_review_by_scanner(
                version=version, rule=None, scanner=CUSTOMS
            )


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

    def test_flags_for_human_review_by_mad_when_score_is_too_low(self):
        version = version_factory(addon=addon_factory())
        results = {'scanners': {'customs': {'score': 0.001}}}
        ScannerResult.objects.create(version=version, scanner=MAD, results=results)

        ScannerResult.run_action(version)

        assert version.reviewerflags.needs_human_review_by_mad

    def test_flags_for_human_review_by_mad_when_score_is_too_high(self):
        version = version_factory(addon=addon_factory())
        results = {'scanners': {'customs': {'score': 0.99}}}
        ScannerResult.objects.create(version=version, scanner=MAD, results=results)

        ScannerResult.run_action(version)

        assert version.reviewerflags.needs_human_review_by_mad

    def test_flags_for_human_review_by_mad_when_models_disagree(self):
        version = version_factory(addon=addon_factory())
        results = {'scanners': {'customs': {'result_details': {'models_agree': False}}}}
        ScannerResult.objects.create(version=version, scanner=MAD, results=results)

        ScannerResult.run_action(version)

        assert version.reviewerflags.needs_human_review_by_mad

    def test_does_not_flag_for_human_review_by_mad_if_check_argument_is_false(self):
        version = version_factory(addon=addon_factory())
        results = {'scanners': {'customs': {'result_details': {'models_agree': False}}}}
        ScannerResult.objects.create(version=version, scanner=MAD, results=results)

        ScannerResult.run_action(version, check_mad_results=False)

        with self.assertRaises(VersionReviewerFlags.DoesNotExist):
            version.reviewerflags  # noqa: B018

    def test_does_not_flag_for_human_review_by_mad_when_score_is_okay(self):
        version = version_factory(addon=addon_factory())
        results = {'scanners': {'customs': {'score': 0.2}}}
        ScannerResult.objects.create(version=version, scanner=MAD, results=results)

        ScannerResult.run_action(version)

        with self.assertRaises(VersionReviewerFlags.DoesNotExist):
            version.reviewerflags  # noqa: B018
