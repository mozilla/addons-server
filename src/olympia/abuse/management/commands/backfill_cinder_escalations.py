from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.abuse.models import ContentDecision
from olympia.abuse.tasks import handle_escalate_action
from olympia.constants.abuse import DECISION_ACTIONS


class Command(BaseCommand):
    log = olympia.core.logger.getLogger('z.abuse')

    def handle(self, *args, **options):
        qs = ContentDecision.objects.filter(
            action=DECISION_ACTIONS.AMO_ESCALATE_ADDON,
            cinder_job__forwarded_to_job__isnull=True,
            cinder_job__isnull=False,
        )
        for decision in qs:
            handle_escalate_action.delay(job_pk=decision.cinder_job.pk)
