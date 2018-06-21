# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia import amo
from olympia.reviewers.models import AutoApprovalSummary


class Command(BaseCommand):
    help = 'Recalculate post-review weights for unconfirmed auto-approvals.'

    def handle(self, *args, **options):
        qs = AutoApprovalSummary.objects.filter(
            confirmed=False, verdict=amo.AUTO_APPROVED)
        for summary in qs:
            log.info('Recalculating weight for %s', summary)
            old_weight = summary.weight
            summary.calculate_weight()
            if summary.weight != old_weight:
                log.info('Saving weight change (from %d to %d) for %s',
                         old_weight, summary.weight, summary)
                summary.save()
