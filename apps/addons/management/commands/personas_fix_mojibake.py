from getpass import getpass
from optparse import make_option
from time import time

from django.core.management.base import BaseCommand
from django.db import (IntegrityError, connection as django_connection,
                       transaction)

import MySQLdb as mysql

def debake(s):
    for c in s:
        try:
            yield c.encode('windows-1252')
        except UnicodeEncodeError:
            yield c.encode('latin-1')


class Command(BaseCommand):
    """
    Consult the personas database to find and fix mangled descriptions.
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
        options['charset'] = 'latin1'
        options['use_unicode'] = False
        if options['host'][0] == '/':
            options['unix_socket'] = options['host']
            del options['host']
        self.connection = mysql.connect(**options)
        self.cursor = self.connection.cursor()
        self.cursor_z = django_connection.cursor()

    def do_fix(self, offset, limit, **options):
        self.log('Processing themes %s to %s' % (offset, offset + limit))
        ids = []
        descs = []
        for theme in self.get_themes(limit, offset):
            if max(theme[1]) > u'\x7f':
                try:
                    descs.append(''.join(debake(theme[1])))
                    ids.append(theme[0])
                except UnicodeEncodeError:
                    # probably already done?
                    print "skipped", theme[0]
            else:
                print "clean", theme[0]
        if ids:
            targets = self.find_needed_fixes(ids, descs)
            self.fix_descs(targets)

    def find_needed_fixes(self, ids, descs):
        original_descs = self.get_original_descs(ids)
        for id, d, original_d in zip(ids, descs, original_descs):
            if d == original_d:
                yield id, d

    def get_original_descs(self, ids):
        qs = ', '.join(['%s'] * len(ids))
        self.cursor.execute("SELECT description from personas where id in (%s)" % qs, ids)
        return (x[0] for x in self.cursor.fetchall())

    def fix_descs(self, targets):
        for id, desc in targets:
            try:
                desc.decode('utf-8')
                print "FIX", id
            except UnicodeDecodeError:
                print "SKIPPED", id
                continue
            self.cursor_z.execute(
                'UPDATE translations AS t, personas AS p SET t.localized_string = %s, '
                't.localized_string_clean = NULL '
                'WHERE t.id = p.description AND p.persona_id = %s', [desc, id])

    def count_themes(self):
        self.cursor_z.execute('SELECT count(persona_id) from personas')
        return self.cursor_z.fetchone()[0]

    def get_themes(self, limit, offset):
        self.cursor_z.execute(
            'SELECT p.persona_id, t.localized_string from personas as p, '
            'translations as t where t.id = p.description and '
            't.localized_string != "" LIMIT %s OFFSET %s' % (limit, offset))
        return self.cursor_z.fetchall()

    @transaction.commit_manually
    def handle(self, *args, **options):
        t_total_start = time()

        self.connect(**options)

        self.log(
            "Fixing mojibake in theme descriptions. Think these mangled "
            "strings are bad? Have a look at "
            "https://en.wikipedia.org/wiki/File:Letter_to_Russia"
            "_with_krokozyabry.jpg")

        try:
            count = self.count_themes()
            self.log("Found %s themes. Hope you're not in a hurry" % count)

            step = 2500
            start = options.get('start', 0)
            self.log("Starting at offset: %s" % start)
            for offset in range(start, count, step):
                t_start = time()
                self.do_fix(offset, step, **options)
                self.commit_or_not(options.get('commit'))
                t_average = 1 / ((time() - t_total_start) /
                                 (offset - start + step))
                print "> %.2fs for %s themes. Averaging %.2f themes/s" % (
                    time() - t_start, step, t_average)
        except:
            self.log('Error, not committing changes.')
            transaction.rollback()
            raise
        finally:
            self.commit_or_not(options.get('commit'))

        self.log("Done. Total time: %s seconds" % (time() - t_total_start))
