import os
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

if __name__ == '__main__':
    today = datetime.today()
    for i in range(30, 0, -1):
        date = today - timedelta(days=i)
        fetch_data_for_date(date)
