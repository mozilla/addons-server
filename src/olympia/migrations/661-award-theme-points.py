#!/usr/bin/env python

import datetime

from django.db.models import Q

import mkt.constants.reviewers as rvw

from amo.utils import chunked
from devhub.models import ActivityLog
from mkt.reviewers.tasks import _batch_award_points

from olympia import amo


def run():
    """
    Retroactively award theme reviewer points for all the theme
    reviewers done since the Great Theme Migration to amo up to
    when we started recording points.
    """
    start_date = datetime.date(2013, 8, 27)

    # Get theme reviews that are approves and rejects from before we started
    # awarding.
    approve = '"action": %s' % rvw.ACTION_APPROVE
    reject = '"action": %s' % rvw.ACTION_REJECT
    al = ActivityLog.objects.filter(
        Q(_details__contains=approve) | Q(_details__contains=reject),
        action=amo.LOG.THEME_REVIEW.id,
        created__lte=start_date,
    )

    for chunk in chunked(al, 50):
        # Review and thou shall receive.
        _batch_award_points.delay(chunk)
