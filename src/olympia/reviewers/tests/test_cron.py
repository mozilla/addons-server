from datetime import date

from django.conf import settings

import time_machine

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.constants.promoted import (
    PROMOTED_GROUP_CHOICES,
    PROMOTED_GROUPS,
)
from olympia.reviewers.cron import record_reviewer_queues_counts
from olympia.reviewers.models import NeedsHumanReview, QueueCount
from olympia.reviewers.views import reviewer_tables_registry


class TestQueueCount(TestCase):
    def setUp(self):
        user_factory(pk=settings.TASK_USER_ID)

    def _test_expected_count(self, date):
        # We are recording every queue, plus drilling down in every promoted group
        expected_count = len(reviewer_tables_registry) + len(PROMOTED_GROUPS)
        assert QueueCount.objects.filter(date=date).count() == expected_count

    def test_empty(self):
        with time_machine.travel('2024-12-03', tick=False):
            expected_date = date.today()
            record_reviewer_queues_counts()

        self._test_expected_count(expected_date)

        for metric in QueueCount.objects.all():
            assert metric.date == expected_date
            assert metric.name
            assert metric.value == 0

    def test_basic(self):
        addon_factory()
        addon_factory(
            needshumanreview_kw={'reason': NeedsHumanReview.REASONS.UNKNOWN},
        )
        addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        )
        self.addon_recommended_1 = addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
            },
        )
        addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
            },
        )
        addon_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            promoted_id=PROMOTED_GROUP_CHOICES.NOTABLE,
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
            },
        )

        with time_machine.travel('2024-12-03', tick=False):
            expected_date = date.today()
            record_reviewer_queues_counts()

        self._test_expected_count(expected_date)

        metric = QueueCount.objects.get(name='queue_extension')
        assert metric.date == expected_date
        assert metric.value == 5

        metric = QueueCount.objects.get(name='queue_extension/recommended')
        assert metric.date == expected_date
        assert metric.value == 2

        metric = QueueCount.objects.get(name='queue_extension/notable')
        assert metric.date == expected_date
        assert metric.value == 1

    def test_twice_same_date_doesnt_override(self):
        self.test_basic()
        self.test_basic()

    def test_twice_different_day(self):
        self.test_basic()
        previous_date = QueueCount.objects.latest('pk').date

        self.addon_recommended_1.current_version.file.update(status=amo.STATUS_APPROVED)
        self.addon_recommended_1.current_version.needshumanreview_set.all()[0].update(
            is_active=False
        )

        with time_machine.travel('2024-12-04', tick=False):
            expected_date = date.today()
            record_reviewer_queues_counts()

        # Previous date records are not affected.
        self._test_expected_count(previous_date)
        assert (
            QueueCount.objects.get(date=previous_date, name='queue_extension').value
            == 5
        )
        assert (
            QueueCount.objects.get(
                date=previous_date, name='queue_extension/recommended'
            ).value
            == 2
        )
        assert (
            QueueCount.objects.get(
                date=previous_date, name='queue_extension/notable'
            ).value
            == 1
        )

        # New date records
        self._test_expected_count(expected_date)

        # One fewer add-on in the queue.
        assert (
            QueueCount.objects.get(date=expected_date, name='queue_extension').value
            == 4
        )

        # One fewer add-on in the queue that was recommended.
        assert (
            QueueCount.objects.get(
                date=expected_date, name='queue_extension/recommended'
            ).value
            == 1
        )

        # No changes to notable.
        assert (
            QueueCount.objects.get(
                date=expected_date, name='queue_extension/notable'
            ).value
            == 1
        )
