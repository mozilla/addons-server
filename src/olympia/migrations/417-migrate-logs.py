from django.db import connection, transaction


def run():
    cursor = connection.cursor()
    cursor.execute('select activity_log_id from log_activity_app;')
    ids = [r[0] for r in cursor.fetchall()]

    if not ids:
        return

    cursor.execute('set foreign_key_checks = 0')
    cursor.execute(
        'insert into log_activity_mkt '
        'select * from log_activity where id IN %(ids)s;',
        {'ids': ids},
    )
    cursor.execute(
        'insert into log_activity_app_mkt '
        'select id, created, modified, addon_id, activity_log_id '
        'from log_activity_app;'
    )
    cursor.execute('set foreign_key_checks = 1')
    transaction.commit_unless_managed()
