from django.core.management.base import BaseCommand

from olympia.abuse.models import CinderJob


class Command(BaseCommand):
    help = (
        'One-off command to fill CinderJob.target_addon and '
        'CinderJob.resolvable_in_reviewer_tools fields'
    )

    def handle(self, *args, **options):
        jobs = CinderJob.objects.all()

        for job in jobs:
            if abuse_report := job.initial_abuse_report:
                job.target_addon = (
                    # If the abuse report is against a guid, set target_addon
                    # on the job accordingly.
                    abuse_report.guid and abuse_report.target
                )
                job.resolvable_in_reviewer_tools = (
                    # If the abuse report was meant to be handled by reviewers
                    # from the start or it's been escalated, set
                    # resolvable_in_reviewer_tools accordingly.
                    abuse_report.is_handled_by_reviewers
                    or job.decision_action
                    == CinderJob.DECISION_ACTIONS.AMO_ESCALATE_ADDON
                )
                job.save()
