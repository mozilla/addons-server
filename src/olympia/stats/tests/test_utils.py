from datetime import date
from unittest import mock

from django.test.utils import override_settings
from google.cloud import bigquery

from olympia.amo.tests import TestCase, addon_factory
from olympia.constants.applications import FIREFOX
from olympia.stats.utils import (
    AMO_STATS_DAU_TABLE,
    AMO_TO_BIGQUERY_COLUMN_MAPPING,
    get_updates_series,
    rows_to_series,
)


class TestRowsToSeries(TestCase):
    def create_fake_bigquery_row(
        self, dau=123, submission_date=date(2020, 5, 28), **kwargs
    ):
        data = {'dau': dau, 'submission_date': submission_date, **kwargs}
        return bigquery.Row(
            list(data.values()),
            {key: idx for idx, key in enumerate(data.keys())},
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
class TestGetUpdatesSeries(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory()

    def create_mock_client(self):
        client = mock.Mock()
        result_mock = mock.Mock()
        result_mock.return_value = []
        client.query.return_value = result_mock
        return client

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_client(self, bigquery_client_mock):
        credentials = 'path/to/credentials.json'
        with override_settings(GOOGLE_APPLICATION_CREDENTIALS=credentials):
            bigquery_client_mock.from_service_account_json = mock.Mock()
            get_updates_series(
                addon=self.addon,
                start_date=date(2020, 5, 27),
                end_date=date(2020, 5, 28),
            )

        bigquery_client_mock.from_service_account_json.assert_called_once_with(
            credentials
        )

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client
        start_date = date(2020, 5, 27)
        end_date = date(2020, 5, 28)
        expected_query = f"""
SELECT submission_date, dau
FROM `project.dataset.{AMO_STATS_DAU_TABLE}`
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

    @mock.patch('google.cloud.bigquery.Client')
    def test_create_query_with_source(self, bigquery_client_mock):
        client = self.create_mock_client()
        bigquery_client_mock.from_service_account_json.return_value = client
        start_date = date(2020, 5, 27)
        end_date = date(2020, 5, 28)

        for source, column in AMO_TO_BIGQUERY_COLUMN_MAPPING.items():
            expected_query = f"""
SELECT submission_date, dau, {column}
FROM `project.dataset.{AMO_STATS_DAU_TABLE}`
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
