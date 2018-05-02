"""
Management utility to create superusers.

Inspired by django.contrib.auth.management.commands.createsuperuser.
(http://bit.ly/2cTgsNV)
"""
import json
import os

from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.management.commands.createsuperuser import (
    Command as CreateSuperUserCommand)
from django.core import exceptions
from django.core.management.base import CommandError
from django.utils.six.moves import input
from django.utils.text import capfirst

from olympia.api.models import APIKey
from olympia.users.models import Group, GroupUser


class Command(CreateSuperUserCommand):
    help = '''
Used to create a superuser. This is similar to django's createsuperuser
command but it doesn't support any arguments. This will prompt for a username
and email address and that's it.
'''
    # TODO: Use `UserProfile.REQUIRED_FIELDS`? Not sure why `username`
    # isn't in there...
    required_fields = ('username', 'email')

    def add_arguments(self, parser):
        parser.add_argument(
            '--add-to-supercreate-group',
            action='store_true',
            dest='add_to_supercreate_group',
            default=False,
            help='Assign the user to the Accounts:SuperCreate group',
        )

        parser.add_argument(
            '--save-api-credentials',
            type=str,
            dest='save_api_credentials',
            default=False,
            help='Saves the generated API credentials into a JSON file',
        )

        parser.add_argument(
            '--hostname',
            type=str,
            dest='hostname',
            default=False,
            help='Sets the hostname of the credentials JSON file',
        )

        parser.add_argument(
            '--fxa_id',
            type=str,
            dest='fxa_id',
            default=False,
            help='Adds an fxa id to the superuser',
        )

        CreateSuperUserCommand.add_arguments(self, parser)

    def handle(self, *args, **options):
        user_data = {}

        # Do quick and dirty validation if --noinput
        if not options.get('interactive', True):
            # Stolen from django's `createsuperuser` implementation.
            try:
                for field_name in self.required_fields:
                    if options.get(field_name, None):
                        field = self.UserModel._meta.get_field(field_name)
                        user_data[field_name] = field.clean(
                            options[field_name], None)
                    else:
                        raise CommandError(
                            'You must use --%s with --noinput.' % field_name)
            except exceptions.ValidationError as exc:
                raise CommandError('; '.join(exc.messages))
        else:
            user_data = {
                field_name: self.get_value(field_name)
                for field_name in self.required_fields
            }

        if options.get('fxa_id', False):
            field = self.UserModel._meta.get_field('fxa_id')
            user_data['fxa_id'] = field.clean(
                options['fxa_id'], None)

        user = get_user_model()._default_manager.create_superuser(**user_data)

        if options.get('add_to_supercreate_group', False):
            user.read_dev_agreement = datetime.utcnow()
            user.save(update_fields=('read_dev_agreement',))

            group, _ = Group.objects.get_or_create(
                rules='Accounts:SuperCreate',
                defaults={'name': 'Account Super Creators'})
            GroupUser.objects.create(user=user, group=group)
            apikey = APIKey.new_jwt_credentials(user=user)

            self.stdout.write(json.dumps({
                'username': user.username,
                'email': user.email,
                'api-key': apikey.key,
                'api-secret': apikey.secret,
                'fxa-id': user.fxa_id,
            }))

        if options.get('save_api_credentials', False):
            hostname = options.get('hostname', os.environ.get(
                'PYTEST_BASE_URL', False))
            # json object for variables file
            # set hostname to stdin or env variable

            if hostname:
                credentials = {
                    'api': {
                        hostname: {
                            'username': user.username,
                            'jwt_issuer': apikey.key,
                            'jwt_secret': apikey.secret,
                        }
                    }
                }

                # write to json file
                with open(options.get('save_api_credentials'), 'w') as outfile:
                    json.dump(credentials, outfile, indent=2)

    def get_value(self, field_name):
        field = get_user_model()._meta.get_field(field_name)
        value = None
        while value is None:
            raw_value = input('{}: '.format(capfirst(field_name)))
            try:
                value = field.clean(raw_value, None)
            except exceptions.ValidationError as exc:
                self.stderr.write('Error: {}'.format('; '.join(exc.messages)))
                value = None
        return value
