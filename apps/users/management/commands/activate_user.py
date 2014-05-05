from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

from apps.access.models import Group, GroupUser
from apps.users.models import UserProfile


class Command(BaseCommand):
    """Activate a registered user, and optionally set it as admin."""
    args = 'email'
    help = 'Activate a registered user by its email.'

    option_list = BaseCommand.option_list + (
        make_option('--set-admin',
                    action='store_true',
                    dest='set_admin',
                    default=False,
                    help='Give superuser/admin rights to the user.'),)

    def handle(self, *args, **options):
        if len(args) != 1:
            raise CommandError('Usage: activate_user [--set-admin] email')

        email = args[0]
        set_admin = options['set_admin']

        try:
            profile = UserProfile.objects.get(email=email)
        except UserProfile.DoesNotExist:
            raise CommandError('User with email %s not found' % email)

        profile.update(confirmationcode='')

        admin_msg = ""
        if set_admin:
            admin_msg = "admin "
            GroupUser.objects.create(user=profile,
                                     group=Group.objects.get(name='Admins'))
        self.stdout.write("Done, you can now login with your %suser" %
                          admin_msg)
