import datetime

from django.core.management.base import BaseCommand
from django.db.models import Q

import amo
from amo.utils import chunked
from devhub.models import ActivityLog

import mkt.constants.reviewers as rvw
from mkt.reviewers.tasks import _batch_award_points


class Command(BaseCommand):
    help = ('Retroactively award theme reviewer points for all the theme '
            'reviewers done since the Great Theme Migration to amo up to when '
            'we started recording points. MEANT FOR ONE-TIME RUN.')

    def handle(self, *args, **options):
        start_date = datetime.date(2013, 8, 27)

        # Get theme reviews that are approves and rejects from before we started
        # awarding.
        approve = '"action": %s' % rvw.ACTION_APPROVE
        reject = '"action": %s' % rvw.ACTION_REJECT
        al_ids = (ActivityLog.objects.filter(
            Q(_details__contains=approve) | Q(_details__contains=reject),
            action=amo.LOG.THEME_REVIEW.id, created__lte=start_date)
            .values_list('id', flat=True))

        for chunk in chunked(al_ids, 1000):
            # Review and thou shall receive.
            _batch_award_points.delay(chunk)
