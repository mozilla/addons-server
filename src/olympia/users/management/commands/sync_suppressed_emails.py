from django.core.management.base import BaseCommand

from olympia.users.tasks import sync_suppressed_emails_task


class Command(BaseCommand):
    """Sync Socket labs suppression list to database."""

    def handle(self, *args, **options):
        sync_suppressed_emails_task.apply()
