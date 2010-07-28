import csv

import test_utils
from nose.tools import eq_

from amo.urlresolvers import reverse
from stats import views


class TestSeriesBase(test_utils.TestCase):
    fixtures = ['stats/test_views.json', 'stats/test_models.json']

    def setUp(self):
        """Setup some reasonable testing defaults."""
        super(TestSeriesBase, self).setUp()
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


class TestCSVs(TestSeriesBase):
    """Tests for CSV output of all known series views."""

    def test_downloads_series(self):
        response = self.get_view_response('stats.downloads_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[9]  # the first row of data after the header
        eq_(len(row), 2, 'unexpected row length')
        date, count = row
        eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
        eq_(count, '50', 'unexpected count value: %s' % count)

    def test_usage_series(self):
        response = self.get_view_response('stats.usage_series',
                                          group='month', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[9]  # the first row of data after the header
        eq_(len(row), 2, 'unexpected row length')
        date, ave = row
        eq_(date, '2009-06-01', 'unexpected date string: %s' % date)
        eq_(ave, '83', 'unexpected ADU average: %s' % ave)

    def test_contributions_series(self):
        response = self.get_view_response('stats.contributions_series',
                                          group='day', format='csv')

        eq_(response.status_code, 200, 'unexpected http status')
        rows = list(csv.reader(response.content.split('\n')))
        row = rows[9]  # the first row of data after the header
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
        row = rows[9]  # the first row of data after the header
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
        row = rows[9]  # the first row of data after the header
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
        row = rows[9]  # the first row of data after the header
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
        row = rows[9]  # the first row of data after the header
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
        row = rows[9]  # the first row of data after the header
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
        row = rows[9]  # the first row of data after the header
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
        row = rows[9]  # the first row of data after the header
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

    def test_usage_series_no_data(self):
        self.url_args = {'start': '20010101', 'end': '20010130', 'addon_id': 4}
        response = self.get_view_response('stats.versions_series',
                                          group='day', format='csv')

        eq_(response.status_code, 200)
        rows = list(csv.reader(response.content.split('\n')))
        eq_(len(rows), 10)
        eq_(rows[8], ['# Fields: []']) # Header is present
        eq_(rows[9], []) # There is no data


class TestCacheControl(TestSeriesBase):
    """Tests we set cache control headers"""

    def test_cache_control(self):
        response = self.get_view_response('stats.downloads_series',
                                          group='month', format='csv')
        assert response.get('cache-control', '').startswith('max-age='), (
            'Bad or no cache-control: %r' % response.get('cache-control', ''))
