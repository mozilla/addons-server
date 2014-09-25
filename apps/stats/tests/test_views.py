# -*- coding: utf-8 -*-
import csv
import datetime
from decimal import Decimal
import json

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse
from access.models import Group, GroupUser
from addons.models import Addon
from bandwagon.models import Collection
from stats import views, tasks
from stats import search
from stats.models import (CollectionCount, DownloadCount, GlobalStat,
                          ThemeUserCount, UpdateCount)
from users.models import UserProfile


class StatsTest(amo.tests.TestCase):
    fixtures = ['stats/test_views.json', 'stats/test_models.json']

    def setUp(self):
        """Setup some reasonable testing defaults."""
        super(StatsTest, self).setUp()
        # Default url_args to an addon and range with data.
        self.url_args = {'start': '20090601', 'end': '20090930', 'addon_id': 4}
        self.url_args_theme = {'start': '20090601', 'end': '20090930',
                               'addon_id': 6}
        # Most tests don't care about permissions.
        self.login_as_admin()

    def login_as_admin(self):
        self.client.logout()
        self.client.login(username='jbalogh@mozilla.com', password='password')

    def login_as_visitor(self):
        self.client.logout()
        self.client.login(username='nobodyspecial@mozilla.com',
                          password='password')

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
        # all views are potentially public, except for contributions
        for view, args in self.views_gen(**kwargs):
            if not view.startswith('stats.contributions'):
                yield (view, args)

    def private_views_gen(self, **kwargs):
        # only contributions views are always private
        for view, args in self.views_gen(**kwargs):
            if view.startswith('stats.contributions'):
                yield (view, args)


class ESStatsTest(StatsTest, amo.tests.ESTestCase):
    """Test class with some ES setup."""

    def setUp(self):
        super(ESStatsTest, self).setUp()
        self.empty_index('stats')
        self.index()

    def index(self):
        updates = UpdateCount.objects.values_list('id', flat=True)
        tasks.index_update_counts(list(updates))
        downloads = DownloadCount.objects.values_list('id', flat=True)
        tasks.index_download_counts(list(downloads))
        user_counts = ThemeUserCount.objects.values_list('id', flat=True)
        tasks.index_theme_user_counts(list(user_counts))
        self.refresh('stats')


class TestSeriesSecurity(StatsTest):
    """Tests to make sure all restricted data remains restricted."""
    mock_es = True  # We're checking only headers, not content.

    def _check_it(self, views, status):
        for view, kwargs in views:
            response = self.get_view_response(view, head=True, **kwargs)
            eq_(response.status_code, status,
                'unexpected http status for %s. got %s. expected %s' % (
                    view, response.status_code, status))

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
        self._check_it(self.private_views_gen(format='json'), 403)

    def test_private_addon_contrib_stats_group(self):
        # Logged in with stats and contrib stats group.
        user = UserProfile.objects.get(email='nobodyspecial@mozilla.com')
        group1 = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=user, group=group1)
        group2 = Group.objects.create(name='Revenue Stats',
                                      rules='RevenueStats:View')
        GroupUser.objects.create(user=user, group=group2)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(format='json'), 200)
        self._check_it(self.private_views_gen(format='json'), 200)

    def test_private_addon_anonymous(self):
        # Not logged in
        self.client.logout()
        self._check_it(self.views_gen(format='json'), 403)

    def test_public_addon_no_groups(self):
        # Logged in but no groups
        self.login_as_visitor()
        self._check_it(self.public_views_gen(addon_id=5, format='json'), 200)
        self._check_it(self.private_views_gen(addon_id=5, format='json'), 403)

    def test_public_addon_stats_group(self):
        # Logged in with stats group.
        user = UserProfile.objects.get(email='nobodyspecial@mozilla.com')
        group = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=user, group=group)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(addon_id=5, format='json'), 200)
        self._check_it(self.private_views_gen(addon_id=5, format='json'), 403)

    def test_public_addon_contrib_stats_group(self):
        # Logged in with stats and contrib stats group.
        user = UserProfile.objects.get(email='nobodyspecial@mozilla.com')
        group1 = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=user, group=group1)
        group2 = Group.objects.create(name='Revenue Stats',
                                      rules='RevenueStats:View')
        GroupUser.objects.create(user=user, group=group2)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(addon_id=5, format='json'), 200)
        self._check_it(self.private_views_gen(addon_id=5, format='json'), 200)

    def test_public_addon_anonymous(self):
        # Not logged in
        self.client.logout()
        self._check_it(self.public_views_gen(addon_id=5, format='json'), 200)
        self._check_it(self.private_views_gen(addon_id=5, format='json'), 403)


class _TestCSVs(StatsTest):
    """Tests for CSV output of all known series views."""
    first_row = 5

    def test_downloads_series(self):
        response = self.get_view_response('stats.downloads_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
        eq_(len(row), 2, 'unexpected row length')
        date, count = row
        eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
        eq_(count, '50', 'unexpected count value: %s' % count)

    def test_usage_series(self):
        for url_args in [self.url_args, self.url_args_theme]:
            self.url_args = url_args

            response = self.get_view_response('stats.usage_series',
                                              group='month', format='csv')

            eq_(response.status_code, 200, 'unexpected http status')
            rows = list(csv.reader(response.content.split('\n')))
            # The first row of data after the header.
            row = rows[self.first_row]
            eq_(len(row), 2, 'unexpected row length')
            date, ave = row
            eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
            eq_(ave, '83', 'unexpected ADU average: %s' % ave)

    def test_contributions_series(self):
        response = self.get_view_response('stats.contributions_series',
                                          group='day', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
        eq_(len(row), 4, 'unexpected row length')
        date, total, count, ave = row
        eq_(date, '2009-06-02', 'unexpected date string: %s' % date)
        eq_(total, '4.98', 'unexpected contribution total: %s' % total)
        eq_(count, '2', 'unexpected contribution count: %s' % count)
        eq_(ave, '2.49', 'unexpected contribution average: %s' % ave)

    def test_sources_series(self):
        response = self.get_view_response('stats.sources_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
        eq_(len(row), 5, 'unexpected row length')
        date, count, source1, source2, source3 = row
        eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
        eq_(count, '50', 'unexpected count: %s' % count)
        eq_(source1, '25', 'unexpected source1 count: %s' % source1)
        eq_(source2, '15', 'unexpected source2 count: %s' % source2)
        eq_(source3, '10', 'unexpected source3 count: %s' % source3)

    def test_os_series(self):
        response = self.get_view_response('stats.os_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
        eq_(len(row), 5, 'unexpected row length')
        date, count, os1, os2, os3 = row
        eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
        eq_(count, '83', 'unexpected count: %s' % count)
        eq_(os1, '30', 'unexpected os1 count: %s' % os1)
        eq_(os2, '30', 'unexpected os2 count: %s' % os2)
        eq_(os3, '23', 'unexpected os3 count: %s' % os3)

    def test_locales_series(self):
        response = self.get_view_response('stats.locales_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
        eq_(len(row), 3, 'unexpected row length')
        date, count, locale1 = row
        eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
        eq_(count, '83', 'unexpected count: %s' % count)
        eq_(locale1, '83', 'unexpected locale1 count: %s' % locale1)

    def test_statuses_series(self):
        response = self.get_view_response('stats.statuses_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
        eq_(len(row), 4, 'unexpected row length')
        date, count, status1, status2 = row
        eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
        eq_(count, '83', 'unexpected count: %s' % count)
        eq_(status1, '77', 'unexpected status1 count: %s' % status1)
        eq_(status2, '6', 'unexpected status2 count: %s' % status2)

    def test_versions_series(self):
        response = self.get_view_response('stats.versions_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
        eq_(len(row), 4, 'unexpected row length')
        date, count, version1, version2 = row
        eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
        eq_(count, '83', 'unexpected count: %s' % count)
        eq_(version1, '58', 'unexpected version1 count: %s' % version1)
        eq_(version2, '25', 'unexpected version2 count: %s' % version2)

    def test_apps_series(self):
        response = self.get_view_response('stats.apps_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
        eq_(len(row), 3, 'unexpected row length')
        date, count, app1 = row
        eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
        eq_(count, '83', 'unexpected count: %s' % count)
        eq_(app1, '83', 'unexpected app1 count: %s' % app1)

    def test_no_cache(self):
        """Test that the csv or json is not caching, due to lack of data."""
        self.url_args = {'start': '20200101', 'end': '20200130', 'addon_id': 4}
        response = self.get_view_response('stats.versions_series', head=True,
                                          group='day', format='csv')
        eq_(response["cache-control"], 'max-age=0')

        self.url_args = {'start': '20200101', 'end': '20200130', 'addon_id': 4}
        response = self.get_view_response('stats.versions_series', head=True,
                                          group='day', format='json')
        eq_(response["cache-control"], 'max-age=0')

    def test_usage_series_no_data(self):
        url_args = [
            {'start': '20010101', 'end': '20010130', 'addon_id': 4},
            # Also test for themes.
            {'start': '20010101', 'end': '20010130', 'addon_id': 6}
        ]
        for url_arg in url_args:
            self.url_args = url_arg
            response = self.get_view_response('stats.usage_series',
                                              group='day', format='csv')

            eq_(response.status_code, 200)
            rows = list(csv.reader(response.content.split('\n')))
            eq_(len(rows), 6)
            eq_(rows[4], [])  # No fields
            eq_(rows[self.first_row], [])  # There is no data


class TestCacheControl(StatsTest):
    """Tests we set cache control headers"""

    def _test_cache_control(self):
        response = self.get_view_response('stats.downloads_series', head=True,
                                          group='month', format='json')
        assert response.get('cache-control', '').startswith('max-age='), (
            'Bad or no cache-control: %r' % response.get('cache-control', ''))


class TestLayout(StatsTest):

    def test_not_public_stats(self):
        r = self.client.get(reverse('stats.downloads', args=[4]))
        eq_(r.status_code, 404)

    def get_public_url(self):
        addon = amo.tests.addon_factory(public_stats=True)
        return reverse('stats.downloads', args=[addon.slug])

    def test_public_stats_page_loads(self):
        r = self.client.get(self.get_public_url())
        eq_(r.status_code, 200)

    def test_public_stats_stats_notes(self):
        r = self.client.get(self.get_public_url())
        eq_(pq(r.content)('#stats-note h2').length, 1)


class TestResponses(ESStatsTest):
    test_es = True

    def csv_eq(self, response, expected):
        # Drop the first 4 lines, which contain the header comment.
        content = response.content.splitlines()[4:]
        # Strip any extra spaces from the expected content.
        expected = [line.strip() for line in expected.splitlines()]
        self.assertListEqual(content, expected)

    def test_usage_json(self):
        for url_args in [self.url_args, self.url_args_theme]:
            self.url_args = url_args

            r = self.get_view_response('stats.usage_series', group='day',
                                       format='json')
            eq_(r.status_code, 200)
            self.assertListEqual(json.loads(r.content), [
                {'count': 1500, 'date': '2009-06-02', 'end': '2009-06-02'},
                {'count': 1000, 'date': '2009-06-01', 'end': '2009-06-01'},
            ])

    def test_usage_csv(self):
        for url_args in [self.url_args, self.url_args_theme]:
            self.url_args = url_args

            r = self.get_view_response('stats.usage_series', group='day',
                                       format='csv')
            eq_(r.status_code, 200)
            self.csv_eq(r,
                        """date,count
                           2009-06-02,1500
                           2009-06-01,1000""")

    def test_usage_by_app_json(self):
        r = self.get_view_response('stats.apps_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        self.assertListEqual(json.loads(r.content), [
            {
                "data": {
                    "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": {"4.0": 1500}
                },
                "count": 1500,
                "date": "2009-06-02",
                "end": "2009-06-02"
            },
            {
                "data": {
                    "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": {"4.0": 1000}
                },
                "count": 1000,
                "date": "2009-06-01",
                "end": "2009-06-01"
            }
        ])

    def test_usage_by_app_csv(self):
        r = self.get_view_response('stats.apps_series', group='day',
                                   format='csv')
        eq_(r.status_code, 200)
        self.csv_eq(r, """date,count,Firefox 4.0
                          2009-06-02,1500,1500
                          2009-06-01,1000,1000""")

    def test_usage_by_locale_json(self):
        r = self.get_view_response('stats.locales_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        self.assertListEqual(json.loads(r.content), [
            {
                "count": 1500,
                "date": "2009-06-02",
                "end": "2009-06-02",
                "data": {
                    u"Ελληνικά (el)": 400,
                    u"English (US) (en-us)": 300
                }
            },
            {
                "count": 1000,
                "date": "2009-06-01",
                "end": "2009-06-01",
                "data": {
                    u"Ελληνικά (el)": 400,
                    u"English (US) (en-us)": 300
                }
            }
        ])

    def test_usage_by_locale_csv(self):
        r = self.get_view_response('stats.locales_series', group='day',
                                   format='csv')
        eq_(r.status_code, 200)
        self.csv_eq(r, """date,count,English (US) (en-us),Ελληνικά (el)
                          2009-06-02,1500,300,400
                          2009-06-01,1000,300,400""")

    def test_usage_by_os_json(self):
        r = self.get_view_response('stats.os_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        self.assertListEqual(json.loads(r.content), [
            {
                "count": 1500,
                "date": "2009-06-02",
                "end": "2009-06-02",
                "data": {
                    "Linux": 400,
                    "Windows": 500
                }
            },
            {
                "count": 1000,
                "date": "2009-06-01",
                "end": "2009-06-01",
                "data": {
                    "Linux": 300,
                    "Windows": 400
                }
            }
        ])

    def test_usage_by_os_csv(self):
        r = self.get_view_response('stats.os_series', head=True, group='day',
                                   format='csv')
        eq_(r.status_code, 200)

    def test_usage_by_version_json(self):
        r = self.get_view_response('stats.versions_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        self.assertListEqual(json.loads(r.content), [
            {
                "count": 1500,
                "date": "2009-06-02",
                "end": "2009-06-02",
                "data": {
                    "1.0": 550,
                    "2.0": 950
                }
            },
            {
                "count": 1000,
                "date": "2009-06-01",
                "end": "2009-06-01",
                "data": {
                    "1.0": 200,
                    "2.0": 800
                }
            }
        ])

    def test_usage_by_version_csv(self):
        r = self.get_view_response('stats.versions_series', group='day',
                                   format='csv')
        eq_(r.status_code, 200)
        self.csv_eq(r, """date,count,2.0,1.0
                          2009-06-02,1500,950,550
                          2009-06-01,1000,800,200""")

    def test_usage_by_status_json(self):
        r = self.get_view_response('stats.statuses_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        self.assertListEqual(json.loads(r.content), [
            {
                "count": 1500,
                "date": "2009-06-02",
                "end": "2009-06-02",
                "data": {
                    "userDisabled": 130,
                    "userEnabled": 1370
                }
            },
            {
                "count": 1000,
                "date": "2009-06-01",
                "end": "2009-06-01",
                "data": {
                    "userDisabled": 50,
                    "userEnabled": 950
                }
            }
        ])

    def test_usage_by_status_csv(self):
        r = self.get_view_response('stats.statuses_series', group='day',
                                   format='csv')
        eq_(r.status_code, 200)
        self.csv_eq(r, """date,count,userEnabled,userDisabled
                          2009-06-02,1500,1370,130
                          2009-06-01,1000,950,50""")

    def test_overview(self):
        r = self.get_view_response('stats.overview_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        # These are the dates from the fixtures. The return value will have
        # dates in between filled with zeroes.
        expected_data = [
            {"date": "2009-09-03",
             "data": {
                 "downloads": 10,
                 "updates": 0,
             },
            },
            {"date": "2009-08-03",
             "data": {
                 "downloads": 10,
                 "updates": 0,
             },
            },
            {"date": "2009-07-03",
             "data": {
                 "downloads": 10,
                 "updates": 0,
             },
            },
            {"date": "2009-06-28",
             "data": {
                 "downloads": 10,
                 "updates": 0,
             },
            },
            {"date": "2009-06-20",
             "data": {
                 "downloads": 10,
                 "updates": 0,
             },
            },
            {"date": "2009-06-12",
             "data": {
                 "downloads": 10,
                 "updates": 0,
             },
            },
            {"date": "2009-06-07",
             "data": {
                 "downloads": 10,
                 "updates": 0,
             },
            },
            {"date": "2009-06-02",
             "data": {
                 "downloads": 0,
                 "updates": 1500,
             },
            },
            {"date": "2009-06-01",
             "data": {
                 "downloads": 10,
                 "updates": 1000,
             },
            }
        ]
        actual_data = json.loads(r.content)
        # Make sure they match up at the front and back.
        eq_(actual_data[0]['date'], expected_data[0]['date'])
        eq_(actual_data[-1]['date'], expected_data[-1]['date'])
        end_date = expected_data[-1]['date']

        expected, actual = iter(expected_data), iter(actual_data)
        next_expected, next_actual = next(expected), next(actual)
        while 1:
            if next_expected['date'] == next_actual['date']:
                # If they match it's a date we have data for.
                self.assertDictEqual(next_expected, next_actual)
                if next_expected['date'] == end_date:
                    break
                next_expected, next_actual = next(expected), next(actual)
            else:
                # Otherwise just check that the data is zeroes.
                self.assertDictEqual(next_actual['data'],
                                     {'downloads': 0, 'updates': 0})
                next_actual = next(actual)

    def test_downloads_json(self):
        r = self.get_view_response('stats.downloads_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        self.assertListEqual(json.loads(r.content), [
            {"count": 10, "date": "2009-09-03", "end": "2009-09-03"},
            {"count": 10, "date": "2009-08-03", "end": "2009-08-03"},
            {"count": 10, "date": "2009-07-03", "end": "2009-07-03"},
            {"count": 10, "date": "2009-06-28", "end": "2009-06-28"},
            {"count": 10, "date": "2009-06-20", "end": "2009-06-20"},
            {"count": 10, "date": "2009-06-12", "end": "2009-06-12"},
            {"count": 10, "date": "2009-06-07", "end": "2009-06-07"},
            {"count": 10, "date": "2009-06-01", "end": "2009-06-01"},
        ])

    def test_downloads_csv(self):
        r = self.get_view_response('stats.downloads_series', group='day',
                                   format='csv')
        eq_(r.status_code, 200)
        self.csv_eq(r, """date,count
                          2009-09-03,10
                          2009-08-03,10
                          2009-07-03,10
                          2009-06-28,10
                          2009-06-20,10
                          2009-06-12,10
                          2009-06-07,10
                          2009-06-01,10""")

    def test_downloads_sources_json(self):
        r = self.get_view_response('stats.sources_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        self.assertListEqual(json.loads(r.content), [
            {"count": 10,
             "date": "2009-09-03",
             "end": "2009-09-03",
             "data": {"api": 2, "search": 3}
            },
            {"count": 10,
             "date": "2009-08-03",
             "end": "2009-08-03",
             "data": {"api": 2, "search": 3}
            },
            {"count": 10,
             "date": "2009-07-03",
             "end": "2009-07-03",
             "data": {"api": 2, "search": 3}
            },
            {"count": 10,
             "date": "2009-06-28",
             "end": "2009-06-28",
             "data": {"api": 2, "search": 3}
            },
            {"count": 10,
             "date": "2009-06-20",
             "end": "2009-06-20",
             "data": {"api": 2, "search": 3}
            },
            {"count": 10,
             "date": "2009-06-12",
             "end": "2009-06-12",
             "data": {"api": 2, "search": 3}
            },
            {"count": 10,
             "date": "2009-06-07",
             "end": "2009-06-07",
             "data": {"api": 2, "search": 3}
            },
            {"count": 10,
             "date": "2009-06-01",
             "end": "2009-06-01",
             "data": {"api": 2, "search": 3}
            }
        ])

    def test_downloads_sources_csv(self):
        r = self.get_view_response('stats.sources_series', group='day',
                                   format='csv')
        eq_(r.status_code, 200)
        self.csv_eq(r, """date,count,search,api
                          2009-09-03,10,3,2
                          2009-08-03,10,3,2
                          2009-07-03,10,3,2
                          2009-06-28,10,3,2
                          2009-06-20,10,3,2
                          2009-06-12,10,3,2
                          2009-06-07,10,3,2
                          2009-06-01,10,3,2""")

    def test_contributions_series_json(self):
        r = self.get_view_response('stats.contributions_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        self.assertListEqual(json.loads(r.content), [
            {
                "count": 2,
                "date": "2009-06-02",
                "average": 2.49,
                "total": 4.98,
                "end": "2009-06-02"
            },
            {
                "count": 1,
                "date": "2009-06-01",
                "average": 5.0,
                "total": 5.0,
                "end": "2009-06-01"
            }
        ])

    def test_contributions_series_csv(self):
        r = self.get_view_response('stats.contributions_series', group='day',
                                   format='csv')
        eq_(r.status_code, 200)
        self.csv_eq(r, """date,count,total,average
                          2009-06-02,2,4.98,2.49
                          2009-06-01,1,5.0,5.0""")


# Test the SQL query by using known dates, for weeks and months etc.
class TestSiteQuery(amo.tests.TestCase):

    def setUp(self):
        self.start = datetime.date(2012, 1, 1)
        self.end = datetime.date(2012, 1, 31)
        for k in xrange(0, 15):
            for name in ['addon_count_new', 'version_count_new']:
                date_ = self.start + datetime.timedelta(days=k)
                GlobalStat.objects.create(date=date_, name=name, count=k)

    def test_day_grouping(self):
        res = views._site_query('date', self.start, self.end)[0]
        eq_(len(res), 14)
        eq_(res[0]['data']['addons_created'], 14)
        # Make sure we are returning counts as integers, otherwise
        # DjangoJSONSerializer will map them to strings.
        eq_(type(res[0]['data']['addons_created']), int)
        eq_(res[0]['date'], '2012-01-15')

    def test_week_grouping(self):
        res = views._site_query('week', self.start, self.end)[0]
        eq_(len(res), 3)
        eq_(res[1]['data']['addons_created'], 70)
        eq_(res[1]['date'], '2012-01-08')

    def test_month_grouping(self):
        res = views._site_query('month', self.start, self.end)[0]
        eq_(len(res), 1)
        eq_(res[0]['data']['addons_created'], (14 * (14 + 1)) / 2)
        eq_(res[0]['date'], '2012-01-02')

    def test_period(self):
        self.assertRaises(AssertionError, views._site_query, 'not_period',
                          self.start, self.end)


@mock.patch('stats.views._site_query')
class TestSite(amo.tests.TestCase):

    def tests_period(self, _site_query):
        _site_query.return_value = ['.', '.']
        for period in ['date', 'week', 'month']:
            self.client.get(reverse('stats.site', args=['json', period]))
            eq_(_site_query.call_args[0][0], period)

    def tests_period_day(self, _site_query):
        _site_query.return_value = ['.', '.']
        start = (datetime.date.today() - datetime.timedelta(days=3))
        end = datetime.date.today()
        self.client.get(reverse('stats.site.new',
                        args=['day', start.strftime('%Y%m%d'),
                              end.strftime('%Y%m%d'), 'json']))
        eq_(_site_query.call_args[0][0], 'date')
        eq_(_site_query.call_args[0][1], start)
        eq_(_site_query.call_args[0][2], end)

    def test_csv(self, _site_query):
        _site_query.return_value = [[], []]
        res = self.client.get(reverse('stats.site', args=['csv', 'date']))
        assert res._headers['content-type'][1].startswith('text/csv')

    def test_json(self, _site_query):
        _site_query.return_value = [[], []]
        res = self.client.get(reverse('stats.site', args=['json', 'date']))
        assert res._headers['content-type'][1].startswith('text/json')

    def tests_no_date(self, _site_query):
        _site_query.return_value = ['.', '.']
        self.client.get(reverse('stats.site', args=['json', 'date']))
        eq_(_site_query.call_args[0][1],
            datetime.date.today() - datetime.timedelta(days=365))
        eq_(_site_query.call_args[0][2], datetime.date.today())


class TestCollections(amo.tests.ESTestCase):
    fixtures = ['bandwagon/test_models', 'base/users',
                'base/addon_3615', 'base/addon_5369']

    def setUp(self):
        super(TestCollections, self).setUp()
        self.today = datetime.date.today()
        self.collection = Collection.objects.get(pk=512)
        self.url = reverse('stats.collection',
                           args=[self.collection.uuid, 'json'])

        for x in xrange(1, 4):
            data = {'date': self.today - datetime.timedelta(days=x - 1),
                    'id': int(self.collection.pk), 'count': x,
                    'data': search.es_dict({'subscribers': x, 'votes_up': x,
                                            'votes_down': x, 'downloads': x})}
            CollectionCount.index(data, id='%s-%s' % (x, self.collection.pk))

        self.refresh('stats')

    def tests_collection_anon(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 403)

    def tests_collection_user(self):
        self.client.login(username='admin@mozilla.com', password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

    def tests_collection_admin(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.collection.update(author=None)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

    def test_collection_json(self):
        self.client.login(username='admin@mozilla.com', password='password')
        res = self.client.get(self.url)
        content = json.loads(res.content)
        eq_(len(content), 3)
        eq_(content[0]['count'], 1)
        eq_(content[0]['data']['votes_down'], 1)
        eq_(content[0]['data']['downloads'], 1)

    def test_collection_csv(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.url = reverse('stats.collection',
                           args=[self.collection.uuid, 'csv'])
        res = self.client.get(self.url)
        date = (self.today.strftime('%Y-%m-%d'))
        assert '%s,1,1,1,1,1' % date in res.content

    def get_url(self, start, end):
        return reverse('collections.stats.subscribers_series',
                       args=[self.collection.author.username,
                             self.collection.slug, 'day',
                             start.strftime('%Y%m%d'),
                             end.strftime('%Y%m%d'), 'json'])

    def test_collection_one_day(self):
        self.client.login(username='admin@mozilla.com', password='password')
        url = self.get_url(self.today, self.today)
        res = self.client.get(url)
        content = json.loads(res.content)
        eq_(len(content), 1)
        eq_(content[0]['date'], self.today.strftime('%Y-%m-%d'))

    def test_collection_range(self):
        self.client.login(username='admin@mozilla.com', password='password')
        yesterday = self.today - datetime.timedelta(days=1)
        day_before = self.today - datetime.timedelta(days=2)
        url = self.get_url(day_before, yesterday)
        res = self.client.get(url)
        content = json.loads(res.content)
        eq_(len(content), 2)
        eq_(content[0]['date'], yesterday.strftime('%Y-%m-%d'))
        eq_(content[1]['date'], day_before.strftime('%Y-%m-%d'))


class TestXssOnAddonName(amo.tests.TestCase):
    fixtures = ['base/addon_3615', ]

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.name = "<script>alert('hé')</script>"
        self.escaped = "&lt;script&gt;alert(&#39;h\xc3\xa9&#39;)&lt;/script&gt;"
        self.addon.name = self.name
        self.addon.save()

    def assertNameAndNoXSS(self, url):
        response = self.client.get(url)
        assert self.name not in response.content
        assert self.escaped in response.content

    def test_stats_page(self):
        url = reverse('stats.overview', args=[self.addon.slug])
        self.client.login(username='del@icio.us', password='password')
        self.assertNameAndNoXSS(url)
