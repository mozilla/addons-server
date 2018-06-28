from django.core.management.base import BaseCommand, CommandError

import olympia.core.logger

from olympia.access.models import Group, GroupUser
from olympia.users.models import UserProfile


class Command(BaseCommand):
    help = ('Remove a user from a group.')

    log = olympia.core.logger.getLogger('z.users')

    def add_arguments(self, parser):
        parser.add_argument('user', type=unicode, help='User id or email')
        parser.add_argument('group_id', type=int, help='Group id')

    def handle(self, *args, **options):
        do_removeuser(options['user'], options['group_id'])

        msg = 'Removing {user} from {group}\n'.format(
            user=options['user'], group=options['group_id'])
        self.log.info(msg)
        self.stdout.write(msg)


def do_removeuser(user, group):
    try:
        if '@' in user:
            user = UserProfile.objects.get(email=user)
        elif user.isdigit():
            user = UserProfile.objects.get(pk=user)
        else:
            raise CommandError('Unknown input for user.')

        group = Group.objects.get(pk=group)

        # Doesn't actually check if the user was in the group or not.
        GroupUser.objects.filter(user=user, group=group).delete()
    except UserProfile.DoesNotExist:
        raise CommandError('User ({user}) does not exist.'.format(user=user))
    except Group.DoesNotExist:
        raise CommandError('Group ({group}) does not exist.'
                           .format(group=group))
