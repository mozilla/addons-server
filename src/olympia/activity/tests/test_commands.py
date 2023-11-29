from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

from olympia import amo
from olympia.activity.models import ActivityLog, ActivityLogToken, RatingLog
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.ratings.models import Rating


class TestRepudiateActivityLogToken(TestCase):
    def setUp(self):
        addon = addon_factory()
        self.version = addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        self.token1 = ActivityLogToken.objects.create(
            uuid='5a0b8a83d501412589cc5d562334b46b',
            version=self.version,
            user=user_factory(),
        )
        self.token2 = ActivityLogToken.objects.create(
            uuid='8a0b8a834e71412589cc5d562334b46b',
            version=self.version,
            user=user_factory(),
        )
        self.token3 = ActivityLogToken.objects.create(
            uuid='336ae924bc23804cef345d562334b46b',
            version=self.version,
            user=user_factory(),
        )
        addon2 = addon_factory()
        addon2_version = addon2.find_latest_version(channel=amo.CHANNEL_LISTED)
        self.token_diff_version = ActivityLogToken.objects.create(
            uuid='470023efdac5730773340eaf3080b589',
            version=addon2_version,
            user=user_factory(),
        )

    def test_with_tokens(self):
        call_command(
            'repudiate_token',
            '5a0b8a83d501412589cc5d562334b46b',
            '8a0b8a834e71412589cc5d562334b46b',
        )
        assert self.token1.reload().is_expired()
        assert self.token2.reload().is_expired()
        assert not self.token3.reload().is_expired()
        assert not self.token_diff_version.reload().is_expired()

    def test_with_version(self):
        call_command('repudiate_token', version_id=self.version.id)
        assert self.token1.reload().is_expired()
        assert self.token2.reload().is_expired()
        assert self.token3.reload().is_expired()
        assert not self.token_diff_version.reload().is_expired()

    def test_with_token_and_version_ignores_version(self):
        call_command(
            'repudiate_token',
            '5a0b8a83d501412589cc5d562334b46b',
            version_id=self.version.id,
        )
        assert self.token1.reload().is_expired()  # token supplied is expired.
        assert not self.token2.reload().is_expired()  # version supplied isn't.
        assert not self.token3.reload().is_expired()  # check the others too.
        assert not self.token_diff_version.reload().is_expired()

    def test_no_tokens_no_version_is_error(self):
        with pytest.raises(CommandError):
            call_command('repudiate_token')


@pytest.mark.django_db
def test_backfill_ratinglog_command():
    user = user_factory()
    addon = addon_factory()

    no_rating_in_args_log = ActivityLog.objects.create(amo.LOG.ADD_RATING, user=user)
    assert no_rating_in_args_log.arguments == []

    missing = Rating.objects.create(addon=addon, user=user)
    missing_log = ActivityLog.objects.create(amo.LOG.ADD_RATING, user=user)
    missing_log.set_arguments((missing,))
    missing_log.save()

    has_rating = Rating.objects.create(addon=addon, user=user)
    has_rating_log = ActivityLog.objects.create(
        amo.LOG.ADD_RATING, has_rating, user=user
    )
    assert has_rating_log.arguments == [has_rating]

    has_rating_not_no_ratinglog_yet = Rating.objects.create(addon=addon, user=user)
    has_rating_not_no_ratinglog_yet_log = ActivityLog.objects.create(
        amo.LOG.ADD_RATING, has_rating_not_no_ratinglog_yet, user=user
    )
    assert has_rating_not_no_ratinglog_yet_log.arguments == [
        has_rating_not_no_ratinglog_yet
    ]

    has_rating_log.ratinglog_set.all().delete()

    other_action = Rating.objects.create(addon=addon, user=user)
    other_action_log = ActivityLog.objects.create(
        amo.LOG.CHANGE_STATUS, addon, user=user
    )
    assert other_action_log.arguments == [addon]
    other_action_log.set_arguments((addon, other_action))
    other_action_log.save()

    assert RatingLog.objects.count() == 1
    call_command('backfill_ratinglog')

    assert RatingLog.objects.count() == 3
    ratinglog1, ratinglog2, ratinglog3 = list(RatingLog.objects.all().order_by('-id'))
    assert ratinglog1.activity_log == missing_log
    assert ratinglog1.rating == missing
    assert ratinglog2.activity_log == has_rating_log
    assert ratinglog2.rating == has_rating
    assert ratinglog3.activity_log == has_rating_not_no_ratinglog_yet_log
    assert ratinglog3.rating == has_rating_not_no_ratinglog_yet
