# -*- coding: utf-8 -*-
import csv
import datetime
import json

from django.http import Http404
from django.test.client import RequestFactory

import mock

from pyquery import PyQuery as pq

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import TestCase, version_factory
from olympia.amo.urlresolvers import reverse
from olympia.bandwagon.models import Collection
from olympia.stats import search, tasks, views
from olympia.stats.models import (
    CollectionCount, DownloadCount, GlobalStat, ThemeUserCount, UpdateCount)
from olympia.users.models import UserProfile


class StatsTest(TestCase):
    fixtures = ['stats/test_views.json', 'stats/test_models.json']

    def setUp(self):
        """Setup some reasonable testing defaults."""
        super(StatsTest, self).setUp()
        # Default url_args to an addon and range with data.
        self.url_args = {'start': '20090601', 'end': '20090930', 'addon_id': 4}
        self.url_args_theme = {'start': '20090601', 'end': '20090930',
                               'addon_id': 6}
        # We use fixtures with fixed add-on pks. That causes the add-ons to be
        # in a weird state that we have to fix.
        # For the persona (pk=6) the current_version needs to be set manually
        # because otherwise the version can't be found, as it has no files.
        # For the rest we simply add a version and it will automatically be
        # picked up as the current_version.
        persona_addon = Addon.objects.get(pk=6)
        version_factory(addon=Addon.objects.get(pk=4))
        version_factory(addon=Addon.objects.get(pk=5))
        persona_version = version_factory(addon=persona_addon)
        persona_addon.update(_current_version=persona_version)
        Addon.objects.filter(id__in=(4, 5, 6)).update(status=amo.STATUS_PUBLIC)
        # Most tests don't care about permissions.
        self.login_as_admin()

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


class TestUnlistedAddons(StatsTest):

    def setUp(self):
        super(TestUnlistedAddons, self).setUp()
        addon = Addon.objects.get(pk=4)
        addon.update(public_stats=True)
        self.make_addon_unlisted(addon)

    def test_no_stats_for_unlisted_addon(self):
        """All the views for the stats return 404 for unlisted addons."""
        self.login_as_visitor()

        self._check_it(self.public_views_gen(format='json'), 404)

    def test_stats_available_for_admins(self):
        """
        All the views for the stats are available to admins for
        unlisted addons.
        """
        self.login_as_admin()
        self._check_it(self.public_views_gen(format='json'), 200)


class TestListedAddons(StatsTest):

    def setUp(self):
        super(TestListedAddons, self).setUp()
        self.addon = Addon.objects.get(pk=4)
        self.someuser = UserProfile.objects.get(
            email='nobodyspecial@mozilla.com')

    def test_private_stats_for_listed_addon(self):
        self.addon.update(public_stats=False)
        self.login_as_visitor()
        self._check_it(self.public_views_gen(format='json'), 403)

        AddonUser.objects.create(user=self.someuser, addon=self.addon)
        self._check_it(self.public_views_gen(format='json'), 200)

    def test_stats_for_mozilla_disabled_addon(self):
        self.addon.update(status=amo.STATUS_DISABLED)

        # Public users should not see stats
        self.client.logout()
        self._check_it(self.public_views_gen(format='json'), 404)

        # Developers should not see stats
        AddonUser.objects.create(user=self.someuser, addon=self.addon)
        self._check_it(self.public_views_gen(format='json'), 404)

        # Admins should see stats
        self.login_as_admin()
        self._check_it(self.public_views_gen(format='json'), 200)

    def test_stats_for_user_disabled_addon(self):
        self.addon.update(disabled_by_user=True)

        # Public users should not see stats
        self.client.logout()
        self._check_it(self.public_views_gen(format='json'), 404)

        # Developers should not see stats
        AddonUser.objects.create(user=self.someuser, addon=self.addon)
        self._check_it(self.public_views_gen(format='json'), 404)

        # Admins should see stats
        self.login_as_admin()
        self._check_it(self.public_views_gen(format='json'), 200)


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

    def csv_eq(self, response, expected):
        content = csv.DictReader(
            # Drop lines that are comments.
            filter(lambda row: row[0] != '#', response.content.splitlines()))
        expected = csv.DictReader(
            # Strip any extra spaces from the expected content.
            line.strip() for line in expected.splitlines())
        assert tuple(content) == tuple(expected)


class TestSeriesSecurity(StatsTest):
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

    def test_public_addon_no_groups(self):
        # Logged in but no groups
        self.login_as_visitor()
        self._check_it(self.public_views_gen(addon_id=5, format='json'), 200)

    def test_public_addon_stats_group(self):
        # Logged in with stats group.
        user = UserProfile.objects.get(email='nobodyspecial@mozilla.com')
        group = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=user, group=group)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(addon_id=5, format='json'), 200)

    def test_public_addon_anonymous(self):
        # Not logged in
        self.client.logout()
        self._check_it(self.public_views_gen(addon_id=5, format='json'), 200)


class TestCSVs(ESStatsTest):
    """Tests for CSV output of all known series views."""

    def test_downloads_series(self):
        response = self.get_view_response('stats.downloads_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(response, """date,count
                                 2009-09-03,10
                                 2009-08-03,10
                                 2009-07-03,10
                                 2009-06-28,10
                                 2009-06-20,10
                                 2009-06-12,10
                                 2009-06-07,10
                                 2009-06-01,10""")

    def test_usage_series(self):
        for url_args in [self.url_args, self.url_args_theme]:
            self.url_args = url_args

            response = self.get_view_response('stats.usage_series',
                                              group='month', format='csv')

            assert response.status_code == 200
            self.csv_eq(response, """date,count
                                     2009-06-02,1500
                                     2009-06-01,1000""")

    def test_sources_series(self):
        response = self.get_view_response('stats.sources_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(response, """date,count,search,api
                                 2009-09-03,10,3,2
                                 2009-08-03,10,3,2
                                 2009-07-03,10,3,2
                                 2009-06-28,10,3,2
                                 2009-06-20,10,3,2
                                 2009-06-12,10,3,2
                                 2009-06-07,10,3,2
                                 2009-06-01,10,3,2""")

    def test_os_series(self):
        response = self.get_view_response('stats.os_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(response, """date,count,Windows,Linux
                                 2009-06-02,1500,500,400
                                 2009-06-01,1000,400,300""")

    def test_locales_series(self):
        response = self.get_view_response('stats.locales_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(
            response,
            """date,count,English (US) (en-us),"""
            """\xce\x95\xce\xbb\xce\xbb\xce\xb7\xce\xbd\xce\xb9\xce\xba"""
            """\xce\xac (el)
               2009-06-02,1500,300,400
               2009-06-01,1000,300,400""")

    def test_statuses_series(self):
        response = self.get_view_response('stats.statuses_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(response, """date,count,userEnabled,userDisabled
                                 2009-06-02,1500,1370,130
                                 2009-06-01,1000,950,50""")

    def test_versions_series(self):
        response = self.get_view_response('stats.versions_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(response, """date,count,2.0,1.0
                                 2009-06-02,1500,950,550
                                 2009-06-01,1000,800,200""")

    def test_apps_series(self):
        response = self.get_view_response('stats.apps_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(response, """date,count,Firefox 4.0
                                 2009-06-02,1500,1500
                                 2009-06-01,1000,1000""")

    def test_no_cache(self):
        """Test that the csv or json is not caching, due to lack of data."""
        self.url_args = {'start': '20200101', 'end': '20200130', 'addon_id': 4}
        response = self.get_view_response('stats.versions_series', head=True,
                                          group='day', format='csv')

        assert set(response['cache-control'].split(', ')) == (
            {'max-age=0', 'no-cache', 'no-store', 'must-revalidate'})

        self.url_args = {'start': '20200101', 'end': '20200130', 'addon_id': 4}
        response = self.get_view_response('stats.versions_series', head=True,
                                          group='day', format='json')
        assert set(response['cache-control'].split(', ')) == (
            {'max-age=0', 'no-cache', 'no-store', 'must-revalidate'})

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

            assert response.status_code == 200
            self.csv_eq(response, """date,count""")


class TestCacheControl(StatsTest):
    """Tests we set cache control headers"""

    def _test_cache_control(self):
        response = self.get_view_response('stats.downloads_series', head=True,
                                          group='month', format='json')
        assert response.get('cache-control', '').startswith('max-age='), (
            'Bad or no cache-control: %r' % response.get('cache-control', ''))


class TestLayout(StatsTest):

    def test_not_public_stats(self):
        self.login_as_visitor()
        addon = amo.tests.addon_factory(public_stats=False)
        response = self.client.get(self.get_public_url(addon))
        assert response.status_code == 403

    def get_public_url(self, addon):
        return reverse('stats.downloads', args=[addon.slug])

    def test_public_stats_page_loads(self):
        addon = amo.tests.addon_factory(public_stats=True)
        response = self.client.get(self.get_public_url(addon))
        assert response.status_code == 200

    def test_public_stats_stats_notes(self):
        addon = amo.tests.addon_factory(public_stats=True)
        response = self.client.get(self.get_public_url(addon))
        assert pq(response.content)('#stats-note h2').length == 1


class TestResponses(ESStatsTest):

    def test_usage_json(self):
        for url_args in [self.url_args, self.url_args_theme]:
            self.url_args = url_args

            r = self.get_view_response('stats.usage_series', group='day',
                                       format='json')
            assert r.status_code == 200
            self.assertListEqual(json.loads(r.content), [
                {'count': 1500, 'date': '2009-06-02', 'end': '2009-06-02'},
                {'count': 1000, 'date': '2009-06-01', 'end': '2009-06-01'},
            ])

    def test_usage_csv(self):
        for url_args in [self.url_args, self.url_args_theme]:
            self.url_args = url_args

            r = self.get_view_response('stats.usage_series', group='day',
                                       format='csv')
            assert r.status_code == 200
            self.csv_eq(r,
                        """date,count
                           2009-06-02,1500
                           2009-06-01,1000""")

    def test_usage_by_app_json(self):
        r = self.get_view_response('stats.apps_series', group='day',
                                   format='json')
        assert r.status_code == 200
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
        assert r.status_code == 200
        self.csv_eq(r, """date,count,Firefox 4.0
                          2009-06-02,1500,1500
                          2009-06-01,1000,1000""")

    def test_usage_by_locale_json(self):
        r = self.get_view_response('stats.locales_series', group='day',
                                   format='json')
        assert r.status_code == 200
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
        assert r.status_code == 200
        self.csv_eq(r, """date,count,English (US) (en-us),Ελληνικά (el)
                          2009-06-02,1500,300,400
                          2009-06-01,1000,300,400""")

    def test_usage_by_os_json(self):
        r = self.get_view_response('stats.os_series', group='day',
                                   format='json')
        assert r.status_code == 200
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
        assert r.status_code == 200

    def test_usage_by_version_json(self):
        r = self.get_view_response('stats.versions_series', group='day',
                                   format='json')
        assert r.status_code == 200
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
        assert r.status_code == 200
        self.csv_eq(r, """date,count,2.0,1.0
                          2009-06-02,1500,950,550
                          2009-06-01,1000,800,200""")

    def test_usage_by_status_json(self):
        r = self.get_view_response('stats.statuses_series', group='day',
                                   format='json')
        assert r.status_code == 200
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
        assert r.status_code == 200
        self.csv_eq(r, """date,count,userEnabled,userDisabled
                          2009-06-02,1500,1370,130
                          2009-06-01,1000,950,50""")

    def test_overview(self):
        r = self.get_view_response('stats.overview_series', group='day',
                                   format='json')
        assert r.status_code == 200
        # These are the dates from the fixtures. The return value will have
        # dates in between filled with zeroes.
        expected_data = [
            {"date": "2009-09-03",
             "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-08-03",
             "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-07-03",
             "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-28",
             "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-20",
             "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-12",
             "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-07",
             "data": {"downloads": 10, "updates": 0}},
            {"date": "2009-06-02",
             "data": {"downloads": 0, "updates": 1500}},
            {"date": "2009-06-01",
             "data": {"downloads": 10, "updates": 1000}}
        ]
        actual_data = json.loads(r.content)
        # Make sure they match up at the front and back.
        assert actual_data[0]['date'] == expected_data[0]['date']
        assert actual_data[-1]['date'] == expected_data[-1]['date']
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
        assert r.status_code == 200
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
        assert r.status_code == 200
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
        assert r.status_code == 200
        self.assertListEqual(json.loads(r.content), [
            {"count": 10,
             "date": "2009-09-03",
             "end": "2009-09-03",
             "data": {"api": 2, "search": 3}},
            {"count": 10,
             "date": "2009-08-03",
             "end": "2009-08-03",
             "data": {"api": 2, "search": 3}},
            {"count": 10,
             "date": "2009-07-03",
             "end": "2009-07-03",
             "data": {"api": 2, "search": 3}},
            {"count": 10,
             "date": "2009-06-28",
             "end": "2009-06-28",
             "data": {"api": 2, "search": 3}},
            {"count": 10,
             "date": "2009-06-20",
             "end": "2009-06-20",
             "data": {"api": 2, "search": 3}},
            {"count": 10,
             "date": "2009-06-12",
             "end": "2009-06-12",
             "data": {"api": 2, "search": 3}},
            {"count": 10,
             "date": "2009-06-07",
             "end": "2009-06-07",
             "data": {"api": 2, "search": 3}},
            {"count": 10,
             "date": "2009-06-01",
             "end": "2009-06-01",
             "data": {"api": 2, "search": 3}}
        ])

    def test_downloads_sources_csv(self):
        r = self.get_view_response('stats.sources_series', group='day',
                                   format='csv')
        assert r.status_code == 200
        self.csv_eq(r, """date,count,search,api
                          2009-09-03,10,3,2
                          2009-08-03,10,3,2
                          2009-07-03,10,3,2
                          2009-06-28,10,3,2
                          2009-06-20,10,3,2
                          2009-06-12,10,3,2
                          2009-06-07,10,3,2
                          2009-06-01,10,3,2""")


# Test the SQL query by using known dates, for weeks and months etc.
class TestSiteQuery(TestCase):

    def setUp(self):
        super(TestSiteQuery, self).setUp()
        self.start = datetime.date(2012, 1, 1)
        self.end = datetime.date(2012, 1, 31)
        for k in xrange(0, 15):
            for name in ['addon_count_new', 'version_count_new']:
                date_ = self.start + datetime.timedelta(days=k)
                GlobalStat.objects.create(date=date_, name=name, count=k)

    def test_day_grouping(self):
        res = views._site_query('date', self.start, self.end)[0]
        assert len(res) == 14
        assert res[0]['data']['addons_created'] == 14
        # Make sure we are returning counts as integers, otherwise
        # DjangoJSONSerializer will map them to strings.
        assert type(res[0]['data']['addons_created']) == int
        assert res[0]['date'] == '2012-01-15'

    def test_week_grouping(self):
        res = views._site_query('week', self.start, self.end)[0]
        assert len(res) == 3
        assert res[1]['data']['addons_created'] == 70
        assert res[1]['date'] == '2012-01-08'

    def test_month_grouping(self):
        res = views._site_query('month', self.start, self.end)[0]
        assert len(res) == 1
        assert res[0]['data']['addons_created'] == (14 * (14 + 1)) / 2
        assert res[0]['date'] == '2012-01-02'

    def test_period(self):
        self.assertRaises(AssertionError, views._site_query, 'not_period',
                          self.start, self.end)


@mock.patch('olympia.stats.views._site_query')
class TestSite(TestCase):

    def tests_period(self, _site_query):
        _site_query.return_value = ['.', '.']
        for period in ['date', 'week', 'month']:
            self.client.get(reverse('stats.site', args=['json', period]))
            assert _site_query.call_args[0][0] == period

    def tests_period_day(self, _site_query):
        _site_query.return_value = ['.', '.']
        start = (datetime.date.today() - datetime.timedelta(days=3))
        end = datetime.date.today()
        self.client.get(reverse('stats.site.new',
                        args=['day', start.strftime('%Y%m%d'),
                              end.strftime('%Y%m%d'), 'json']))
        assert _site_query.call_args[0][0] == 'date'
        assert _site_query.call_args[0][1] == start
        assert _site_query.call_args[0][2] == end

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
        assert _site_query.call_args[0][1] == (
            datetime.date.today() - datetime.timedelta(days=365))
        assert _site_query.call_args[0][2] == datetime.date.today()


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
        assert res.status_code == 403

    def tests_collection_user(self):
        self.client.login(email='admin@mozilla.com')
        res = self.client.get(self.url)
        assert res.status_code == 200

    def tests_collection_admin(self):
        self.client.login(email='admin@mozilla.com')
        self.collection.update(author=None)
        res = self.client.get(self.url)
        assert res.status_code == 200

    def test_collection_json(self):
        self.client.login(email='admin@mozilla.com')
        res = self.client.get(self.url)
        content = json.loads(res.content)
        assert len(content) == 3
        assert content[0]['count'] == 1
        assert content[0]['data']['votes_down'] == 1
        assert content[0]['data']['downloads'] == 1

    def test_collection_csv(self):
        self.client.login(email='admin@mozilla.com')
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
        self.client.login(email='admin@mozilla.com')
        url = self.get_url(self.today, self.today)
        res = self.client.get(url)
        content = json.loads(res.content)
        assert len(content) == 1
        assert content[0]['date'] == self.today.strftime('%Y-%m-%d')

    def test_collection_range(self):
        self.client.login(email='admin@mozilla.com')
        yesterday = self.today - datetime.timedelta(days=1)
        day_before = self.today - datetime.timedelta(days=2)
        url = self.get_url(day_before, yesterday)
        res = self.client.get(url)
        content = json.loads(res.content)
        assert len(content) == 2
        assert content[0]['date'] == yesterday.strftime('%Y-%m-%d')
        assert content[1]['date'] == day_before.strftime('%Y-%m-%d')


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
