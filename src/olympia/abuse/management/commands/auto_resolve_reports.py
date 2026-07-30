from datetime import date

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.abuse.models import CinderJob
from olympia.abuse.tasks import auto_resolve_job


class Command(BaseCommand):
    log = olympia.core.logger.getLogger('z.abuse')

    def add_arguments(self, parser):
        parser.add_argument(
            '--force-reviewer',
            action='store_true',
            default=False,
            help=(
                'Force auto-resolve of all unresolved CinderJobs handled by reviewers, '
                'skipping should_auto_resolve check',
            ),
        )
        parser.add_argument(
            '--before',
            type=date.fromisoformat,
            default=None,
            help=(
                'Only auto-resolve CinderJobs with reports created before this date '
                '(YYYY-MM-DD)'
            ),
        )

    def handle(self, *args, **options):
        force = options.get('force_reviewer')
        before = options.get('before')
        jobs = (
            CinderJob.objects.filter(decisions__isnull=True)
            .resolvable_in_reviewer_tools()
            .exclude(appealed_decisions__isnull=False)
        )
        if before:
            jobs = jobs.exclude(abusereport__created__gte=before)
        self.stdout.write(f'{jobs.count()} unresolved CinderJobs in reviewer tools')

        for job_id in jobs.values_list('id', flat=True):
            auto_resolve_job.delay(job_pk=job_id, force=force)
