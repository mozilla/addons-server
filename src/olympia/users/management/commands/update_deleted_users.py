from django.core.management.base import BaseCommand

from olympia.users.models import UserProfile


class Command(BaseCommand):
    """Make sure we are correctly anonymizing deleted users."""

    help = 'Re-anonymize already deleted users.'

    def handle(self, *args, **options):
        for user in UserProfile.objects.filter(deleted=True):
            user.delete()

        self.stdout.write(
            'Done, all anonymized users got re-anonymized again. '
            'New fields got deleted/anonymized now.'
        )
