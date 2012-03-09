from base64 import decodestring
from optparse import make_option
from time import time

from django.core.management.base import BaseCommand

from addons.models import Persona
from bandwagon.models import CollectionAddon
from users.models import UserProfile

import MySQLdb as mysql

from django.db import transaction


class Command(BaseCommand):
    """
    Import from the personas database:
    `task`: the table to import from, eg users
    `host`: the host of the personas database
    `database`: the personas database, eg: personas
    `commit`: if yes, actually commit the transaction, for any other value, it
              aborts the transaction at the end.
    """
    option_list = BaseCommand.option_list + (
        make_option('--task', action='store',
                    dest='task', help='The task to import'),
        make_option('--host', action='store',
                    dest='host', help='The host of MySQL'),
        make_option('--db', action='store',
                    dest='db', help='The database in MySQL'),
        make_option('--user', action='store',
                    dest='user', help='The database user'),
        make_option('--password', action='store',
                    dest='password', help='The database user password'),
        make_option('--commit', action='store',
                    dest='commit', help='If: yes, then commits the run'),
    )

    def log(self, msg):
        print msg

    def connect(self, **options):
        options = dict([(k, v) for k, v in options.items() if k in
                        ['host', 'db', 'user', 'password'] and v])
        self.connection = mysql.connect(**options)
        self.cursor = self.connection.cursor()

    def handle_users(self):
        self.log('Importing users.')
        self.cursor.execute('SELECT count(username) from users')
        k, step = 0, 10
        count = self.cursor.fetchone()[0]
        self.log('Found %s users.' % count)
        for x in range(0, count, step):
            k += step
            self.log('Doing %s to %s' % (x, k))
            self.cursor.execute('SELECT * FROM users ORDER BY username '
                                'LIMIT %s OFFSET %s' % (step, k))
            for user in self.cursor.fetchall():
                self._handle_user(user)

    def handle_designers(self):
        # TODO: bug 726186
        pass

    def handle_images(self):
        # TODO: bug 726190
        pass

    def _handle_user(self, user):
        user = dict(zip(['username', 'display_username', 'md5', 'email',
                         'privs', 'change_code', 'news', 'description'], user))
        for k in ['username', 'display_username', 'email']:
            user[k] = user[k].decode('latin1').encode('utf-8')

        profile = UserProfile.objects.filter(email=user['email'])
        if UserProfile.objects.filter(username=user['username']).exists():
            user['username'] = user['username'] + '-' + time()
            self.log('Username already taken, so making username: %s'
                     % user['username'])

        if profile:
            self.log('Ignoring %s' % user['email'])
        else:
            self.log('Creating user for %s' % user['email'])
            note = 'Imported from personas, username: %s' % user['username']
            algo, salt, password = user['md5'].split('$')
            # The salt is a bytes string. In get personas it is base64
            # encoded. I'd like to decode here so we don't have to do any
            # more work, but that means MySQL doesn't like the bytes that
            # get written to the column. So we'll have to persist that
            # base64 encoding. Let's add +base64 on to it so we know this in
            # zamboni.
            password  = '$'.join([algo + '+base64', salt, password])
            profile = UserProfile.objects.create(username=user['username'],
                                                 email=user['email'],
                                                 password=password,
                                                 notes=note)
            profile.create_django_user()

        # Now sort out any favourites.
        self.cursor.execute('SELECT id FROM favorites WHERE '
                            'username = %s', user['username'])
        favs = self.cursor.fetchall()
        fav = profile.favorites_collection()
        for fav in favs:
            try:
                addon = Persona.objects.get(persona_id=fav[0]).addon
            except Persona.DoesNotExist:
                self.log('Not found fav. %s for user %s' %
                         (fav[0], user['username']))
                continue
            CollectionAddon.objects.create(collection=fav, addon=addon)
            self.log('Adding fav. %s for user %s' % (addon, user['username']))

    @transaction.commit_manually
    def handle(self, *args, **options):
        task = options.get('task')
        task = getattr(self, 'handle_%s' % task, None)
        if not task:
            raise ValueError('Unknown task: %s' % task)

        self.connect(**options)

        try:
            task()
        except:
            self.log('Error, not committing changes.')
            transaction.rollback()
            raise
        finally:
            if options.get('commit'):
                self.log('Committing changes.')
                transaction.commit()
            else:
                self.log('Not committing changes, this is a dry run.')
                transaction.rollback()
