from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

import olympia.core.logger

from olympia.access.models import Group, GroupUser
from olympia.users.models import UserProfile


class Command(BaseCommand):
    help = 'Add a new user to a group.'

    log = olympia.core.logger.getLogger('z.users')

    def add_arguments(self, parser):
        parser.add_argument('user', type=unicode, help='User id or email')
        parser.add_argument('group_id', type=int, help='Group id')

    def handle(self, *args, **options):
        do_adduser(options['user'], options['group_id'])

        msg = 'Adding {user} to {group}\n'.format(
            user=options['user'], group=options['group_id']
        )
        self.log.info(msg)
        self.stdout.write(msg)


def do_adduser(user, group):
    try:
        if '@' in user:
            user = UserProfile.objects.get(email=user)
        elif user.isdigit():
            user = UserProfile.objects.get(pk=user)
        else:
            raise CommandError('Unknown input for user.')

        group = Group.objects.get(pk=group)

        GroupUser.objects.create(user=user, group=group)

    except IntegrityError as e:
        raise CommandError('User is already in that group? %s' % e)
    except UserProfile.DoesNotExist:
        raise CommandError('User ({user}) does not exist.'.format(user=user))
    except Group.DoesNotExist:
        raise CommandError(
            'Group ({group}) does not exist.'.format(group=group)
        )
