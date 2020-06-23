from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Max

from olympia.reviewers.utils import ReviewHelper
from olympia.versions.models import Version


# Note: this not done in auto_approve.py on purpose: in case somehow
# auto_approve.py would raise an uncaught exception and fail, we still want to
# notify the developers, so a separate command is slightly safer.
class Command(BaseCommand):
    help = 'Notify developers about add-ons that have not been auto-approved'
    WAITING_PERIOD_HOURS = 3  # Wait period before notifying, in hours.

    def fetch_versions_waiting_for_approval_for_too_long(self):
        """
        Return versions that are auto-approvable but have waited long enough
        that we need to notify their developers about the delay.

        Versions are grouped by add-on, only the latest auto-approvable version
        for each add-on is considered ; if a version has been created recently
        enough for a given add-on and not auto-approved, none of its other
        versions will be returned.
        """
        exclude_kwargs = {
            'addon__reviewerflags__notified_about_auto_approval_delay': True
        }
        qs = (
            # Base queryset with auto-approvable versions. Default ordering
            # is reset to make the GROUP BY work.
            Version.objects
                   .auto_approvable()
                   .exclude(**exclude_kwargs)
                   .order_by()
        )
        # Get only the latest version for each add-on from the auto-approvable
        # versions.
        latest_per_addon = qs.values('addon').annotate(latest_pk=Max('pk'))
        # Now that we have the pks of the latest versions waiting for approval
        # for each add-on, we can use that in a subquery and apply the filter
        # to only care about versions that have been waiting long enough.
        maximum_created = datetime.now() - timedelta(
            hours=self.WAITING_PERIOD_HOURS)
        return Version.objects.filter(
            pk__in=latest_per_addon.values('latest_pk'),
            created__lt=maximum_created,
        ).order_by('created')

    def notify_developers(self, version):
        """
        Trigger task sending email notifying developer(s) of the add-on that
        this version hasn't been auto-approved yet.
        """
        helper = ReviewHelper(addon=version.addon, version=version)
        helper.handler.data = {}
        helper.handler.notify_about_auto_approval_delay(version)

    def handle(self, *args, **options):
        qs = self.fetch_versions_waiting_for_approval_for_too_long()
        for version in qs:
            self.notify_developers(version)
