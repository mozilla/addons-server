from collections import defaultdict

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.abuse.models import AbuseReport, CinderJob
from olympia.abuse.tasks import handle_already_moderated
from olympia.versions.models import Version


class Command(BaseCommand):
    log = olympia.core.logger.getLogger('z.abuse')

    def handle(self, *args, **options):
        jobs = (
            CinderJob.objects.unresolved()
            .resolvable_in_reviewer_tools()
            .select_related('target_addon___current_version')
            .prefetch_related('appealed_decisions')
        )
        abuse_report_dict = defaultdict(list)
        abuse_reports = list(
            AbuseReport.objects.filter(cinder_job__in=jobs).values_list(
                'reason', 'addon_version', 'cinder_job_id', named=True
            )
        )
        for report in abuse_reports:
            abuse_report_dict[report.cinder_job_id].append(report)

        addon_versions = list(
            # Note this query can over-match Version objects if the version string
            # exists in multiple add-ons (e.g. version "0.1" exists in addon-A and
            # addon-B, but is not reported for addon-A, only for addon-B)
            # - this is somewhat inefficient, but harmless - it just won't be looked
            # up in CinderJob.should_auto_resolve.
            Version.objects.filter(
                addon__in=[job.target_addon for job in jobs],
                version__in=[
                    report.addon_version
                    for report in abuse_reports
                    if report.addon_version
                ],
            ).values_list('addon_id', 'version', 'human_review_date', named=True)
        )
        addon_version_dict = defaultdict(list)
        for version in addon_versions:
            addon_version_dict[version.addon_id].append(version)
        self.stdout.write(f'{len(jobs)} unresolved CinderJobs in reviewer tools')

        for job in jobs:
            job._abusereports = abuse_report_dict.get(job.id, [])
            job._addon_versions = addon_version_dict.get(job.target_addon_id, [])
            if job.should_auto_resolve():
                # if it should be auto resolved, fire a task to resolve it
                self.log.info(
                    'Found job#%s to auto resolve for addon#%s.',
                    job.id,
                    job.target_addon_id,
                )
                handle_already_moderated.delay(job_pk=job.id)
