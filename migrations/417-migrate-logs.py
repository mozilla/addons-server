from django.db import connection, transaction


def run():
    cursor = connection.cursor()
    cursor.execute('select activity_log_id from log_activity_app;')
    ids = [r[0] for r in cursor.fetchall()]

    cursor.execute('insert into log_activity_app_mkt '
                   'select * from log_activity_app;')
    cursor.execute('insert into log_activity_mkt '
                   'select * from log_activity where id IN %(ids)s;',
                   {'ids':ids})
    transaction.commit()
