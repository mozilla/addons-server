from django.core.management.base import BaseCommand

from olympia.users.tasks import sync_blocked_emails


class Command(BaseCommand):
    """Sync Socket labs suppression list to database."""

    def handle(self, *args, **options):
        sync_blocked_emails.apply()
