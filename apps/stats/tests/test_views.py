# -*- coding: utf-8 -*-
import csv
import json

from nose.tools import eq_

import amo.tests
from amo.urlresolvers import reverse
from stats import views, tasks
from stats.models import DownloadCount, UpdateCount


class StatsTest(object):
    fixtures = ['stats/test_views.json', 'stats/test_models.json']

    def setUp(self):
        """Setup some reasonable testing defaults."""
        super(StatsTest, self).setUp()
        # default url_args to an addon and range with data
        self.url_args = {'start': '20090601', 'end': '20090930', 'addon_id': 4}
        # most tests don't care about permissions
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
        view_args.update(kwargs)
        url = reverse(view, kwargs=view_args)
        return self.client.get(url, follow=True)

    def views_gen(self, **kwargs):
        # common set of views
        for series in views.SERIES:
            for group in views.SERIES_GROUPS:
                view = 'stats.%s_series' % series
                args = kwargs.copy()
                args['group'] = group
                yield (view, args)

        # special case views
        yield ('stats.contributions_detail', kwargs)

    def public_views_gen(self, **kwargs):
        # all views are potentially public, except for contributions
        for view, args in self.views_gen(**kwargs):
            if view.find('stats.contributions') != 0:
                yield (view, args)

    def private_views_gen(self, **kwargs):
        # only contributions views are always private
        for view, args in self.views_gen(**kwargs):
            if view.find('stats.contributions') == 0:
                yield (view, args)


class TestSeriesBase(StatsTest, amo.tests.TestCase):
    pass


class TestSeriesSecurity(TestSeriesBase):
    """Tests to make sure all restricted data remains restricted."""

    def test_private_addon(self):
        """Ensure 403 for all series of an addon with private stats."""
        # First as a logged in user with no special permissions
        self.login_as_visitor()
        for view, kwargs in self.views_gen(format='json'):
            response = self.get_view_response(view, **kwargs)
            eq_(response.status_code, 403,
                'unexpected http status for %s' % view)

        # Again as an unauthenticated user
        self.client.logout()
        for view, kwargs in self.views_gen(format='json'):
            response = self.get_view_response(view, **kwargs)
            eq_(response.status_code, 403,
                'unexpected http status for %s' % view)

    def test_public_addon(self):
        """Ensure 403 for sensitive series of an addon with public stats."""
        # First as a logged in user with no special permissions
        self.login_as_visitor()
        for view, kwargs in self.private_views_gen(addon_id=5, format='json'):
            response = self.get_view_response(view, **kwargs)
            eq_(response.status_code, 403,
                'unexpected http status for %s' % view)

        # Again as an unauthenticated user
        self.client.logout()
        for view, kwargs in self.private_views_gen(addon_id=5, format='json'):
            response = self.get_view_response(view, **kwargs)
            eq_(response.status_code, 403,
                'unexpected http status for %s' % view)


class _TestCSVs(TestSeriesBase):
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
        response = self.get_view_response('stats.usage_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
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

    def test_contributions_detail(self):
        response = self.get_view_response('stats.contributions_detail',
                                          format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[self.first_row]  # the first row of data after the header
        eq_(len(row), 6, 'unexpected row length')
        date, amount, requested, name, email, comment = row
        eq_(date, '2009-06-02', 'unexpected date string: %s' % date)
        eq_(amount, '1.99', 'unexpected amount: %s' % amount)
        eq_(requested, '4.99', 'unexpected requested: %s' % requested)
        eq_(name, 'First Last', 'unexpected contributor: %s' % name)
        eq_(email, 'nobody@mozilla.com', 'unexpected email: %s' % email)
        eq_(comment, 'thanks!', 'unexpected comment: %s' % comment)

    def test_for_tests(self):
        """Test to make sure we didn't miss testing a known series view."""
        for view, kwargs in self.views_gen(format='csv'):
            testname = 'test_%s' % view[6:]  # everything after 'stats.'
            assert hasattr(self, testname), "no test for '%s'" % view

    def test_cache(self):
        """Test that the csv or json is sending a cache header of 7 days."""
        response = self.get_view_response('stats.contributions_detail',
                                          format='csv')
        eq_(response["cache-control"], 'max-age=604800')

        response = self.get_view_response('stats.contributions_detail',
                                          format='json')
        eq_(response["cache-control"], 'max-age=604800')

    def test_no_cache(self):
        """Test that the csv or json is not caching, due to lack of data."""
        self.url_args = {'start': '20200101', 'end': '20200130', 'addon_id': 4}
        response = self.get_view_response('stats.versions_series',
                                          group='day', format='csv')
        eq_(response["cache-control"], 'max-age=0')

        self.url_args = {'start': '20200101', 'end': '20200130', 'addon_id': 4}
        response = self.get_view_response('stats.versions_series',
                                          group='day', format='json')
        eq_(response["cache-control"], 'max-age=0')

    def test_usage_series_no_data(self):
        self.url_args = {'start': '20010101', 'end': '20010130', 'addon_id': 4}
        response = self.get_view_response('stats.versions_series',
                                          group='day', format='csv')

        eq_(response.status_code, 200)
        rows = list(csv.reader(response.content.split('\n')))
        eq_(len(rows), 6)
        eq_(rows[4], [])  # No fields
        eq_(rows[self.first_row], [])  # There is no data


class TestCacheControl(TestSeriesBase):
    """Tests we set cache control headers"""

    def _test_cache_control(self):
        response = self.get_view_response('stats.downloads_series',
                                          group='month', format='json')
        assert response.get('cache-control', '').startswith('max-age='), (
            'Bad or no cache-control: %r' % response.get('cache-control', ''))


class TestResponses(StatsTest, amo.tests.ESTestCase):
    es = True

    def setUp(self):
        super(TestResponses, self).setUp()
        self.index()

    def csv_eq(self, response, expected):
        # Drop the first 4 lines, which contain the header comment.
        content = response.content.splitlines()[4:]
        # Strip any extra spaces from the expected content.
        expected = [line.strip() for line in expected.splitlines()]
        self.assertListEqual(content, expected)

    def index(self):
        updates = UpdateCount.objects.values_list('id', flat=True)
        tasks.index_update_counts(list(updates))
        downloads = DownloadCount.objects.values_list('id', flat=True)
        tasks.index_download_counts(list(downloads))
        self.refresh('update_counts')

    def test_usage_json(self):
        r = self.get_view_response('stats.usage_series', group='day',
                                   format='json')
        eq_(r.status_code, 200)
        self.assertListEqual(json.loads(r.content), [
            {'count': 1500, 'date': '2009-06-02', 'end': '2009-06-02'},
            {'count': 1000, 'date': '2009-06-01', 'end': '2009-06-01'},
        ])

    def test_usage_csv(self):
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
        self.csv_eq(r, """date,count,{ec8030f7-c20a-464f-9b0e-13a3a9e97384}
                          2009-06-02,1500,{u'4.0': 1500}
                          2009-06-01,1000,{u'4.0': 1000}""")

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
        r = self.get_view_response('stats.os_series', group='day',
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
