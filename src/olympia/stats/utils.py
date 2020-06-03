from django.conf import settings
from google.cloud import bigquery

from olympia.constants.applications import FIREFOX

# This is the mapping between the AMO stats `sources` and the BigQuery columns.
AMO_TO_BIGQUERY_COLUMN_MAPPING = {
    'apps': 'dau_by_app_version',
    'countries': 'dau_by_country',
    'locales': 'dau_by_locale',
    'os': 'dau_by_app_os',
    'versions': 'dau_by_addon_version',
}


AMO_STATS_DAU_TABLE = 'amo_stats_dau_v1'


def rows_to_series(rows, filter_by=None):
    """Transforms BigQuery rows into series items suitable for the rest of the
    AMO stats logic."""
    for row in rows:
        item = {
            'count': row['dau'],
            'date': row['submission_date'],
            'end': row['submission_date'],
        }
        if filter_by:
            item['data'] = {
                d['key']: d['value'] for d in row.get(filter_by, [])
            }

            # See: https://github.com/mozilla/addons-server/issues/14411
            if filter_by == AMO_TO_BIGQUERY_COLUMN_MAPPING['apps']:
                item['data'] = {FIREFOX.guid: item['data']}

        yield item


def get_updates_series(addon, start_date, end_date, source=None):
    client = bigquery.Client.from_service_account_json(
        settings.GOOGLE_APPLICATION_CREDENTIALS
    )

    filter_by = AMO_TO_BIGQUERY_COLUMN_MAPPING.get(source)

    select_clause = 'SELECT submission_date, dau'
    if filter_by:
        select_clause = f'{select_clause}, {filter_by}'

    fully_qualified_table_name = '.'.join(
        [
            settings.BIGQUERY_PROJECT,
            settings.BIGQUERY_AMO_DATASET,
            AMO_STATS_DAU_TABLE,
        ]
    )

    query = f"""
{select_clause}
FROM `{fully_qualified_table_name}`
WHERE addon_id = @addon_id
AND submission_date BETWEEN @submission_date_start AND @submission_date_end
ORDER BY submission_date DESC
LIMIT 365"""

    rows = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    'addon_id', 'STRING', addon.guid
                ),
                bigquery.ScalarQueryParameter(
                    'submission_date_start', 'DATE', start_date
                ),
                bigquery.ScalarQueryParameter(
                    'submission_date_end', 'DATE', end_date
                ),
            ]
        ),
    ).result()

    return rows_to_series(rows, filter_by=filter_by)
