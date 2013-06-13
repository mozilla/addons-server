from getpass import getpass
from optparse import make_option
from time import time

from django.core.management.base import BaseCommand
from django.db import IntegrityError, connection as django_connection

import MySQLdb as mysql

from users.models import UserProfile


class Command(BaseCommand):
    """
    Import from the personas database:
    `host`: the host of the personas database
    `database`: the personas database, eg: personas
    `user`: the user of the personas database
    """
    option_list = BaseCommand.option_list + (
        make_option('--host', action='store',
                    dest='host', help='The host of MySQL'),
        make_option('--db', action='store',
                    dest='db', help='The database in MySQL'),
        make_option('--user', action='store',
                    dest='user', help='The database user'),
    )

    def connect(self, **options):
        options = dict([(k, v) for k, v in options.items() if k in
                        ['host', 'db', 'user'] and v])
        options['passwd'] = getpass('MySQL Password: ')
        self.connection = mysql.connect(**options)
        self.cursor = self.connection.cursor()
        self.cursor_z = django_connection.cursor()
        self.users = {}
        self.addons = {}

    def count_favorites(self):
        self.cursor.execute('SELECT count(username) FROM favorites')
        return self.cursor.fetchone()[0]

    def get_favorite_collection(self, collection_id, addon_id):
        self.cursor_z.execute('SELECT id FROM addons_collections '
                              'WHERE collection_id = %s AND addon_id = %s '
                              'LIMIT 1', (collection_id, addon_id))
        try:
            return self.cursor_z.fetchone()[0]
        except TypeError:
            return None

    def get_user_by_gp_username(self, gp_username):
        if gp_username not in self.users:
            self.cursor.execute('SELECT email FROM users WHERE username = %s',
                                gp_username)
            email = self.cursor.fetchone()[0]
            try:
                profile = UserProfile.objects.get(email=email)
                self.users[gp_username] = (profile,
                                           profile.favorites_collection().id)
            except UserProfile.DoesNotExist:
                print('[ERROR] Could not find user with GP username "%s"' %
                      gp_username)
                self.users[gp_username] = None, None

        profile = self.users.get(gp_username)

        return profile

    def get_addon_id_from_persona_id(self, persona_id):
        if persona_id not in self.addons:
            self.cursor_z.execute(
                'SELECT addon_id FROM personas WHERE persona_id = %s',
                persona_id)
            try:
                self.addons[persona_id] = self.cursor_z.fetchone()[0]
            except:
                print('[ERROR] Could not find add-on with persona_id "%s"' %
                      persona_id)
                self.addons[persona_id] = None

        addon_id = self.addons.get(persona_id)

        return addon_id

    def do_import(self, limit, offset):
        added, ignored, errored = 0, 0, 0

        self.cursor.execute(
            'SELECT username, id, added FROM favorites '
            'ORDER BY username, id LIMIT %s OFFSET %s' % (limit, offset))
        favorites = self.cursor.fetchall()

        for gp_username, persona_id, date_added in favorites:
            profile, faves_id = self.get_user_by_gp_username(gp_username)
            if not profile:
                print('[ERROR] Could not add favourite "%s" because of bad '
                      'username "%s"' % (persona_id, gp_username))
                errored += 1
                continue

            addon_id = self.get_addon_id_from_persona_id(persona_id)

            if not addon_id:
                print('[ERROR] Could not add favourite "%s" because of bad '
                      'persona_id' % persona_id)
                errored += 1
                continue

            coll = self.get_favorite_collection(collection_id=faves_id,
                                                addon_id=addon_id)
            if coll:
                print '[IGNORED] Favourite already exists: %s' % coll
                ignored += 1
                continue

            data = {
                'date_added': date_added,
                'addon_id': addon_id,
                'persona_id': persona_id,
                'collection_id': faves_id,
                'user_id': profile.id
            }

            try:
                self.cursor_z.execute("""
                    INSERT INTO addons_collections
                    (created, modified, addon_id, collection_id, user_id)
                    VALUES (%(date_added)s, %(date_added)s, %(addon_id)s,
                            %(collection_id)s, %(user_id)s)
                """, data)
                print '[ADDED] Favourite added: %s' % data
                added += 1
            except IntegrityError, e:
                print '[ERROR] Could not add favourite: %s\n%s' % (data, e)
                errored += 1

        return added, ignored, errored

    def handle(self, *args, **options):
        t_total_start = time()

        self.connect(**options)

        print "You're running a script to associate more favourites!"

        total_added, total_ignored, total_errored = 0, 0, 0

        count = self.count_favorites()

        print 'Found %s users. Grab some tea and chillax, bro.' % count

        step = 2500
        start = options.get('start', 0)
        print 'Starting at offset: %s' % start
        for offset in xrange(start, count, step):
            t_start = time()

            added, ignored, errored = self.do_import(offset, step)
            total_added += added
            total_ignored += ignored
            total_errored += errored

            t_average = (1 / ((time() - t_total_start) /
                              (offset - start + step)))
            print "> %.2fs for %s favourites. Averaging %.2f favourites/s" % (
                time() - t_start, step, t_average)

        print '\nDone. Total time: %s seconds' % (time() - t_start)
        print 'Favourites added: %s' % added
        print 'Bad favourites: %s' % errored
        print 'Already favourited: %s' % ignored
