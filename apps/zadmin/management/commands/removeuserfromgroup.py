from django.core.management.base import BaseCommand, CommandError

import commonware.log

from access.models import Group, GroupUser
from users.models import UserProfile


class Command(BaseCommand):
    help = ('Remove a user from a group. Syntax: \n'
            '    ./manage.py removeuserfromgroup <user_id|email> <group_id>')

    log = commonware.log.getLogger('z.users')

    def handle(self, *args, **options):
        try:
            do_removeuser(args[0], args[1])

            msg = 'Removing {user} from {group}\n'.format(user=args[0],
                                                          group=args[1])
            self.log.info(msg)
            self.stdout.write(msg)
        except IndexError:
            raise CommandError(self.help)


def do_removeuser(user, group):
    try:
        if '@' in user:
            user = UserProfile.objects.get(email=user)
        elif user.isdigit():
            user = UserProfile.objects.get(pk=user)
        else:
            raise CommandError('Unknown input for user.')

        if group.isdigit():
            group = Group.objects.get(pk=group)
        else:
            raise CommandError('Group must be a valid ID.')

        # Doesn't actually check if the user was in the group or not.
        GroupUser.objects.filter(user=user, group=group).delete()
        # Help django-cache-machine invalidate its cache (it has issues with
        # M2Ms).
        Group.objects.invalidate(*user.groups.all())

    except UserProfile.DoesNotExist:
        raise CommandError('User ({user}) does not exist.'.format(user=user))
    except Group.DoesNotExist:
        raise CommandError('Group ({group}) does not exist.'
                           .format(group=group))
