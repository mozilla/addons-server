# -*- coding: utf-8 -*-
import csv
import json

from django.http import Http404
from django.test.client import RequestFactory
from django.utils.encoding import force_text

from pyquery import PyQuery as pq

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import (TestCase, version_factory, addon_factory,
                               user_factory)
from olympia.amo.urlresolvers import reverse, resolve
from olympia.stats import tasks, views
from olympia.stats.models import DownloadCount, UpdateCount
from olympia.users.models import UserProfile


class StatsTest(TestCase):
    fixtures = ['stats/test_views.json', 'stats/test_models.json']

    def setUp(self):
        """Setup some reasonable testing defaults."""
        super(StatsTest, self).setUp()
        # Default url_args to an addon and range with data.
        self.url_args = {'start': '20090601', 'end': '20090930', 'addon_id': 4}
        # We use fixtures with fixed add-on pks. That causes the add-ons to be
        # in a weird state that we have to fix.
        # We simply add a version and it will automatically be
        # picked up as the current_version.
        version_factory(addon=Addon.objects.get(pk=4))
        version_factory(addon=Addon.objects.get(pk=5))
        Addon.objects.filter(id__in=(4, 5)).update(status=amo.STATUS_APPROVED)
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
        self.refresh('stats')

    def csv_eq(self, response, expected):
        content = force_text(response.content)
        content_csv = csv.DictReader(
            # Drop lines that are comments.
            filter(lambda row: row[0] != '#', content.splitlines()))
        expected = force_text(expected)
        expected_csv = csv.DictReader(
            # Strip any extra spaces from the expected content.
            line.strip() for line in expected.splitlines())
        assert tuple(content_csv) == tuple(expected_csv)


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
        self.csv_eq(response, """date,count,api,search
                                 2009-09-03,10,2,3
                                 2009-08-03,10,2,3
                                 2009-07-03,10,2,3
                                 2009-06-28,10,2,3
                                 2009-06-20,10,2,3
                                 2009-06-12,10,2,3
                                 2009-06-07,10,2,3
                                 2009-06-01,10,2,3""")

    def test_os_series(self):
        response = self.get_view_response('stats.os_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(response, """date,count,Linux,Windows
                                 2009-06-02,1500,400,500
                                 2009-06-01,1000,300,400""")

    def test_locales_series(self):
        response = self.get_view_response('stats.locales_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(
            response,
            u"""date,count,English (US) (en-us),Espa\xf1ol (de M\xe9xico) (es-mx),Ελληνικά (el)
               2009-06-02,1500,300,400,400
               2009-06-01,1000,300,400,400""")  # noqa

    def test_statuses_series(self):
        response = self.get_view_response('stats.statuses_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(response, """date,count,userDisabled,userEnabled
                                 2009-06-02,1500,130,1370
                                 2009-06-01,1000,50,950""")

    def test_versions_series(self):
        response = self.get_view_response('stats.versions_series',
                                          group='month', format='csv')

        assert response.status_code == 200
        self.csv_eq(response, """date,count,1.0,2.0
                                 2009-06-02,1500,550,950
                                 2009-06-01,1000,200,800""")

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
        assert response.status_code == 200
        assert set(response['cache-control'].split(', ')) == (
            {'max-age=0', 'no-cache', 'no-store', 'must-revalidate'})

        self.url_args = {'start': '20200101', 'end': '20200130', 'addon_id': 4}
        response = self.get_view_response('stats.versions_series', head=True,
                                          group='day', format='json')
        assert response.status_code == 200
        assert set(response['cache-control'].split(', ')) == (
            {'max-age=0', 'no-cache', 'no-store', 'must-revalidate'})

    def test_usage_series_no_data(self):
        url_args = [
            {'start': '20010101', 'end': '20010130', 'addon_id': 4},
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
        response = self.get_view_response(
            'stats.usage_series', group='day', format='json')
        assert response.status_code == 200
        self.assertListEqual(json.loads(force_text(response.content)), [
            {'count': 1500, 'date': '2009-06-02', 'end': '2009-06-02'},
            {'count': 1000, 'date': '2009-06-01', 'end': '2009-06-01'},
        ])

    def test_usage_csv(self):
        response = self.get_view_response(
            'stats.usage_series', group='day', format='csv')
        assert response.status_code == 200
        self.csv_eq(response,
                    """date,count
                       2009-06-02,1500
                       2009-06-01,1000""")

    def test_usage_by_app_json(self):
        response = self.get_view_response(
            'stats.apps_series', group='day', format='json')
        assert response.status_code == 200
        self.assertListEqual(json.loads(force_text(response.content)), [
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
        response = self.get_view_response(
            'stats.apps_series', group='day', format='csv')
        assert response.status_code == 200
        self.csv_eq(response, """date,count,Firefox 4.0
                                 2009-06-02,1500,1500
                                 2009-06-01,1000,1000""")

    def test_usage_by_locale_json(self):
        response = self.get_view_response(
            'stats.locales_series', group='day', format='json')
        assert response.status_code == 200
        self.assertListEqual(json.loads(force_text(response.content)), [
            {
                "count": 1500,
                "date": "2009-06-02",
                "end": "2009-06-02",
                "data": {
                    u"Ελληνικά (el)": 400,
                    u'Espa\xf1ol (de M\xe9xico) (es-mx)': 400,
                    u"English (US) (en-us)": 300
                }
            },
            {
                "count": 1000,
                "date": "2009-06-01",
                "end": "2009-06-01",
                "data": {
                    u"Ελληνικά (el)": 400,
                    u'Espa\xf1ol (de M\xe9xico) (es-mx)': 400,
                    u"English (US) (en-us)": 300
                }
            },
        ])

    def test_usage_by_locale_csv(self):
        response = self.get_view_response(
            'stats.locales_series', group='day', format='csv')
        assert response.status_code == 200
        self.csv_eq(response,
            u"""date,count,English (US) (en-us),Espa\xf1ol (de M\xe9xico) (es-mx),Ελληνικά (el)
               2009-06-02,1500,300,400,400
               2009-06-01,1000,300,400,400""")  # noqa

    def test_usage_by_os_json(self):
        response = self.get_view_response(
            'stats.os_series', group='day', format='json')
        assert response.status_code == 200
        self.assertListEqual(json.loads(force_text(response.content)), [
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
        response = self.get_view_response(
            'stats.os_series', head=True, group='day', format='csv')
        assert response.status_code == 200

    def test_usage_by_version_json(self):
        response = self.get_view_response(
            'stats.versions_series', group='day', format='json')
        assert response.status_code == 200
        self.assertListEqual(json.loads(force_text(response.content)), [
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
        response = self.get_view_response(
            'stats.versions_series', group='day', format='csv')
        assert response.status_code == 200
        self.csv_eq(response, """date,count,1.0,2.0
                                 2009-06-02,1500,550,950
                                 2009-06-01,1000,200,800""")

    def test_usage_by_status_json(self):
        response = self.get_view_response(
            'stats.statuses_series', group='day', format='json')
        assert response.status_code == 200
        self.assertListEqual(json.loads(force_text(response.content)), [
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
        response = self.get_view_response(
            'stats.statuses_series', group='day', format='csv')
        assert response.status_code == 200
        self.csv_eq(response, """date,count,userDisabled,userEnabled
                                 2009-06-02,1500,130,1370
                                 2009-06-01,1000,50,950""")

    def test_overview(self):
        response = self.get_view_response(
            'stats.overview_series', group='day', format='json')
        assert response.status_code == 200
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
                self.assertDictEqual(next_actual['data'],
                                     {'downloads': 0, 'updates': 0})
                next_actual = next(actual)

    def test_downloads_json(self):
        response = self.get_view_response(
            'stats.downloads_series', group='day', format='json')
        assert response.status_code == 200
        self.assertListEqual(json.loads(force_text(response.content)), [
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
        response = self.get_view_response(
            'stats.downloads_series', group='day', format='csv')
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

    def test_downloads_sources_json(self):
        response = self.get_view_response(
            'stats.sources_series', group='day', format='json')
        assert response.status_code == 200
        self.assertListEqual(json.loads(force_text(response.content)), [
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
        response = self.get_view_response(
            'stats.sources_series', group='day', format='csv')
        assert response.status_code == 200
        self.csv_eq(response, """date,count,api,search
                                 2009-09-03,10,2,3
                                 2009-08-03,10,2,3
                                 2009-07-03,10,2,3
                                 2009-06-28,10,2,3
                                 2009-06-20,10,2,3
                                 2009-06-12,10,2,3
                                 2009-06-07,10,2,3
                                 2009-06-01,10,2,3""")


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


class TestStatsBeta(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.addon = addon_factory(users=[self.user])
        self.client.login(email=self.user.email)

    def test_stats_overview_page(self):
        url = reverse('stats.overview.beta', args=[self.addon.slug])

        response = self.client.get(url)

        assert b'You are viewing a beta feature.' in response.content
        assert response.context['beta']

    def test_beta_series_urls(self):
        url = reverse(
            'stats.overview_series.beta',
            args=[self.addon.slug, 'day', '20200101', '20200105', 'json']
        )

        match = resolve(url)

        assert match.kwargs['beta']
