from datetime import date
from unittest import mock

from django.test.utils import override_settings
from google.cloud import bigquery

from olympia.amo.tests import TestCase, addon_factory
from olympia.constants.applications import FIREFOX
from olympia.stats.utils import (
    AMO_STATS_DAU_VIEW,
    AMO_TO_BIGQUERY_COLUMN_MAPPING,
    get_addons_and_average_daily_users_from_bigquery,
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


class TestRowsToSeries(BigQueryTestMixin, TestCase):
    def create_fake_bigquery_row(
        self, dau=123, submission_date=date(2020, 5, 28), **kwargs
    ):
        return self.create_bigquery_row(
            {'dau': dau, 'submission_date': submission_date, **kwargs}
        )

    def test_no_rows(self):
        rows = []

        series = list(rows_to_series(rows))

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

        series = list(rows_to_series(rows))

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

        series = list(rows_to_series(rows))

        assert series[0] == {
            'count': dau,
            'date': submission_date,
            'end': submission_date,
        }

    def test_filter_by(self):
        filter_by = 'column_with_data'
        data = [{'key': 'k1', 'value': 123}, {'key': 'k2', 'value': 678}]
        rows = [self.create_fake_bigquery_row(column_with_data=data)]

        series = list(rows_to_series(rows, filter_by=filter_by))

        assert 'data' in series[0]
        assert series[0]['data'] == {'k1': 123, 'k2': 678}

    def test_filter_by_dau_by_app_version(self):
        filter_by = 'dau_by_app_version'
        data = [
            {'key': '77.0.0', 'value': 123},
            {'key': '76.0.1', 'value': 678},
        ]
        rows = [self.create_fake_bigquery_row(dau_by_app_version=data)]

        series = list(rows_to_series(rows, filter_by=filter_by))

        assert 'data' in series[0]
        assert series[0]['data'] == {
            FIREFOX.guid: {'77.0.0': 123, '76.0.1': 678}
        }


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

        for source, column in AMO_TO_BIGQUERY_COLUMN_MAPPING.items():
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
