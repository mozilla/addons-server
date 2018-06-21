# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.reviewers.models import ReviewerScore


# The note we're going to add to the ReviewerScore this command creates to be
# able to find them later.
MANUAL_NOTE = 'Retroactively awarded for past post/content review approval.'


class Command(BaseCommand):
    help = 'Retroactively award points for past post/content review approvals'

    def handle(self, *args, **options):
        self.award_all_points_for_action(
            amo.LOG.APPROVE_CONTENT, content_review=True)
        self.award_all_points_for_action(
            amo.LOG.CONFIRM_AUTO_APPROVED, content_review=False)

    def award_all_points_for_action(self, action, content_review=False):
        for activity_log in ActivityLog.objects.filter(action=action.id):
            user = activity_log.user
            try:
                addon = activity_log.arguments[0]
                version = activity_log.arguments[1]
            except IndexError:
                log.error('ActivityLog %d is missing one or more arguments',
                          activity_log.pk)
                continue

            # If there is already a score recorded in the database for this
            # event, with our special note, it means we already processed it
            # somehow (maybe we ran the script twice...), so ignore it.
            # Otherwise award the points!
            event = ReviewerScore.get_event(
                addon, amo.STATUS_PUBLIC, version=version,
                post_review=True, content_review=content_review)
            if not ReviewerScore.objects.filter(
                    user=user, addon=addon, note_key=event,
                    note=MANUAL_NOTE).exists():
                ReviewerScore.award_points(
                    user, addon, amo.STATUS_PUBLIC,
                    version=version, post_review=True,
                    content_review=content_review, extra_note=MANUAL_NOTE)
            else:
                log.error('Already awarded points for "%s" action on %s %s',
                          action.short, addon, version)
                continue
