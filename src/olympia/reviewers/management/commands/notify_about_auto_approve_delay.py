from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

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
        """
        waiting_period = datetime.now() - timedelta(
            hours=self.WAITING_PERIOD_HOURS)
        exclude_kwargs = {
            'addon__addonreviewerflags__notified_about_auto_approval_delay':
                True
        }
        return (
            Version.objects
                   .auto_approvable()
                   .filter(created__lt=waiting_period)
                   .exclude(**exclude_kwargs)
                   .order_by('created')
                   .distinct()
        )

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
