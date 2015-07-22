import os
import sys
from datetime import datetime, timedelta

import MySQLdb

date_format = '%Y-%m-%d'
db = MySQLdb.connect(host=os.environ['MYSQL_HOST'],
                     user=os.environ['MYSQL_USER'],
                     passwd=os.environ['MYSQL_PASSWORD'],
                     db="addons_mozilla_org")
cursor = db.cursor()

QUERY_FORMAT = '''
    SELECT validation
    FROM file_uploads
    WHERE created LIKE %s
    AND validation IS NOT NULL
    ORDER BY created DESC;
'''


def fetch_data_for_date(date):
    date_string = date.strftime(date_format)
    print 'Fetching for {date}'.format(date=date_string)
    cursor.execute(QUERY_FORMAT, [date_string + '%'])
    with open('validations/{date}.txt'.format(date=date_string), 'w') as f:
        for row in cursor.fetchall():
            f.write(row[0] + '\n')


def fetch_unlisted_addon_ids():
    print 'Fetching unlisted addons'
    cursor.execute('SELECT guid FROM addons WHERE is_listed=0 '
                   'AND guid IS NOT NULL;')
    with open('validations/unlisted-addons.txt', 'w') as f:
        for row in cursor.fetchall():
            f.write(row[0] + '\n')

if __name__ == '__main__':
    action = len(sys.argv) == 2 and sys.argv[1]
    if action == 'validations':
        today = datetime.today()
        for i in range(30, 0, -1):
            date = today - timedelta(days=i)
            fetch_data_for_date(date)
    elif action == 'unlisted':
        fetch_unlisted_addon_ids()
    else:
        print 'Unknown action {action}'.format(action=action)
