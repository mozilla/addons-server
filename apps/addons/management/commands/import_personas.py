import htmlentitydefs
import os
import re
import uuid
from getpass import getpass
from optparse import make_option
from time import time

from django.core.management.base import BaseCommand
from django.db import (IntegrityError, connection as django_connection,
                       transaction)

import MySQLdb as mysql

from addons import cron
import amo

BIOS_TO_IMPORT = os.environ.get('BIOS', 'bios_to_import.py')


class Command(BaseCommand):
    """
    Import from the personas database:
    `host`: the host of the personas database
    `database`: the personas database, eg: personas
    `commit`: if yes, actually commit the transaction, for any other value, it
              aborts the transaction at the end.
    `users`: migrate user accounts?
    `favorites`: migrate favorites for users?
    """
    option_list = BaseCommand.option_list + (
        make_option('--host', action='store',
                    dest='host', help='The host of MySQL'),
        make_option('--db', action='store',
                    dest='db', help='The database in MySQL'),
        make_option('--user', action='store',
                    dest='user', help='The database user'),
        make_option('--commit', action='store',
                    dest='commit', help='If yes, then commits the run'),
        make_option('--start', action='store', type="int",
                    dest='start', help='An optional offset to start at'),
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
        self.cursor_z = django_connection.cursor()

    def do_import(self, offset, limit, **options):
        self.log('Processing users %s to %s' % (offset, offset + limit))
        for user in self.get_users(limit, offset):
            user = dict(zip(['username', 'display_username', 'md5',
                             'email', 'description'], user))

            for k in ['username', 'description', 'display_username', 'email']:
                user[k] = (user.get(k) or '').decode('latin1').encode('utf-8')

            user['orig-username'] = user['username']

            self.handle_user(user)

    def count_users(self):
        self.cursor.execute('SELECT count(username) from users')
        return self.cursor.fetchone()[0]

    def get_persona_addon_id(self, **kw):
        column, value = kw.items()[0]
        self.cursor_z.execute(
            'SELECT addon_id FROM personas WHERE %s = %%s LIMIT 1' % column,
            value)
        try:
            return self.cursor_z.fetchone()[0]
        except TypeError:
            return 0

    def get_user_id(self, **kw):
        column, value = kw.items()[0]
        self.cursor_z.execute(
            'SELECT id FROM users WHERE %s = %%s LIMIT 1' % column, value)
        try:
            return self.cursor_z.fetchone()[0]
        except TypeError:
            return 0

    def get_users(self, limit, offset):
        self.cursor.execute(
            'SELECT username, display_username, md5, '
            'email, description FROM users ORDER BY username '
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
        profile_id = self.get_user_id(email=user['email'])

        if profile_id:
            self.log(' Ignoring existing user: %s' % user['email'])
            return

        orig_username = user['username']
        if self.get_user_id(username=user['username']):
            user['username'] = user['username'] + '-' + str(time())
            self.log(' Username already taken, so making username: %s'
                     % user['username'])

        self.log(' Creating user for %s' % user['email'])
        note = 'Imported from getpersonas, username: %s' % user['username']
        if orig_username != user['username']:
            note += ' (formerly %s)' % orig_username

        algo, salt, password = user['md5'].split('$')
        # The salt is a bytes string. In get personas it is base64
        # encoded. I'd like to decode here so we don't have to do any
        # more work, but that means MySQL doesn't like the bytes that
        # get written to the column. So we'll have to persist that
        # base64 encoding. Let's add +base64 on to it so we know this in
        # zamboni.
        password = '$'.join([algo + '+base64', salt, password])

        data = {
            'username': user['username'],
            'email': user['email'],
            'password': password,
            'notes': note,
            'bio': user['description']
        }
        try:
            data['bio'] = re.sub('&([^;]+);', lambda m: unichr(htmlentitydefs.name2codepoint[m.group(1)]), data['bio'])
        except:
            data['bio'] = ""

        try:
            # Create UserProfile.
            self.cursor_z.execute("""
                INSERT INTO users (created, modified,
                username, display_name, password, emailhidden, email,
                notes) VALUES (NOW(), NOW(), %(username)s, %(username)s,
                %(password)s, 1, %(email)s, %(notes)s)""", data)
            data['user_id'] = self.cursor_z.lastrowid

            # We'll import the bios one day. It's all good.
            if data['bio']:
                with open(BIOS_TO_IMPORT, 'a') as f:
                    f.write('u = UserProfile.objects.get(id=%(user_id)s)\n'
                            'if not u.bio:\n'
                            '  u.bio = """%(bio)s"""\n'
                            '  u.save()\n'
                            'time.sleep(1)\n\n' % data)

            # Create Django User.
            self.cursor_z.execute("""
                INSERT INTO auth_user (id, username, first_name,
                last_name, email, password, is_active, is_staff,
                is_superuser, date_joined, last_login)
                VALUES (%(user_id)s, %(username)s, '', '',
                %(email)s, %(password)s, 1, 0, 0, NOW(), NOW())""", data)
        except IntegrityError:
            self.log(' Failed creating new user (%s)' % user['email'])

        # Now link up the designers with the profile.
        rows = []
        for persona_id in self.get_designers(user['orig-username']):
            addon_id = self.get_persona_addon_id(persona_id=persona_id[0])
            if addon_id:
                rows.append('(%s, %s, 5)' % (addon_id, data['user_id']))
            else:
                self.log(' Skipping unknown persona (%s) for user (%s)' %
                         (persona_id[0], user['username']))

        if rows:
            values = ', '.join(rows)
            try:
                self.cursor_z.execute("""
                    INSERT INTO addons_users (addon_id, user_id, role)
                    VALUES %s""" % values)
                self.log(' Adding (%s) as owner of (%s) personas' %
                         (user['username'], len(rows)))
            except IntegrityError:
                # Can mean they already own the personas (eg. you've run this
                # script before) or a persona doesn't exist in the db.
                self.log(' Failed adding (%s) as owner of (%s) personas. Rows: %s' %
                         (user['username'], len(rows), values))

        # Now hook up any favorites
        try:
            self.cursor_z.execute(
                'SELECT id FROM collections WHERE author_id = %s', data['user_id'])
            collection_id = self.cursor_z.fetchone()[0]
        except TypeError:
            uuid_ = unicode(uuid.uuid4())
            self.cursor_z.execute("""
                INSERT INTO collections (created, modified, uuid, slug,
                defaultlocale, collection_type, author_id)
                VALUES (NOW(), NOW(), %s, 'favorites', 'en-US', 4, %s)
            """, (uuid_, data['user_id']))
            collection_id = self.cursor_z.lastrowid

        rows = []
        for fav in self.get_favourites(user['orig-username']):
            addon_id = self.get_persona_addon_id(persona_id=fav[0])
            if addon_id:
                rows.append('(NOW(), NOW(), %s, %s, %s)' %
                            (addon_id, collection_id, data['user_id']))
            else:
                self.log(' Skipping unknown favorite (%s) for user (%s)' %
                         (fav[0], user['username']))

        if rows:
            values = ', '.join(rows)
            try:
                self.cursor_z.execute("""
                    INSERT INTO addons_collections
                    (created, modified, addon_id, collection_id, user_id)
                    VALUES %s
                """ % values)
                self.log(' Adding %s favs for user %s' %
                         (len(rows), user['username']))
            except IntegrityError:
                self.log(' Failed to import (%s) favorites for user (%s). Rows: %s' %
                         (len(rows), user['username'], values))

    @transaction.commit_manually
    def handle(self, *args, **options):
        t_total_start = time()

        self.connect(**options)

        self.log("You're running a script to import getpersonas.com to AMO!")

        try:
            count = self.count_users()
            self.log('Found %s users. Grab some coffee and settle in' % count)

            step = 2500
            start = options.get('start', 0)
            self.log("Starting at offset: %s" % start)
            for offset in range(start, count, step):
                t_start = time()
                self.do_import(offset, step, **options)
                self.commit_or_not(options.get('commit'))
                t_average = 1 / ((time() - t_total_start) /
                                 (offset - start + step))
                print "> %.2fs for %s accounts. Averaging %.2f accounts/s" % (
                    time() - t_start, step, t_average)
        except:
            self.log('Error, not committing changes.')
            transaction.rollback()
            raise
        finally:
            self.commit_or_not(options.get('commit'))
            # Let's not do this programmatically with how this script is acting
            #if options.get('commit') == 'yes':
                #self.log("Kicking off cron to reindex personas...")
                #cron.reindex_addons(addon_type=amo.ADDON_PERSONA)

        self.log("Done. Total time: %s seconds" % (time() - t_total_start))
