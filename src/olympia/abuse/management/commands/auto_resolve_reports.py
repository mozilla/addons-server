from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.abuse.models import CinderJob
from olympia.abuse.tasks import auto_resolve_job


class Command(BaseCommand):
    log = olympia.core.logger.getLogger('z.abuse')

    def handle(self, *args, **options):
        job_ids = (
            CinderJob.objects.unresolved().resolvable_in_reviewer_tools()
        ).values_list('id', flat=True)
        self.stdout.write(f'{len(job_ids)} unresolved CinderJobs in reviewer tools')

        for job_id in job_ids:
            auto_resolve_job.delay(job_pk=job_id)
