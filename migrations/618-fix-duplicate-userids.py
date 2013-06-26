from django.db import connection, transaction


def run():
    from django.db import connection, transaction
    cursor = connection.cursor()

    # Link orphaned `auth_user` rows created in getpersonas # migration
    # to their `users` rows, by email.
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

    # Rename username field to guaranteed-unique name based on PK.
    # Usernames migrated from Remora are already UUIDs. Usernames
    # for users created on zamboni are whatever the username was
    # when the account was created. They've never been updated for
    # username changes.
    cursor.execute('''
        UPDATE IGNORE
            auth_user
        SET
            username = CONCAT('uid-', id)
    ''')

    try:
        # Create a temporary table to hold usernames and check for
        # conflicts.
        cursor.execute('''
            CREATE TEMPORARY TABLE usernames (
                username varchar(255) PRIMARY KEY,
                user_id int(11) UNSIGNED
            ) DEFAULT CHARSET = utf8
        ''')

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

        # Get a list of users with clashing usernames who don't have
        # precedence.
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

        rows = cursor.fetchall()

        if not rows:
            return

        # Find all usernames with could possibly clash with our new
        # suffixed variants.
        prefixes = [r[1].replace('%', r'\%').replace('_', r'\_') + '-%'
                    for r in rows]

        cursor.execute('''
                SELECT
                    LOWER(username)
                FROM
                    usernames
                WHERE
                    %s
            ''' % ' OR '.join('username LIKE %s' for i in range(0, len(prefixes))),
            prefixes)

        usernames = [r[0] for r in cursor]

    finally:
        cursor.execute('DROP TEMPORARY TABLE usernames')

    # Update usernames to case-insensitive unique variants.
    suffixes = range(2, 65535)
    def unique_username(username, lower):
        u = next('%s-%d' % (username, i) for i in suffixes
                 if '%s-%d' % (lower, i) not in usernames)
        usernames.append(u)
        return u

    cursor.executemany('''
            UPDATE
                users
            SET
                username = %s
            WHERE
                id = %s
        ''',
        ((unique_username(username, lower), id)
         for id, username, lower in rows))

    transaction.commit_unless_managed()

    # Drop case sensitive collation on username column.
    cursor.execute('''
        ALTER TABLE
            users
        MODIFY COLUMN
            username varchar(255) NOT NULL
    ''')
