from datetime import date
from unittest import mock

from django.test.utils import override_settings
from google.cloud import bigquery

from olympia.amo.tests import TestCase, addon_factory
from olympia.constants.applications import ANDROID, FIREFOX
from olympia.stats.utils import (
    AMO_STATS_DAU_VIEW,
    AMO_STATS_DOWNLOAD_VIEW,
    AMO_TO_BQ_DAU_COLUMN_MAPPING,
    AMO_TO_BQ_DOWNLOAD_COLUMN_MAPPING,
    get_addons_and_average_daily_users_from_bigquery,
    get_addons_and_weekly_downloads_from_bigquery,
    get_averages_by_addon_from_bigquery,
    get_download_series,
    get_updates_series,
    rows_to_series,
)


class BigQueryTestMixin(object):
    def create_mock_client(self, results=None):
        client = mock.Mock()
        result_mock = mock.Mock()
        result_mock.result.return_value = list(results if results else [])
        client.query.return_value = result_mock
        return client

    def create_bigquery_row(self, data):
        return bigquery.Row(
            list(data.values()),
            {key: idx for idx, key in enumerate(data.keys())},
        )

    def get_job_config_named_parameters(self, query):
        # We execute `client.query()` with the actual SQL query as first arg
        # and a `job_config` as second arg.
        assert len(query.call_args) == 2
        assert 'job_config' in query.call_args[1]
        job_config = query.call_args[1]['job_config'].to_api_repr()
        return job_config['query']['queryParameters']


class TestRowsToSeriesForUsageStats(BigQueryTestMixin, TestCase):
    def create_fake_bigquery_row(
        self, dau=123, submission_date=date(2020, 5, 28), **kwargs
    ):
        return self.create_bigquery_row(
            {'dau': dau, 'submission_date': submission_date, **kwargs}
        )

    def test_no_rows(self):
        rows = []

        series = list(rows_to_series(rows, count_column='dau'))

        assert series == []

    def test_returns_items(self):
        dau = 456
        submission_date = date(2020, 5, 24)
        rows = [
            self.create_fake_bigquery_row(
                dau=dau, submission_date=submission_date
            ),
            self.create_fake_bigquery_row(),
            self.create_fake_bigquery_row(),
        ]

        series = list(rows_to_series(rows, count_column='dau'))

        assert len(series) == len(rows)
        item = series[0]
        assert 'count' in item
        assert item['count'] == dau
        assert 'date' in item
        assert item['date'] == submission_date
        assert 'end' in item
        assert item['end'] == submission_date
        # By default there should be no 'data' attribute.
        assert 'data' not in series

    def test_ignores_other_columns(self):
        dau = 456
        submission_date = date(2020, 5, 24)
        rows = [
            self.create_fake_bigquery_row(
                dau=dau, submission_date=submission_date, other_column=123
            )
        ]

        series = list(rows_to_series(rows, count_column='dau'))

        assert series[0] == {
            'count': dau,
            'date': submission_date,
            'end': submission_date,
        }

    def test_filter_by(self):
        filter_by = 'column_with_data'
        data = [{'key': 'k1', 'value': 123}, {'key': 'k2', 'value': 678}]
        rows = [self.create_fake_bigquery_row(column_with_data=data)]

        series = list(
            rows_to_series(rows, count_column='dau', filter_by=filter_by)
        )

        assert 'data' in series[0]
        assert series[0]['data'] == {'k1': 123, 'k2': 678}

    def test_filter_by_dau_by_app_version_and_fenix_build(self):
        filter_by = AMO_TO_BQ_DAU_COLUMN_MAPPING.get('apps')
        android_data = [{'key': '79.0.0', 'value': 987}]
        firefox_data = [
            {'key': '77.0.0', 'value': 123},
            {'key': '76.0.1', 'value': 678},
        ]
        rows = [
            self.create_fake_bigquery_row(
                dau_by_app_version=firefox_data,
                dau_by_fenix_build=android_data,
            )
        ]

        series = list(
            rows_to_series(rows, count_column='dau', filter_by=filter_by)
        )

        assert 'data' in series[0]
        assert series[0]['data'] == {
            ANDROID.guid: {'79.0.0': 987},
            FIREFOX.guid: {'77.0.0': 123, '76.0.1': 678},
        }

    def test_filter_by_dau_by_app_version_and_no_fenix_data(self):
        filter_by = AMO_TO_BQ_DAU_COLUMN_MAPPING.get('apps')
        android_data = []
        firefox_data = [
            {'key': '77.0.0', 'value': 123},
            {'key': '76.0.1', 'value': 678},
        ]
        rows = [
            self.create_fake_bigquery_row(
                dau_by_app_version=firefox_data,
                dau_by_fenix_build=android_data,
            )
        ]

        series = list(
            rows_to_series(rows, count_column='dau', filter_by=filter_by)
        )

        assert 'data' in series[0]
        assert series[0]['data'] == {
            ANDROID.guid: {},
            FIREFOX.guid: {'77.0.0': 123, '76.0.1': 678},
        }


class TestRowsToSeriesForDownloadStats(BigQueryTestMixin, TestCase):
    def create_fake_bigquery_row(
        self, total_downloads=123, submission_date=date(2020, 5, 28), **kwargs
    ):
        return self.create_bigquery_row(
            {
                'total_downloads': total_downloads,
                'submission_date': submission_date,
                **kwargs,
            }
        )

    def test_returns_series(self):
        total_downloads = 1234
        submission_date = date(2020, 5, 24)
        rows = [
            self.create_fake_bigquery_row(
                total_downloads=total_downloads,
                submission_date=submission_date,
            )
        ]

        series = list(rows_to_series(rows, count_column='total_downloads'))

        assert series == [
            {
                'count': total_downloads,
                'date': submission_date,
                'end': submission_date,
            }
        ]


@override_settings(BIGQUERY_PROJECT='project', BIGQUERY_AMO_DATASET='dataset')
class TestGetUpdatesSeries(BigQueryTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory()

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_client(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client

        credentials = 'path/to/credentials.json'
        with override_settings(GOOGLE_APPLICATION_CREDENTIALS=credentials):
            get_updates_series(
                addon=self.addon,
                start_date=date(2020, 5, 27),
                end_date=date(2020, 5, 28),
            )

        bigquery_client_mock.from_service_account_json.assert_called_once_with(
            credentials
        )

    @mock.patch('olympia.stats.utils.statsd.timer')
    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query(self, bigquery_client_mock, timer_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client
        start_date = date(2020, 5, 27)
        end_date = date(2020, 5, 28)
        expected_query = f"""
SELECT submission_date, dau
FROM `project.dataset.{AMO_STATS_DAU_VIEW}`
WHERE addon_id = @addon_id
AND submission_date BETWEEN @submission_date_start AND @submission_date_end
ORDER BY submission_date DESC
LIMIT 365"""

        get_updates_series(
            addon=self.addon, start_date=start_date, end_date=end_date
        )

        client.query.assert_called_once_with(
            expected_query, job_config=mock.ANY
        )
        parameters = self.get_job_config_named_parameters(client.query)
        assert parameters == [
            {
                'parameterType': {'type': 'STRING'},
                'parameterValue': {'value': self.addon.guid},
                'name': 'addon_id',
            },
            {
                'parameterType': {'type': 'DATE'},
                'parameterValue': {'value': str(start_date)},
                'name': 'submission_date_start',
            },
            {
                'parameterType': {'type': 'DATE'},
                'parameterValue': {'value': str(end_date)},
                'name': 'submission_date_end',
            },
        ]
        timer_mock.assert_called_once_with(
            'stats.get_updates_series.bigquery.no_source'
        )

    @mock.patch('olympia.stats.utils.statsd.timer')
    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query_with_source(self, bigquery_client_mock, timer_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client
        start_date = date(2020, 5, 27)
        end_date = date(2020, 5, 28)

        for source, column in AMO_TO_BQ_DAU_COLUMN_MAPPING.items():
            expected_query = f"""
SELECT submission_date, dau, {column}
FROM `project.dataset.{AMO_STATS_DAU_VIEW}`
WHERE addon_id = @addon_id
AND submission_date BETWEEN @submission_date_start AND @submission_date_end
ORDER BY submission_date DESC
LIMIT 365"""

            get_updates_series(
                addon=self.addon,
                start_date=start_date,
                end_date=end_date,
                source=source,
            )

            client.query.assert_called_with(
                expected_query, job_config=mock.ANY
            )
            timer_mock.assert_called_with(
                f'stats.get_updates_series.bigquery.{source}'
            )


@override_settings(BIGQUERY_PROJECT='project', BIGQUERY_AMO_DATASET='dataset')
class TestGetAddonsAndAverageDailyUsersFromBigQuery(
    BigQueryTestMixin, TestCase
):
    @mock.patch('google.cloud.bigquery.Client')
    def test_create_client(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client

        credentials = 'path/to/credentials.json'
        with override_settings(GOOGLE_APPLICATION_CREDENTIALS=credentials):
            get_addons_and_average_daily_users_from_bigquery()

        bigquery_client_mock.from_service_account_json.assert_called_once_with(
            credentials
        )

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client
        expected_query = f"""
SELECT addon_id, AVG(dau) AS count
FROM `project.dataset.{AMO_STATS_DAU_VIEW}`
WHERE submission_date > DATE_SUB(CURRENT_DATE(), INTERVAL 13 DAY)
GROUP BY addon_id"""

        get_addons_and_average_daily_users_from_bigquery()

        client.query.assert_called_once_with(expected_query)

    @mock.patch('google.cloud.bigquery.Client')
    def test_returned_results(self, bigquery_client_mock):
        results = [
            self.create_bigquery_row({'addon_id': 1, 'count': 123}),
            self.create_bigquery_row({'addon_id': 2, 'count': 456}),
        ]
        client = self.create_mock_client(results=results)
        bigquery_client_mock.from_service_account_json.return_value = client

        returned_results = get_addons_and_average_daily_users_from_bigquery()
        assert returned_results == [(1, 123), (2, 456)]

    @mock.patch('google.cloud.bigquery.Client')
    def test_skips_null_values(self, bigquery_client_mock):
        results = [
            self.create_bigquery_row({'addon_id': 1, 'count': 123}),
            self.create_bigquery_row({'addon_id': 2, 'count': None}),
            self.create_bigquery_row({'addon_id': None, 'count': 456}),
        ]
        client = self.create_mock_client(results=results)
        bigquery_client_mock.from_service_account_json.return_value = client

        returned_results = get_addons_and_average_daily_users_from_bigquery()
        assert returned_results == [(1, 123)]


@override_settings(BIGQUERY_PROJECT='project', BIGQUERY_AMO_DATASET='dataset')
class TestGetAveragesByAddonFromBigQuery(BigQueryTestMixin, TestCase):
    expected_base_query = f"""
WITH
  this_week AS (
  SELECT
    addon_id,
    AVG(dau) AS avg_this_week
  FROM
    `project.dataset.{AMO_STATS_DAU_VIEW}`
  WHERE
    submission_date >= @one_week_date
  GROUP BY
    addon_id),
  three_weeks_before_this_week AS (
  SELECT
    addon_id,
    AVG(dau) AS avg_three_weeks_before
  FROM
    `project.dataset.{AMO_STATS_DAU_VIEW}`
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

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_client(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client

        credentials = 'path/to/credentials.json'
        with override_settings(GOOGLE_APPLICATION_CREDENTIALS=credentials):
            get_averages_by_addon_from_bigquery(today=date.today())

        bigquery_client_mock.from_service_account_json.assert_called_once_with(
            credentials
        )

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client

        get_averages_by_addon_from_bigquery(today=date(2020, 5, 31))

        client.query.assert_called_once_with(
            self.expected_base_query, job_config=mock.ANY
        )
        parameters = self.get_job_config_named_parameters(client.query)
        assert parameters == [
            {
                'parameterType': {'type': 'DATE'},
                'parameterValue': {'value': '2020-05-24'},
                'name': 'one_week_date',
            },
            {
                'parameterType': {'type': 'DATE'},
                'parameterValue': {'value': '2020-05-03'},
                'name': 'four_weeks_date',
            },
        ]

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query_with_excluded_guids(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client
        guids = ['guid-1', 'guid-2']
        expected_query = f'{self.expected_base_query} WHERE addon_id NOT IN UNNEST(@excluded_addon_ids)'  # noqa

        get_averages_by_addon_from_bigquery(
            today=date(2020, 5, 31), exclude=guids
        )

        client.query.assert_called_once_with(
            expected_query, job_config=mock.ANY
        )
        parameters = self.get_job_config_named_parameters(client.query)
        assert parameters == [
            {
                'parameterType': {'type': 'DATE'},
                'parameterValue': {'value': '2020-05-24'},
                'name': 'one_week_date',
            },
            {
                'parameterType': {'type': 'DATE'},
                'parameterValue': {'value': '2020-05-03'},
                'name': 'four_weeks_date',
            },
            {
                'parameterType': {
                    'type': 'ARRAY',
                    'arrayType': {'type': 'STRING'},
                },
                'parameterValue': {
                    'arrayValues': [{'value': guid} for guid in guids]
                },
                'name': 'excluded_addon_ids',
            },
        ]

    @mock.patch('google.cloud.bigquery.Client')
    def test_returned_values(self, bigquery_client_mock):
        results = [
            self.create_bigquery_row(
                {
                    'addon_id': 'guid',
                    'avg_this_week': 123,
                    'avg_three_weeks_before': 456,
                }
            ),
            self.create_bigquery_row(
                {
                    'addon_id': 'guid2',
                    'avg_this_week': 45,
                    'avg_three_weeks_before': 40,
                }
            ),
            # This should be skipped because `addon_id` is `None`.
            self.create_bigquery_row(
                {
                    'addon_id': None,
                    'avg_this_week': 123,
                    'avg_three_weeks_before': 456,
                }
            ),
        ]
        client = self.create_mock_client(results=results)
        bigquery_client_mock.from_service_account_json.return_value = client

        returned_results = get_averages_by_addon_from_bigquery(
            today=date(2020, 5, 6)
        )

        assert returned_results == {
            'guid': {'avg_this_week': 123, 'avg_three_weeks_before': 456},
            'guid2': {'avg_this_week': 45, 'avg_three_weeks_before': 40},
        }


@override_settings(BIGQUERY_PROJECT='project', BIGQUERY_AMO_DATASET='dataset')
class TestGetDownloadSeries(BigQueryTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory()

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_client(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client

        credentials = 'path/to/credentials.json'
        with override_settings(GOOGLE_APPLICATION_CREDENTIALS=credentials):
            get_download_series(
                addon=self.addon,
                start_date=date(2020, 5, 27),
                end_date=date(2020, 5, 28),
            )

        bigquery_client_mock.from_service_account_json.assert_called_once_with(
            credentials
        )

    @mock.patch('olympia.stats.utils.statsd.timer')
    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query(self, bigquery_client_mock, timer_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client
        start_date = date(2020, 5, 27)
        end_date = date(2020, 5, 28)
        expected_query = f"""
SELECT submission_date, total_downloads
FROM `project.dataset.{AMO_STATS_DOWNLOAD_VIEW}`
WHERE addon_id = @addon_id
AND submission_date BETWEEN @submission_date_start AND @submission_date_end
ORDER BY submission_date DESC
LIMIT 365"""

        get_download_series(
            addon=self.addon, start_date=start_date, end_date=end_date
        )

        client.query.assert_called_once_with(
            expected_query, job_config=mock.ANY
        )
        parameters = self.get_job_config_named_parameters(client.query)
        assert parameters == [
            {
                'parameterType': {'type': 'STRING'},
                'parameterValue': {'value': self.addon.guid},
                'name': 'addon_id',
            },
            {
                'parameterType': {'type': 'DATE'},
                'parameterValue': {'value': str(start_date)},
                'name': 'submission_date_start',
            },
            {
                'parameterType': {'type': 'DATE'},
                'parameterValue': {'value': str(end_date)},
                'name': 'submission_date_end',
            },
        ]
        timer_mock.assert_called_once_with(
            'stats.get_download_series.bigquery.no_source'
        )

    @mock.patch('olympia.stats.utils.statsd.timer')
    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query_with_source(self, bigquery_client_mock, timer_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client
        start_date = date(2020, 5, 27)
        end_date = date(2020, 5, 28)

        for source, column in AMO_TO_BQ_DOWNLOAD_COLUMN_MAPPING.items():
            expected_query = f"""
SELECT submission_date, total_downloads, {column}
FROM `project.dataset.{AMO_STATS_DOWNLOAD_VIEW}`
WHERE addon_id = @addon_id
AND submission_date BETWEEN @submission_date_start AND @submission_date_end
ORDER BY submission_date DESC
LIMIT 365"""

            get_download_series(
                addon=self.addon,
                start_date=start_date,
                end_date=end_date,
                source=source,
            )

            client.query.assert_called_with(
                expected_query, job_config=mock.ANY
            )
            timer_mock.assert_called_with(
                f'stats.get_download_series.bigquery.{source}'
            )


@override_settings(BIGQUERY_PROJECT='project', BIGQUERY_AMO_DATASET='dataset')
class TestGetAddonsAndWeeklyDownloadsFromBigQuery(
    BigQueryTestMixin, TestCase
):
    @mock.patch('google.cloud.bigquery.Client')
    def test_create_client(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client

        credentials = 'path/to/credentials.json'
        with override_settings(GOOGLE_APPLICATION_CREDENTIALS=credentials):
            get_addons_and_weekly_downloads_from_bigquery()

        bigquery_client_mock.from_service_account_json.assert_called_once_with(
            credentials
        )

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client
        expected_query = f"""
SELECT addon_id, SUM(total_downloads) AS count
FROM `project.dataset.{AMO_STATS_DOWNLOAD_VIEW}`
WHERE submission_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY addon_id"""

        get_addons_and_weekly_downloads_from_bigquery()

        client.query.assert_called_once_with(expected_query)

    @mock.patch('google.cloud.bigquery.Client')
    def test_returned_results(self, bigquery_client_mock):
        results = [
            self.create_bigquery_row({'addon_id': 1, 'count': 123}),
            self.create_bigquery_row({'addon_id': 2, 'count': 456}),
        ]
        client = self.create_mock_client(results=results)
        bigquery_client_mock.from_service_account_json.return_value = client

        returned_results = get_addons_and_weekly_downloads_from_bigquery()
        assert returned_results == [(1, 123), (2, 456)]

    @mock.patch('google.cloud.bigquery.Client')
    def test_skips_null_values(self, bigquery_client_mock):
        results = [
            self.create_bigquery_row({'addon_id': 1, 'count': 123}),
            self.create_bigquery_row({'addon_id': 2, 'count': None}),
            self.create_bigquery_row({'addon_id': None, 'count': 456}),
        ]
        client = self.create_mock_client(results=results)
        bigquery_client_mock.from_service_account_json.return_value = client

        returned_results = get_addons_and_weekly_downloads_from_bigquery()
        assert returned_results == [(1, 123)]
