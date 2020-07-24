# -*- coding: utf-8 -*-
import csv
import json

from datetime import date
from unittest import mock

from django.http import Http404
from django.test.client import RequestFactory
from django.utils.encoding import force_text
from waffle.testutils import override_flag

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.amo.urlresolvers import reverse
from olympia.constants.applications import FIREFOX
from olympia.stats import tasks, views
from olympia.stats.models import DownloadCount
from olympia.users.models import UserProfile


@override_flag('bigquery-download-stats', active=True)
class StatsTestCase(TestCase):
    fixtures = [
        # Create two configured users:
        #
        #   - admin: jbalogh@mozilla.com
        #   - simple user: nobodyspecial@mozilla.com
        'stats/users.json',
        # Create add-ons `4` and `5` and `DownloadCount` entries.
        'stats/download_counts.json',
    ]

    def setUp(self):
        super().setUp()

        self.addon_4 = Addon.objects.get(pk=4)
        version_factory(addon=self.addon_4)
        self.addon_5 = Addon.objects.get(pk=5)
        version_factory(addon=self.addon_5)

        # Default url_args to an addon and range with data.
        self.url_args = {
            'addon_id': self.addon_4.pk,
            'start': '20090601',
            'end': '20090930',
        }

        Addon.objects.filter(id__in=(self.addon_4.pk, self.addon_5.pk)).update(
            status=amo.STATUS_APPROVED
        )
        # Most tests don't care about permissions.
        self.login_as_admin()

        self.get_updates_series_patcher = mock.patch(
            'olympia.stats.views.get_updates_series'
        )
        self.get_updates_series_mock = self.get_updates_series_patcher.start()
        self.get_updates_series_mock.return_value = []

        self.get_download_series_patcher = mock.patch(
            'olympia.stats.views.get_download_series'
        )
        self.get_download_series_mock = (
            self.get_download_series_patcher.start()
        )
        self.get_download_series_mock.return_value = []

    def tearDown(self):
        super().setUp()

        self.get_updates_series_patcher.stop()
        self.get_download_series_patcher.stop()

    def login_as_admin(self):
        self.client.logout()
        self.client.login(email='jbalogh@mozilla.com')

    def login_as_visitor(self):
        self.client.logout()
        self.client.login(email='nobodyspecial@mozilla.com')

    def get_view_response(self, view, **kwargs):
        view_args = self.url_args.copy()
        head = kwargs.pop('head', False)
        view_args.update(kwargs)
        url = reverse(view, kwargs=view_args)
        if head:
            return self.client.head(url, follow=True)
        return self.client.get(url, follow=True)

    def views_gen(self, **kwargs):
        # common set of views
        for series in views.SERIES:
            for group in views.SERIES_GROUPS:
                view = 'stats.%s_series' % series
                args = kwargs.copy()
                args['group'] = group
                yield (view, args)

    def public_views_gen(self, **kwargs):
        # all views are potentially public
        for view, args in self.views_gen(**kwargs):
            yield (view, args)

    def _check_it(self, views, status):
        for view, kwargs in views:
            response = self.get_view_response(view, head=True, **kwargs)
            assert response.status_code == status


class TestUnlistedAddons(StatsTestCase):
    def setUp(self):
        super().setUp()

        self.author = user_factory(email='user@example.com')
        self.addon = addon_factory(users=[self.author])
        self.url_args = {
            'addon_id': self.addon.pk,
            'start': '20090601',
            'end': '20090930',
        }
        self.make_addon_unlisted(self.addon)

    def test_no_public_stats_for_unlisted_addon(self):
        """All the views for the stats return 404 for unlisted addons."""
        self.login_as_visitor()
        self._check_it(self.public_views_gen(format='json'), 404)

    def test_stats_available_for_admins(self):
        """
        All the views for the stats are available to admins for unlisted
        addons.
        """
        self.login_as_admin()
        self._check_it(self.public_views_gen(format='json'), 200)

    def test_stats_available_for_authors(self):
        self.client.logout()
        self.client.login(email=self.author.email)
        self._check_it(self.public_views_gen(format='json'), 200)


class TestListedAddons(StatsTestCase):
    def setUp(self):
        super().setUp()

        self.someuser = UserProfile.objects.get(
            email='nobodyspecial@mozilla.com'
        )
        AddonUser.objects.create(user=self.someuser, addon=self.addon_4)

    def test_private_stats_for_listed_addon(self):
        self.client.logout()
        self._check_it(self.public_views_gen(format='json'), 403)

        self.client.login(email=self.someuser.email)
        self._check_it(self.public_views_gen(format='json'), 200)

    def test_stats_for_mozilla_disabled_addon(self):
        self.addon_4.update(status=amo.STATUS_DISABLED)

        # Public users should not see stats
        self.client.logout()
        # It is a 404 (and not a 403) before the decorator first tries to
        # retrieve the add-on.
        self._check_it(self.public_views_gen(format='json'), 404)

        # Developers should not see stats
        self.client.login(email=self.someuser.email)
        self._check_it(self.public_views_gen(format='json'), 404)

        # Admins should see stats
        self.login_as_admin()
        self._check_it(self.public_views_gen(format='json'), 200)

    def test_stats_for_user_disabled_addon(self):
        self.addon_4.update(disabled_by_user=True)

        # Public users should not see stats
        self.client.logout()
        self._check_it(self.public_views_gen(format='json'), 403)

        # Developers should see stats
        self.client.login(email=self.someuser.email)
        self._check_it(self.public_views_gen(format='json'), 200)

        # Admins should see stats
        self.login_as_admin()
        self._check_it(self.public_views_gen(format='json'), 200)


class TestSeriesSecurity(StatsTestCase):
    """Tests to make sure all restricted data remains restricted."""

    def test_private_addon_no_groups(self):
        # Logged in but no groups
        self.login_as_visitor()
        self._check_it(self.views_gen(format='json'), 403)

    def test_private_addon_stats_group(self):
        # Logged in with stats group.
        user = UserProfile.objects.get(email='nobodyspecial@mozilla.com')
        group = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=user, group=group)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(format='json'), 200)

    def test_private_addon_anonymous(self):
        # Not logged in
        self.client.logout()
        self._check_it(self.views_gen(format='json'), 403)

    def test_addon_no_groups(self):
        # Logged in but no groups
        self.login_as_visitor()
        self._check_it(self.public_views_gen(addon_id=5, format='json'), 403)

    def test_addon_stats_group(self):
        # Logged in with stats group.
        user = UserProfile.objects.get(email='nobodyspecial@mozilla.com')
        group = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=user, group=group)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(addon_id=5, format='json'), 200)

    def test_addon_anonymous(self):
        # Not logged in
        self.client.logout()
        self._check_it(self.public_views_gen(addon_id=5, format='json'), 403)


class TestCacheControl(StatsTestCase):
    """Tests we set cache control headers"""

    def test_cache_control(self):
        response = self.get_view_response(
            'stats.downloads_series', head=True, group='month', format='json'
        )
        assert response.get('cache-control', '').startswith(
            'max-age='
        ), 'Bad or no cache-control: %r' % response.get('cache-control', '')


class TestLayout(StatsTestCase):
    def test_no_public_stats(self):
        self.login_as_visitor()
        response = self.client.get(
            reverse('stats.downloads', args=[self.addon_4.slug])
        )
        assert response.status_code == 403


class ESStatsTestCase(StatsTestCase, amo.tests.ESTestCase):
    """Test class with some ES setup."""

    def setUp(self):
        super().setUp()

        self.empty_index('stats_download_counts')
        self.index()

    def index(self):
        downloads = DownloadCount.objects.values_list('id', flat=True)
        tasks.index_download_counts(list(downloads))
        self.refresh('stats_download_counts')

    def csv_eq(self, response, expected):
        content = force_text(response.content)
        content_csv = csv.DictReader(
            # Drop lines that are comments.
            filter(lambda row: row[0] != '#', content.splitlines())
        )
        expected = force_text(expected)
        expected_csv = csv.DictReader(
            # Strip any extra spaces from the expected content.
            line.strip()
            for line in expected.splitlines()
        )
        assert tuple(content_csv) == tuple(expected_csv)


class TestCsvAndJsonViews(ESStatsTestCase):
    def test_usage_series_no_data_json(self):
        self.get_updates_series_mock.return_value = []

        response = self.get_view_response(
            'stats.usage_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(json.loads(force_text(response.content)), [])

    def test_usage_series_no_data_csv(self):
        self.get_updates_series_mock.return_value = []

        response = self.get_view_response(
            'stats.usage_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(response, """date,count""")

    def test_usage_json(self):
        self.get_updates_series_mock.return_value = [
            {'date': date(2009, 6, 2), 'end': date(2009, 6, 2), 'count': 1500},
            {'date': date(2009, 6, 1), 'end': date(2009, 6, 1), 'count': 1000},
        ]

        response = self.get_view_response(
            'stats.usage_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {'count': 1500, 'date': '2009-06-02', 'end': '2009-06-02'},
                {'count': 1000, 'date': '2009-06-01', 'end': '2009-06-01'},
            ],
        )

    def test_usage_csv(self):
        self.get_updates_series_mock.return_value = [
            {'date': date(2009, 6, 2), 'end': date(2009, 6, 2), 'count': 1500},
            {'date': date(2009, 6, 1), 'end': date(2009, 6, 1), 'count': 1000},
        ]

        response = self.get_view_response(
            'stats.usage_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count
            2009-06-02,1500
            2009-06-01,1000""",
        )

    def test_usage_by_app_json(self):
        self.get_updates_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {FIREFOX.guid: {'4.0': 1500}},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {FIREFOX.guid: {'4.0': 1000}},
            },
        ]

        response = self.get_view_response(
            'stats.apps_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {
                    "data": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": {"4.0": 1500}
                    },
                    "count": 1500,
                    "date": "2009-06-02",
                    "end": "2009-06-02",
                },
                {
                    "data": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": {"4.0": 1000}
                    },
                    "count": 1000,
                    "date": "2009-06-01",
                    "end": "2009-06-01",
                },
            ],
        )

    def test_usage_by_app_csv(self):
        self.get_updates_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {FIREFOX.guid: {'4.0': 1500}},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {FIREFOX.guid: {'4.0': 1000}},
            },
        ]

        response = self.get_view_response(
            'stats.apps_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count,Firefox 4.0
            2009-06-02,1500,1500
            2009-06-01,1000,1000""",
        )

    def test_usage_by_locale_json(self):
        self.get_updates_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'el': 800, 'es-mx': 400, 'en-us': 300},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'el': 400, 'es-mx': 300, 'en-us': 300},
            },
        ]

        response = self.get_view_response(
            'stats.locales_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {
                    "count": 1500,
                    "date": "2009-06-02",
                    "end": "2009-06-02",
                    "data": {
                        u"Ελληνικά (el)": 800,
                        u'Espa\xf1ol (de M\xe9xico) (es-mx)': 400,
                        u"English (US) (en-us)": 300,
                    },
                },
                {
                    "count": 1000,
                    "date": "2009-06-01",
                    "end": "2009-06-01",
                    "data": {
                        u"Ελληνικά (el)": 400,
                        u'Espa\xf1ol (de M\xe9xico) (es-mx)': 300,
                        u"English (US) (en-us)": 300,
                    },
                },
            ],
        )

    def test_usage_by_locale_csv(self):
        self.get_updates_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'el': 800, 'es-mx': 400, 'en-us': 300},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'el': 400, 'es-mx': 300, 'en-us': 300},
            },
        ]

        response = self.get_view_response(
            'stats.locales_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            u"""date,count,English (US) (en-us),Espa\xf1ol (de M\xe9xico) (es-mx),Ελληνικά (el)
            2009-06-02,1500,300,400,800
            2009-06-01,1000,300,300,400""",  # noqa
        )

    def test_usage_by_os_json(self):
        self.get_updates_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'Linux': 400, 'Windows': 500},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'Linux': 300, 'Windows': 400},
            },
        ]

        response = self.get_view_response(
            'stats.os_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {
                    "count": 1500,
                    "date": "2009-06-02",
                    "end": "2009-06-02",
                    "data": {"Linux": 400, "Windows": 500},
                },
                {
                    "count": 1000,
                    "date": "2009-06-01",
                    "end": "2009-06-01",
                    "data": {"Linux": 300, "Windows": 400},
                },
            ],
        )

    def test_usage_by_os_csv(self):
        self.get_updates_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'Linux': 400, 'Windows': 500},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'Linux': 300, 'Windows': 400},
            },
        ]

        response = self.get_view_response(
            'stats.os_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            u"""date,count,Linux,Windows
            2009-06-02,1500,400,500
            2009-06-01,1000,300,400""",
        )

    def test_usage_by_version_json(self):
        self.get_updates_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'1.0': 550, '2.0': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'1.0': 200, '2.0': 800},
            },
        ]

        response = self.get_view_response(
            'stats.versions_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {
                    'count': 1500,
                    'date': '2009-06-02',
                    'end': '2009-06-02',
                    'data': {'1.0': 550, '2.0': 950},
                },
                {
                    'count': 1000,
                    'date': '2009-06-01',
                    'end': '2009-06-01',
                    'data': {'1.0': 200, '2.0': 800},
                },
            ],
        )

    def test_usage_by_version_csv(self):
        self.get_updates_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'1.0': 550, '2.0': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'1.0': 200, '2.0': 800},
            },
        ]

        response = self.get_view_response(
            'stats.versions_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count,1.0,2.0
            2009-06-02,1500,550,950
            2009-06-01,1000,200,800""",
        )

    @override_flag('bigquery-download-stats', active=False)
    def test_overview(self):
        self.get_updates_series_mock.return_value = [
            {'date': date(2009, 6, 2), 'end': date(2009, 6, 2), 'count': 1500},
            {'date': date(2009, 6, 1), 'end': date(2009, 6, 1), 'count': 1000},
        ]

        response = self.get_view_response(
            'stats.overview_series', group='day', format='json'
        )

        assert response.status_code == 200
        # These are the dates from the fixtures. The return value will have
        # dates in between filled with zeroes.
        expected_data = [
            {"date": "2009-09-03", "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-08-03", "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-07-03", "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-28", "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-20", "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-12", "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-07", "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-02", "data": {"downloads": 0, "updates": 1500}},
            {"date": "2009-06-01", "data": {"downloads": 10, "updates": 1000}},
        ]
        actual_data = json.loads(force_text(response.content))
        # Make sure they match up at the front and back.
        assert actual_data[0]['date'] == expected_data[0]['date']
        assert actual_data[-1]['date'] == expected_data[-1]['date']
        end_date = expected_data[-1]['date']

        expected, actual = iter(expected_data), iter(actual_data)
        next_expected, next_actual = next(expected), next(actual)
        while True:
            if next_expected['date'] == next_actual['date']:
                # If they match it's a date we have data for.
                self.assertDictEqual(next_expected, next_actual)
                if next_expected['date'] == end_date:
                    break
                next_expected, next_actual = next(expected), next(actual)
            else:
                # Otherwise just check that the data is zeroes.
                self.assertDictEqual(
                    next_actual['data'], {'downloads': 0, 'updates': 0}
                )
                next_actual = next(actual)
        self.get_download_series_mock.no_called()

    @override_flag('bigquery-download-stats', active=False)
    def test_downloads_json_legacy(self):
        response = self.get_view_response(
            'stats.downloads_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {"count": 10, "date": "2009-09-03", "end": "2009-09-03"},
                {"count": 10, "date": "2009-08-03", "end": "2009-08-03"},
                {"count": 10, "date": "2009-07-03", "end": "2009-07-03"},
                {"count": 10, "date": "2009-06-28", "end": "2009-06-28"},
                {"count": 10, "date": "2009-06-20", "end": "2009-06-20"},
                {"count": 10, "date": "2009-06-12", "end": "2009-06-12"},
                {"count": 10, "date": "2009-06-07", "end": "2009-06-07"},
                {"count": 10, "date": "2009-06-01", "end": "2009-06-01"},
            ],
        )
        self.get_download_series_mock.no_called()

    @override_flag('bigquery-download-stats', active=False)
    def test_downloads_csv_legacy(self):
        response = self.get_view_response(
            'stats.downloads_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count
            2009-09-03,10
            2009-08-03,10
            2009-07-03,10
            2009-06-28,10
            2009-06-20,10
            2009-06-12,10
            2009-06-07,10
            2009-06-01,10""",
        )
        self.get_download_series_mock.no_called()

    def test_downloads_json(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
            },
        ]

        response = self.get_view_response(
            'stats.downloads_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {"date": "2009-06-02", "end": "2009-06-02", "count": 1500},
                {"date": "2009-06-01", "end": "2009-06-01", "count": 1000},
            ]
        )

    def test_downloads_csv(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
            },
        ]

        response = self.get_view_response(
            'stats.downloads_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count
            2009-06-02,1500
            2009-06-01,1000""",
        )

    @override_flag('bigquery-download-stats', active=False)
    def test_downloads_sources_json_legacy(self):
        response = self.get_view_response(
            'stats.sources_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {
                    "count": 10,
                    "date": "2009-09-03",
                    "end": "2009-09-03",
                    "data": {"api": 2, "search": 3},
                },
                {
                    "count": 10,
                    "date": "2009-08-03",
                    "end": "2009-08-03",
                    "data": {"api": 2, "search": 3},
                },
                {
                    "count": 10,
                    "date": "2009-07-03",
                    "end": "2009-07-03",
                    "data": {"api": 2, "search": 3},
                },
                {
                    "count": 10,
                    "date": "2009-06-28",
                    "end": "2009-06-28",
                    "data": {"api": 2, "search": 3},
                },
                {
                    "count": 10,
                    "date": "2009-06-20",
                    "end": "2009-06-20",
                    "data": {"api": 2, "search": 3},
                },
                {
                    "count": 10,
                    "date": "2009-06-12",
                    "end": "2009-06-12",
                    "data": {"api": 2, "search": 3},
                },
                {
                    "count": 10,
                    "date": "2009-06-07",
                    "end": "2009-06-07",
                    "data": {"api": 2, "search": 3},
                },
                {
                    "count": 10,
                    "date": "2009-06-01",
                    "end": "2009-06-01",
                    "data": {"api": 2, "search": 3},
                },
            ],
        )
        self.get_download_series_mock.no_called()

    @override_flag('bigquery-download-stats', active=False)
    def test_downloads_sources_csv_legacy(self):
        response = self.get_view_response(
            'stats.sources_series', group='day', format='csv'
        )
        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count,api,search
            2009-09-03,10,2,3
            2009-08-03,10,2,3
            2009-07-03,10,2,3
            2009-06-28,10,2,3
            2009-06-20,10,2,3
            2009-06-12,10,2,3
            2009-06-07,10,2,3
            2009-06-01,10,2,3""",
        )
        self.get_download_series_mock.no_called()

    def test_download_by_source_json(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'api': 550, 'search': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'api': 550, 'search': 450},
            },
        ]

        response = self.get_view_response(
            'stats.sources_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {
                    "date": "2009-06-02",
                    "end": "2009-06-02",
                    "count": 1500,
                    "data": {"api": 550, "search": 950},
                },
                {
                    "date": "2009-06-01",
                    "end": "2009-06-01",
                    "count": 1000,
                    "data": {"api": 550, "search": 450},
                },
            ]
        )

    def test_download_by_source_csv(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'api': 550, 'search': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'api': 550, 'search': 450},
            },
        ]

        response = self.get_view_response(
            'stats.sources_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count,api,search
            2009-06-02,1500,550,950
            2009-06-01,1000,550,450""",
        )

    def test_download_by_content_json(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'content-1': 550, 'content-2': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'content-1': 550, 'content-3': 450},
            },
        ]

        response = self.get_view_response(
            'stats.contents_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {
                    'data': {'content-1': 550, 'content-2': 950},
                    'date': '2009-06-02',
                    'end': '2009-06-02',
                    'count': 1500,
                },
                {
                    'data': {'content-1': 550, 'content-3': 450},
                    'date': '2009-06-01',
                    'end': '2009-06-01',
                    'count': 1000,
                },
            ],
        )

    def test_download_by_content_csv(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'content-1': 550, 'content-2': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'content-1': 550, 'content-3': 450},
            },
        ]

        response = self.get_view_response(
            'stats.contents_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count,content-1,content-2,content-3
            2009-06-02,1500,550,950,0
            2009-06-01,1000,550,0,450""",
        )

    def test_download_by_medium_json(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'medium-1': 550, 'medium-2': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'medium-1': 550, 'medium-3': 450},
            },
        ]

        response = self.get_view_response(
            'stats.mediums_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {
                    'data': {'medium-1': 550, 'medium-2': 950},
                    'date': '2009-06-02',
                    'end': '2009-06-02',
                    'count': 1500,
                },
                {
                    'data': {'medium-1': 550, 'medium-3': 450},
                    'date': '2009-06-01',
                    'end': '2009-06-01',
                    'count': 1000,
                },
            ],
        )

    def test_download_by_medium_csv(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'medium-1': 550, 'medium-2': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'medium-1': 550, 'medium-3': 450},
            },
        ]

        response = self.get_view_response(
            'stats.mediums_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count,medium-1,medium-2,medium-3
            2009-06-02,1500,550,950,0
            2009-06-01,1000,550,0,450""",
        )

    def test_download_by_campaign_json(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'campaign-1': 550, 'campaign-2': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'campaign-1': 550, 'campaign-3': 450},
            },
        ]

        response = self.get_view_response(
            'stats.campaigns_series', group='day', format='json'
        )

        assert response.status_code == 200
        self.assertListEqual(
            json.loads(force_text(response.content)),
            [
                {
                    'data': {'campaign-1': 550, 'campaign-2': 950},
                    'date': '2009-06-02',
                    'end': '2009-06-02',
                    'count': 1500,
                },
                {
                    'data': {'campaign-1': 550, 'campaign-3': 450},
                    'date': '2009-06-01',
                    'end': '2009-06-01',
                    'count': 1000,
                },
            ],
        )

    def test_download_by_campaign_csv(self):
        self.get_download_series_mock.return_value = [
            {
                'date': date(2009, 6, 2),
                'end': date(2009, 6, 2),
                'count': 1500,
                'data': {'campaign-1': 550, 'campaign-2': 950},
            },
            {
                'date': date(2009, 6, 1),
                'end': date(2009, 6, 1),
                'count': 1000,
                'data': {'campaign-1': 550, 'campaign-3': 450},
            },
        ]

        response = self.get_view_response(
            'stats.campaigns_series', group='day', format='csv'
        )

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count,campaign-1,campaign-2,campaign-3
            2009-06-02,1500,550,950,0
            2009-06-01,1000,550,0,450""",
        )

    @override_flag('bigquery-download-stats', active=False)
    def test_no_download_by_content_if_not_bigquery(self):
        response = self.get_view_response(
            'stats.contents_series', group='day', format='csv'
        )

        assert response.status_code == 404
        self.get_download_series_mock.not_called()

    @override_flag('bigquery-download-stats', active=False)
    def test_no_download_by_campaign_if_not_bigquery(self):
        response = self.get_view_response(
            'stats.campaigns_series', group='day', format='csv'
        )

        assert response.status_code == 404
        self.get_download_series_mock.not_called()

    @override_flag('bigquery-download-stats', active=False)
    def test_no_download_by_medium_if_not_bigquery(self):
        response = self.get_view_response(
            'stats.mediums_series', group='day', format='csv'
        )

        assert response.status_code == 404
        self.get_download_series_mock.not_called()


class TestXss(amo.tests.TestXss):
    def test_stats_page(self):
        url = reverse('stats.overview', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_date_range_or_404_xss(self):
        with self.assertRaises(Http404):
            views.get_daterange_or_404(start='<alert>', end='20010101')

    def test_report_view_xss(self):
        req = RequestFactory().get('/', start='<alert>', end='20010101')
        assert views.get_report_view(req) == {}

        req = RequestFactory().get('/', last='<alert>')
        assert views.get_report_view(req) == {}


class TestStatsWithBigQuery(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory(email='staff@mozilla.com')
        self.addon = addon_factory(users=[self.user])
        self.start_date = date(2020, 1, 1)
        self.end_date = date(2020, 1, 5)
        self.series_args = [
            self.addon.slug,
            'day',
            self.start_date.strftime('%Y%m%d'),
            self.end_date.strftime('%Y%m%d'),
            'json',
        ]
        self.client.login(email=self.user.email)

    def test_overview_shows_link_to_stats_by_country(self):
        url = reverse('stats.overview', args=[self.addon.slug])

        response = self.client.get(url)

        assert b'by Country' in response.content

    @override_flag('bigquery-download-stats', active=False)
    @mock.patch('olympia.stats.views.get_updates_series')
    @mock.patch('olympia.stats.views.get_download_series')
    def test_overview_series(
            self, get_download_series, get_updates_series_mock
    ):
        get_updates_series_mock.return_value = []
        url = reverse('stats.overview_series', args=self.series_args)

        self.client.get(url)

        get_download_series.not_called()
        get_updates_series_mock.assert_called_once_with(
            addon=self.addon,
            start_date=self.start_date,
            end_date=self.end_date,
        )

    @mock.patch('olympia.stats.views.get_updates_series')
    def test_usage_series(self, get_updates_series_mock):
        get_updates_series_mock.return_value = []
        url = reverse('stats.usage_series', args=self.series_args)

        self.client.get(url)

        get_updates_series_mock.assert_called_once_with(
            addon=self.addon,
            start_date=self.start_date,
            end_date=self.end_date,
        )

    def test_usage_breakdown_series(self):
        for (url_name, source) in [
            ('stats.apps_series', 'apps'),
            ('stats.countries_series', 'countries'),
            ('stats.locales_series', 'locales'),
            ('stats.os_series', 'os'),
            ('stats.versions_series', 'versions'),
        ]:
            url = reverse(url_name, args=self.series_args)

            with mock.patch(
                'olympia.stats.views.get_updates_series'
            ) as get_updates_series_mock:
                get_updates_series_mock.return_value = []
                self.client.get(url)

                get_updates_series_mock.assert_called_once_with(
                    addon=self.addon,
                    start_date=self.start_date,
                    end_date=self.end_date,
                    source=source,
                )

    def test_stats_by_country(self):
        url = reverse('stats.countries', args=[self.addon.slug])

        response = self.client.get(url)

        assert b'User countries by Date' in response.content

    def test_stats_for_langpacks(self):
        self.addon.update(type=amo.ADDON_LPAPP)
        url = reverse('stats.overview', args=[self.addon.slug])

        response = self.client.get(url)

        assert response.status_code == 200

    def test_stats_for_dictionaries(self):
        self.addon.update(type=amo.ADDON_DICT)
        url = reverse('stats.overview', args=[self.addon.slug])

        response = self.client.get(url)

        assert response.status_code == 200

    @override_flag('bigquery-download-stats', active=True)
    @mock.patch('olympia.stats.views.get_updates_series')
    @mock.patch('olympia.stats.views.get_download_series')
    def test_overview_series_with_bigquery_download_stats(
        self, get_download_series_mock, get_updates_series_mock
    ):
        get_download_series_mock.return_value = []
        get_updates_series_mock.return_value = []
        url = reverse('stats.overview_series', args=self.series_args)

        self.client.get(url)

        get_download_series_mock.assert_called_once_with(
            addon=self.addon,
            start_date=self.start_date,
            end_date=self.end_date,
        )

    @override_flag('bigquery-download-stats', active=False)
    def test_overview_does_not_show_some_links_when_flag_is_disabled(self):
        url = reverse('stats.overview', args=[self.addon.slug])

        response = self.client.get(url)

        assert b'by Source' in response.content
        assert b'by Medium' not in response.content
        assert b'by Content' not in response.content
        assert b'by Campaign' not in response.content

    @override_flag('bigquery-download-stats', active=True)
    def test_overview_shows_links_to_bigquery_download_stats(self):
        url = reverse('stats.overview', args=[self.addon.slug])

        response = self.client.get(url)

        assert b'by Source' in response.content
        assert b'by Medium' in response.content
        assert b'by Content' in response.content
        assert b'by Campaign' in response.content

    @override_flag('bigquery-download-stats', active=True)
    def test_download_stats_by_source(self):
        url = reverse('stats.sources', args=[self.addon.slug])

        response = self.client.get(url)

        assert b'Download sources by Date' in response.content

    @override_flag('bigquery-download-stats', active=True)
    def test_download_stats_by_medium(self):
        url = reverse('stats.mediums', args=[self.addon.slug])

        response = self.client.get(url)

        assert b'Download mediums by Date' in response.content

    @override_flag('bigquery-download-stats', active=True)
    def test_download_stats_by_content(self):
        url = reverse('stats.contents', args=[self.addon.slug])

        response = self.client.get(url)

        assert b'Download contents by Date' in response.content

    @override_flag('bigquery-download-stats', active=True)
    def test_download_stats_by_campaign(self):
        url = reverse('stats.campaigns', args=[self.addon.slug])

        response = self.client.get(url)

        assert b'Download campaigns by Date' in response.content


class TestProcessLocales(TestCase):
    def test_performs_lowercase_lookup(self):
        series = [{'data': {'en-US': 123}}]

        series = views.process_locales(series)

        assert len(next(series)['data']) == 1

    def test_skips_none_key(self):
        series = [{'data': {None: 123}}]

        series = views.process_locales(series)

        assert len(next(series)['data']) == 0


class TestRenderCSV(TestCase):
    def test_handles_null_keys(self):
        series = [
            {'data': {None: 1, 'a': 2}, 'count': 3, 'date': '2020-01-01'},
            {'data': {'a': 4}, 'count': 4, 'date': '2020-01-02'},
        ]

        # Simulates how other views are rendering CSV content.
        stats, fields = views.csv_fields(series)
        response = views.render_csv(
            request=RequestFactory().get('/'),
            addon=addon_factory(),
            stats=stats,
            fields=fields,
        )

        assert '\r\n'.join([',a', '1,2', '0,4']) in force_text(
            response.content
        )
