from datetime import timedelta

from django.conf import settings
from django_statsd.clients import statsd
from google.cloud import bigquery

from olympia.constants.applications import ANDROID, FIREFOX

# This is the mapping between the AMO stats `sources` and the BigQuery columns.
AMO_TO_BIGQUERY_COLUMN_MAPPING = {
    'apps': 'dau_by_app_version, dau_by_fenix_build',
    'countries': 'dau_by_country',
    'locales': 'dau_by_locale',
    'os': 'dau_by_app_os',
    'versions': 'dau_by_addon_version',
}


AMO_STATS_DAU_VIEW = 'amo_stats_dau'


def get_amo_stats_dau_view_name():
    return '.'.join(
        [
            settings.BIGQUERY_PROJECT,
            settings.BIGQUERY_AMO_DATASET,
            AMO_STATS_DAU_VIEW,
        ]
    )


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
            # This filter is special because we have two columns instead of
            # one.
            # See: https://github.com/mozilla/addons-server/issues/14411
            # See: https://github.com/mozilla/addons-server/issues/14832
            if filter_by == AMO_TO_BIGQUERY_COLUMN_MAPPING['apps']:
                item['data'] = {
                    ANDROID.guid: {
                        d['key']: d['value']
                        for d in row.get('dau_by_fenix_build', [])
                    },
                    FIREFOX.guid: {
                        d['key']: d['value']
                        for d in row.get('dau_by_app_version', [])
                    },
                }
            else:
                item['data'] = {
                    d['key']: d['value'] for d in row.get(filter_by, [])
                }

        yield item


def get_updates_series(addon, start_date, end_date, source=None):
    client = bigquery.Client.from_service_account_json(
        settings.GOOGLE_APPLICATION_CREDENTIALS
    )

    filter_by = AMO_TO_BIGQUERY_COLUMN_MAPPING.get(source)

    select_clause = 'SELECT submission_date, dau'
    if filter_by:
        select_clause = f'{select_clause}, {filter_by}'

    query = f"""
{select_clause}
FROM `{get_amo_stats_dau_view_name()}`
WHERE addon_id = @addon_id
AND submission_date BETWEEN @submission_date_start AND @submission_date_end
ORDER BY submission_date DESC
LIMIT 365"""

    statsd_timer = f'stats.get_updates_series.bigquery.{source or "no_source"}'
    with statsd.timer(statsd_timer):
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


def get_addons_and_average_daily_users_from_bigquery():
    """This function is used to compute the 'average_daily_users' value of each
    add-on (see `update_addon_average_daily_users()` cron task)."""
    client = bigquery.Client.from_service_account_json(
        settings.GOOGLE_APPLICATION_CREDENTIALS
    )

    query = f"""
SELECT addon_id, AVG(dau) AS count
FROM `{get_amo_stats_dau_view_name()}`
WHERE submission_date > DATE_SUB(CURRENT_DATE(), INTERVAL 13 DAY)
GROUP BY addon_id"""

    rows = client.query(query).result()

    return [
        (row['addon_id'], row['count'])
        for row in rows if row['addon_id'] and row['count']
    ]


def get_averages_by_addon_from_bigquery(today, exclude=None):
    """This function is used to compute the 'hotness' score of each add-on (see
    also `deliver_hotness()` cron task). It returns a dict with top-level keys
    being add-on GUIDs and values being dicts containing average values."""
    client = bigquery.Client.from_service_account_json(
        settings.GOOGLE_APPLICATION_CREDENTIALS
    )

    one_week_date = today - timedelta(days=7)
    four_weeks_date = today - timedelta(days=28)

    query = f"""
WITH
  this_week AS (
  SELECT
    addon_id,
    AVG(dau) AS avg_this_week
  FROM
    `{get_amo_stats_dau_view_name()}`
  WHERE
    submission_date >= @one_week_date
  GROUP BY
    addon_id),
  three_weeks_before_this_week AS (
  SELECT
    addon_id,
    AVG(dau) AS avg_three_weeks_before
  FROM
    `{get_amo_stats_dau_view_name()}`
  WHERE
    submission_date BETWEEN @four_weeks_date AND @one_week_date
  GROUP BY
    addon_id)
SELECT
  *
FROM
  this_week
JOIN
  three_weeks_before_this_week
USING
  (addon_id)
"""
    query_parameters = [
        bigquery.ScalarQueryParameter('one_week_date', 'DATE', one_week_date),
        bigquery.ScalarQueryParameter(
            'four_weeks_date', 'DATE', four_weeks_date
        ),
    ]

    if exclude and len(exclude) > 0:
        query = f'{query} WHERE addon_id NOT IN UNNEST(@excluded_addon_ids)'
        query_parameters.append(
            bigquery.ArrayQueryParameter(
                'excluded_addon_ids', 'STRING', exclude
            )
        )

    rows = client.query(
        query,
        job_config=bigquery.QueryJobConfig(query_parameters=query_parameters),
    ).result()

    return {
        row['addon_id']: {
            'avg_this_week': row['avg_this_week'],
            'avg_three_weeks_before': row['avg_three_weeks_before'],
        }
        for row in rows if row['addon_id']
    }
