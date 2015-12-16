from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

import commonware.log

from olympia.access.models import Group, GroupUser
from olympia.users.models import UserProfile


class Command(BaseCommand):
    help = ('Add a new user to a group. Syntax: \n'
            '    ./manage.py addusertogroup <user_id|email> <group_id>')

    log = commonware.log.getLogger('z.users')

    def handle(self, *args, **options):
        try:
            do_adduser(args[0], args[1])

            msg = 'Adding {user} to {group}\n'.format(user=args[0],
                                                      group=args[1])
            self.log.info(msg)
            self.stdout.write(msg)
        except IndexError:
            raise CommandError(self.help)


def do_adduser(user, group):
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

        GroupUser.objects.create(user=user, group=group)

    except IntegrityError, e:
        raise CommandError('User is already in that group? %s' % e)
    except UserProfile.DoesNotExist:
        raise CommandError('User ({user}) does not exist.'.format(user=user))
    except Group.DoesNotExist:
        raise CommandError('Group ({group}) does not exist.'
                           .format(group=group))
