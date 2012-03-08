from getpass import getpass
from optparse import make_option
from time import time

from django.core.management.base import BaseCommand
from django.db import transaction

import MySQLdb as mysql

from addons.models import Persona
from bandwagon.models import CollectionAddon
from users.models import UserProfile, PersonaAuthor


class Command(BaseCommand):
    """
    Import from the personas database:
    `host`: the host of the personas database
    `database`: the personas database, eg: personas
    `commit`: if yes, actually commit the transaction, for any other value, it
              aborts the transaction at the end.
    """
    option_list = BaseCommand.option_list + (
        make_option('--host', action='store',
                    dest='host', help='The host of MySQL'),
        make_option('--db', action='store',
                    dest='db', help='The database in MySQL'),
        make_option('--user', action='store',
                    dest='user', help='The database user'),
        make_option('--commit', action='store',
                    dest='commit', help='If: yes, then commits the run'),
    )

    def log(self, msg):
        print msg

    def connect(self, **options):
        options = dict([(k, v) for k, v in options.items() if k in
                        ['host', 'db', 'user'] and v])
        options['passwd'] = getpass('MySQL Password: ')
        self.connection = mysql.connect(**options)
        self.cursor = self.connection.cursor()

    def do_import(self):
        self.log('Importing users.')
        count = self.count_users()
        k, step = 0, 10
        self.log('Found %s users.' % count)
        for x in range(0, count, step):
            k += step
            self.log('Doing %s to %s' % (x, k))
            for user in self.get_users(step, k):
                self.handle_user(user)

    def count_users(self):
        self.cursor.execute('SELECT count(username) from users')
        return self.cursor.fetchone()[0]

    def get_users(self, limit, offset):
        self.cursor.execute('SELECT * FROM users ORDER BY username '
                            'LIMIT %s OFFSET %s' % (limit, offset))
        return self.cursor.fetchall()

    def get_designers(self, author):
        self.cursor.execute('SELECT id FROM personas WHERE author = %s',
                            author)
        return self.cursor.fetchall()

    def handle_images(self):
        # TODO: bug 726190
        pass

    def get_favourites(self, username):
        self.cursor.execute('SELECT id FROM favorites WHERE '
                            'username = %s', username)
        return self.cursor.fetchall()

    def handle_user(self, user):
        user = dict(zip(['username', 'display_username', 'md5', 'email',
                         'privs', 'change_code', 'news', 'description'], user))

        for k in ['username', 'description', 'display_username', 'email']:
            user[k] = user[k].decode('latin1').encode('utf-8')

        profile = UserProfile.objects.filter(email=user['email'])
        user['orig-username'] = user['username']

        if profile:
            self.log('Ignoring %s' % user['email'])
        else:
            if UserProfile.objects.filter(username=user['username']).exists():
                user['username'] = user['username'] + '-' + str(time())
                self.log('Username already taken, so making username: %s'
                         % user['username'])

            self.log('Creating user for %s' % user['email'])
            note = 'Imported from personas, username: %s' % user['username']
            algo, salt, password = user['md5'].split('$')
            # The salt is a bytes string. In get personas it is base64
            # encoded. I'd like to decode here so we don't have to do any
            # more work, but that means MySQL doesn't like the bytes that
            # get written to the column. So we'll have to persist that
            # base64 encoding. Let's add +base64 on to it so we know this in
            # zamboni.
            password = '$'.join([algo + '+base64', salt, password])
            profile = UserProfile.objects.create(username=user['username'],
                                                 email=user['email'],
                                                 bio=user['description'],
                                                 password=password,
                                                 notes=note)
            profile.create_django_user()

        # Now sort out any favourites.
        for fav in self.get_favourites(user['orig-username']):
            try:
                addon = Persona.objects.get(persona_id=fav[0]).addon
            except Persona.DoesNotExist:
                self.log('Not found fav. %s for user %s' %
                         (fav[0], user['username']))
                continue
            CollectionAddon.objects.create(addon=addon,
                    collection=profile.favorites_collection())
            self.log('Adding fav. %s for user %s' % (addon, user['username']))

        # Now link up the designers with the profile.
        for persona_id in self.get_designers(user['orig-username']):
            try:
                persona = Persona.objects.get(persona_id=persona_id[0])
            except Persona.DoesNotExist:
                self.log('Not found persona %s for user %s' %
                         (persona_id[0], user['username']))
                continue
            PersonaAuthor.objects.create(persona=persona, author=profile)
            self.log('Adding PersonAuthor for persona %s for user %s' %
                     (user['username'], persona))

    @transaction.commit_manually
    def handle(self, *args, **options):
        self.connect(**options)

        try:
            self.do_import()
        except:
            self.log('Error, not committing changes.')
            transaction.rollback()
            raise
        finally:
            if options.get('commit') == 'yes':
                self.log('Committing changes.')
                transaction.commit()
            else:
                self.log('Not committing changes, this is a dry run.')
                transaction.rollback()
