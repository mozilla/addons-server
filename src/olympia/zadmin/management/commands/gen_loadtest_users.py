import os
from datetime import datetime
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

from apps.users.models import UserProfile


class Command(BaseCommand):
    help = 'Generate some fake users that can be used for load testing.'

    option_list = BaseCommand.option_list + (
        make_option(
            '--total',
            action='store',
            type='int',
            default=10,
            help='Total number of users to generate. Default: %default.'),
        make_option(
            '--file-dest',
            action='store',
            default=os.getcwd(),
            help='Directory to write user/pass file to. Default: %default.'),
    )

    def handle(self, *args, **options):
        fn = os.path.join(options['file_dest'], 'loadtest-users.txt')
        if os.path.exists(fn):
            raise CommandError(
                'User file exists: {}. Delete or move it first.'.format(fn))
        group_id = os.urandom(3).encode('hex')

        with open(fn, 'w') as user_file:
            print 'About to generate {} users; prefix={}'.format(
                options['total'], group_id)
            for index in range(options['total']):
                user_id = '{}-{}'.format(group_id, index)
                username = 'loadtest-{}'.format(user_id)
                email = '{}@addons.mozilla.org'.format(username)
                password = os.urandom(16).encode('hex')

                user = UserProfile.objects.create(
                    username=username,
                    email=email,
                    display_name='Loadtest McTester {}'.format(user_id),
                    is_verified=True,
                    confirmationcode='',
                    notes='auto-generated for load testing',
                    read_dev_agreement=datetime.now())
                user.set_password(password)
                user.save()

                user_file.write('{}:{}\n'.format(email, password))

        print ('Wrote user credentials to {}'
               .format(user_file.name.replace(os.getcwd(), '.')))
