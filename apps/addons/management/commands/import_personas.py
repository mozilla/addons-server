from getpass import getpass
from optparse import make_option
from time import time

from django.core.management.base import BaseCommand
from django.db import transaction

import MySQLdb as mysql

from addons import cron
from addons.models import Persona, AddonUser
import amo
from bandwagon.models import CollectionAddon
from users.models import UserProfile


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

    def commit_or_not(self, gogo):
        if gogo == 'yes':
            self.log('Committing changes.')
            transaction.commit()
        else:
            self.log('Not committing changes, this is a dry run.')
            transaction.rollback()


    def connect(self, **options):
        options = dict([(k, v) for k, v in options.items() if k in
                        ['host', 'db', 'user'] and v])
        options['passwd'] = getpass('MySQL Password: ')
        self.connection = mysql.connect(**options)
        self.cursor = self.connection.cursor()

    def do_import(self, offset, limit):
        self.log('Importing users %s to %s' % (offset, offset+limit))
        for user in self.get_users(limit, offset):
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

    def get_favourites(self, username):
        self.cursor.execute('SELECT id FROM favorites WHERE '
                            'username = %s', username)
        return self.cursor.fetchall()

    def handle_user(self, user):
        user = dict(zip(['username', 'display_username', 'md5', 'email',
                         'privs', 'change_code', 'news', 'description'], user))

        for k in ['username', 'description', 'display_username', 'email']:
            user[k] = (user.get(k) or '').decode('latin1').encode('utf-8')

        profile = UserProfile.objects.filter(email=user['email'])
        user['orig-username'] = user['username']

        if profile.exists():
            self.log(' Ignoring existing user: %s' % user['email'])
            profile = profile[0]
        else:
            if UserProfile.objects.filter(username=user['username']).exists():
                user['username'] = user['username'] + '-' + str(time())
                self.log(' Username already taken, so making username: %s'
                         % user['username'])

            self.log(' Creating user for %s' % user['email'])
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
                self.log('  Not found fav. %s for user %s' %
                         (fav[0], user['username']))
                continue
            CollectionAddon.objects.create(addon=addon,
                    collection=profile.favorites_collection())
            self.log('  Adding fav. %s for user %s' % (addon, user['username']))

        # Now link up the designers with the profile.
        for persona_id in self.get_designers(user['orig-username']):
            try:
                persona = Persona.objects.get(persona_id=persona_id[0])
            except Persona.DoesNotExist:
                self.log('  Not found persona %s for user %s' %
                         (persona_id[0], user['username']))
                continue
            AddonUser.objects.create(addon=persona.addon, user=profile,
                                     listed=True)
            self.log('  Adding PersonAuthor for persona %s for user %s' %
                     (user['username'], persona))

    @transaction.commit_manually
    def handle(self, *args, **options):
        t_total_start = time()

        self.connect(**options)

        self.log("You're running a script to import getpersonas.com to AMO!")
        self.log("Grab some coffee and settle in.")

        try:
            count = self.count_users()
            self.log('Going to import %s users.' % count)

            step = 30
            for offset in range(0, count, step):
                t_start = time()
                self.do_import(offset, step)
                self.commit_or_not(options.get('commit'))
                t_average = 1 / ((time()- t_total_start) / (offset + step))
                print "> %.2fs for %s accounts. Averaging %.2f accounts/s" % (
                        time() - t_start, step, t_average)
        except:
            self.log('Error, not committing changes.')
            transaction.rollback()
            raise
        finally:
            self.commit_or_not(options.get('commit'))
            if options.get('commit') == 'yes':
                self.log("Kicking off cron to reindex personas...")
                cron.reindex_addons(addon_type=amo.ADDON_PERSONA)

        self.log("Done. Total time: %s seconds" % (time() - t_total_start))
