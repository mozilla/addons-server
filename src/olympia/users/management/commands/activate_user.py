from django.core.management.base import BaseCommand, CommandError

from olympia.access.models import Group, GroupUser
from olympia.users.models import UserProfile


class Command(BaseCommand):
    """Activate a registered user, and optionally set it as admin."""

    help = 'Activate a registered user by its email.'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('email')
        parser.add_argument(
            '--set-admin',
            action='store_true',
            dest='set_admin',
            default=False,
            help='Give superuser/admin rights to the user.',
        )

    def handle(self, *args, **options):
        email = options['email']
        set_admin = options['set_admin']

        try:
            profile = UserProfile.objects.get(email=email)
        except UserProfile.DoesNotExist:
            raise CommandError('User with email %s not found' % email)

        admin_msg = ""
        if set_admin:
            admin_msg = "admin "
            GroupUser.objects.create(
                user=profile, group=Group.objects.get(name='Admins')
            )
        self.stdout.write(
            "Done, you can now login with your %suser" % admin_msg
        )
