from datetime import datetime
import traceback

from django.core.management.base import BaseCommand
from django.db import connection, transaction


MAX_DUPS = 16

class Command(BaseCommand):
    """
    Renames user accounts whose usernames would conflict with other
    users in a case-insensitive regime.
    """

    def log(self, msg):
        print '[%s]' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg

    @transaction.commit_manually
    def handle(self, *args, **options):
        cursor = connection.cursor()

        # Link orphaned `auth_user` rows created in getpersonas # migration
        # to their `users` rows, by email.
        self.log('Linking orphaned `auth_user` records')
        cursor.execute('''
            UPDATE
                auth_user AS au,
                users AS u
            SET
                u.user_id = au.id
            WHERE
                u.user_id IS NULL
                AND au.email = u.email
        ''')
        self.log('%d rows updated' % cursor.rowcount)

        # Rename username field to guaranteed-unique name based on PK.
        # Usernames migrated from Remora are already UUIDs. Usernames
        # for users created on zamboni are whatever the username was
        # when the account was created. They've never been updated for
        # username changes.
        self.log('Renaming `auth_user` records to guaranteed-unique IDs')
        cursor.execute('''
            UPDATE IGNORE
                auth_user
            SET
                username = CONCAT('uid-', id)
        ''')
        self.log('%d rows updated' % cursor.rowcount)

        rows = None
        try:
            # Create a temporary table to hold usernames and check for
            # conflicts.
            cursor.execute('''
                CREATE TEMPORARY TABLE usernames (
                    username varchar(255) PRIMARY KEY,
                    user_id int(11) UNSIGNED
                ) DEFAULT CHARSET = utf8
            ''')

            self.log('Populating `usernames` table')
            cursor.execute('''
                INSERT INTO
                    usernames (username, user_id)
                SELECT
                    u.username, u.id
                FROM
                    users AS u
                ORDER BY
                    u.created, u.id
                ON DUPLICATE KEY UPDATE
                    username = usernames.username
            ''')
            self.log('%d rows inserted' % cursor.rowcount)

            # Get a list of users with clashing usernames who don't have
            # precedence.
            self.log('Finding duplicate usernames')
            cursor.execute('''
                SELECT
                    u.id, u.username, LOWER(u.username)
                FROM
                    users AS u
                INNER JOIN
                    usernames AS un
                ON
                    un.username = u.username COLLATE utf8_general_ci
                    AND un.user_id != u.id
            ''')
            self.log('%d rows returned' % cursor.rowcount)

            rows = cursor.fetchall()

            if not rows:
                return

            # Find all usernames with could possibly clash with our new
            # suffixed variants.
            self.log('Finding possible clashes for new usernames')
            patterns = ['%%-%d' % i for i in range(2, MAX_DUPS + 1)]
            cursor.execute('''
                    SELECT
                        LOWER(username)
                    FROM
                        usernames
                    WHERE
                        %s
                ''' % ' OR '.join('username LIKE %s' for p in patterns),
                patterns)
            self.log('%d rows returned' % cursor.rowcount)

            usernames = [r[0] for r in cursor]

        finally:
            cursor.execute('DROP TEMPORARY TABLE usernames')
            if not rows:
                transaction.rollback()

        # Update usernames to case-insensitive unique variants.
        suffixes = range(2, MAX_DUPS + 1)
        def unique_username(username, lower):
            n = next(i for i in suffixes
                     if '%s-%d' % (lower, i) not in usernames)
            usernames.append('%s-%d' % (lower, n))
            return '%s-%d' % (username, n)

        failures = []

        self.log('Updating duplicate usernames in `users` table')
        new_name = None
        for id, username, lower in rows:
            try:
                new_name = unique_username(username, lower)
                self.log('Renaming %d "%s" -> "%s"' % (id, username, new_name))

                cursor.execute('''
                        UPDATE
                            users
                        SET
                            username = %s
                        WHERE
                            id = %s
                    ''', (new_name, id))
            except Exception, e:
                failures.append((id, username, new_name))
                self.log('FAIL: %s' % e)
                traceback.print_exc()

        if failures:
            self.log('%d username updates failed:' % len(failures))
            self.log('\t' + '\n\t'.join(map(repr, failures)))

        transaction.commit()
        self.log('Done.')
