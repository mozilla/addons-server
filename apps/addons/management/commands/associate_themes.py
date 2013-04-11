from getpass import getpass
from optparse import make_option
from time import time

from django.core.management.base import BaseCommand
from django.db import IntegrityError, connection as django_connection

import MySQLdb as mysql


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
                    dest='commit', help='If yes, then commits the run'),
    )

    def connect(self, **options):
        options = dict([(k, v) for k, v in options.items() if k in
                        ['host', 'db', 'user'] and v])
        options['passwd'] = getpass('MySQL Password: ')
        self.connection = mysql.connect(**options)
        self.cursor = self.connection.cursor()
        self.cursor_z = django_connection.cursor()

    def get_amo_user_id(self, username):
        if username in self.user_ids:
            return self.user_ids[username]

        # Figure out the user's email by looking up username on GP.
        self.cursor.execute('SELECT email FROM users WHERE username = %s',
                            username)
        try:
            email = self.cursor.fetchone()[0].decode('latin1').encode('utf-8')
        except TypeError:
            return

        # Figure out the user's id by looking up email on AMO.
        self.cursor_z.execute('SELECT id FROM users WHERE email = %s', email)
        try:
            pk = self.cursor_z.fetchone()[0]
        except TypeError:
            return

        # Remember this for next time so we can avoid the queries above.
        self.user_ids[username] = pk

        return pk

    def handle(self, *args, **options):
        t_start = time()

        self.connect(**options)

        print "You're running a script to associate themes with their owners!"

        self.user_ids = {}
        self.cursor_z.execute('BEGIN')
        self.cursor_z.execute("""
            SELECT addons.id, addons.slug, personas.author FROM addons
            LEFT OUTER JOIN addons_users ON addons.id = addons_users.addon_id
            LEFT OUTER JOIN users ON addons_users.user_id = users.id
            LEFT OUTER JOIN personas ON addons.id = personas.addon_id
            WHERE addons.addontype_id = 9 AND users.id IS NULL AND
            personas.persona_id != 0
        """)
        themes = self.cursor_z.fetchall()
        count = len(themes)
        i, failed, added, already = 0, 0, 0, 0

        try:
            print 'Found %s unassociated themes :)\n' % count

            for pk, slug, username in themes:
                if not username:
                    continue

                i += 1

                amo_user_id = self.get_amo_user_id(username)
                if not amo_user_id:
                    failed += 1
                    print('\t[ERROR] Could not find AMO user for GP user '
                          '"%s" to associate [%s] %s' % (username, pk, slug))
                    continue

                try:
                    self.cursor_z.execute(
                        'INSERT INTO addons_users (addon_id, user_id, role) '
                        'VALUES (%s, %s, 5)' % (pk, amo_user_id))
                except IntegrityError:
                    already += 1
                    print('\tUser "%s" is already an owner of [%s] %s' %
                          (username, pk, slug))
                else:
                    added += 1
                    print '\tAdded "%s" [%s] as an owner of [%s] %s' % (
                        username, amo_user_id, pk, slug)

                if i % 500 == 0:
                    print 'Committing 500 users (#%s) ...' % i
                    self.cursor_z.execute('COMMIT')
                    self.cursor_z.execute('BEGIN')
        except:
            print 'Error, not committing changes.'
            self.cursor_z.execute('ROLLBACK')
            raise
        else:
            self.cursor_z.execute('COMMIT')

        print '\nDone. Total time: %s seconds' % (time() - t_start)
        print 'Failed: %s. Added: %s. Already: %s.' % (failed, added, already)
