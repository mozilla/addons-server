"""
Fetch data from the olympia database for validation results and unlisted
addons for use with the validations.py script.

Expected environment variables:
    MYSQL_HOST - The MySQL host.
    MYSQL_USER - The MySQL username.
    MYSQL_PASSWORD - The MySQL password.

Actions supported:
    validations - Fetch validation data for the last 30 days and write it to
        the filesystem in files named `validations/YYYY-MM-DD.txt`.
    unlisted - Fetch all unlisted addon guids and write the results to
        `validations/unlisted-addons.txt`.

Usage:
    python fetch_validation_data.py <action>
"""

import json
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

QUERY_FORMAT = """
    SELECT validation
    FROM file_uploads
    WHERE created LIKE %s
    AND validation IS NOT NULL
    ORDER BY created DESC;
"""


def single_result_formatter(row):
    return row[0]


def write_results(filename, formatter=single_result_formatter):
    """Write the results in the current query to `filename` using the first
    column returned or by passing each row to `formatter`."""
    with open(filename, 'w') as f:
        for row in cursor:
            f.write(formatter(row))
            f.write('\n')


def fetch_data_for_date(date):
    """Fetch validation results for a certain date."""
    date_string = date.strftime(date_format)
    print 'Fetching for {date}'.format(date=date_string)
    cursor.execute(QUERY_FORMAT, [date_string + '%'])
    write_results('validations/{date}.txt'.format(date=date_string))


def fetch_unlisted_addon_ids():
    """Fetch the guid for each unlisted addon on AMO right now."""
    print 'Fetching unlisted addons'
    cursor.execute('SELECT guid FROM addons WHERE is_listed=0 '
                   'AND guid IS NOT NULL;')
    write_results('validations/unlisted-addons.txt')


def fetch_lite_addon_ids():
    """Fetch the guid for each lite addon on AMO right now."""
    print 'Fetching STATUS_LITE addons'
    cursor.execute('SELECT guid FROM addons WHERE status=8 '
                   'AND guid IS NOT NULL;')
    write_results('validations/lite-addons.txt')


def fetch_validations():
    """Fetch the last 30 days of validations."""
    today = datetime.today()
    for i in range(30, 0, -1):
        date = today - timedelta(days=i)
        fetch_data_for_date(date)


def fetch_manual_reviews():
    """Fetch all manual review results for unlisted addons."""
    def formatter(row):
        return json.dumps(
            {'guid': row[0], 'version': row[1], 'action': row[2],
             'created': row[3].strftime('%Y-%m-%dT%H:%M%S')})

    query = """
        SELECT a.guid, v.version, la.action, la.created
        FROM versions v
        JOIN files f on f.version_id=v.id
        JOIN file_validation fv ON fv.file_id=f.id
        JOIN addons a on a.id=v.addon_id
        JOIN log_activity_version lav ON lav.version_id=v.id
        JOIN log_activity la ON la.id=lav.activity_log_id
        WHERE a.guid IS NOT NULL
           AND a.is_listed=0
           AND la.action IN (42, 43) -- (PRELIMINARY_VERSION, REJECT_VERSION)
           AND fv.passed_auto_validation=0
        ;"""
    print 'Fetching manual reviews'
    cursor.execute(query)
    write_results('validations/manual-reviews.txt', formatter=formatter)


def fetch_all():
    """Helper function to run all fetch commands."""
    for name, action in ACTIONS.items():
        if name != 'all':
            action()

ACTIONS = {
    'validations': fetch_validations,
    'unlisted': fetch_unlisted_addon_ids,
    'lite': fetch_lite_addon_ids,
    'manual_reviews': fetch_manual_reviews,
    'all': fetch_all,
}

if __name__ == '__main__':
    action = len(sys.argv) == 2 and sys.argv[1]
    if action in ACTIONS:
        ACTIONS[action]()
    else:
        print 'Unknown action "{action}". Known actions are {actions}'.format(
            action=action or '', actions=', '.join(ACTIONS.keys()))
