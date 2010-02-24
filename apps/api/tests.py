import math

from django.conf import settings
from django.test.client import Client

from test_utils import TestCase
from nose.tools import eq_

import api
from addons.models import Addon
from search.tests import SphinxTestCase
from search.utils import stop_sphinx


def api_url(x, app='firefox', lang='en-US', version=1.2):
    return '/%s/%s/api/%.1f/%s' % (lang, app, version, x)

client = Client()
make_call = lambda *args, **kwargs: client.get(api_url(*args, **kwargs))


class APITest(TestCase):

    fixtures = ['base/addons']

    def test_redirection(self):
        """
        Test that /api/addon is redirected to /api/LATEST_API_VERSION/addon
        """
        response = self.client.get('/en-US/firefox/api/addon/12', follow=True)
        last_link = response.redirect_chain[-1]
        assert last_link[0].endswith('en-US/firefox/api/%.1f/addon/12' %
            api.CURRENT_VERSION)

    def test_forbidden_api(self):
        """
        APIs older than api.MIN_VERSION are deprecated, and we send a 403.
        We suggest people to use api.CURRENT_VERSION.
        """

        response = self.client.get('/en-US/firefox/api/0.9/addon/12')
        self.assertContains(response, 'The API version, %.1f, you are using '
            'is not valid. Please upgrade to the current version %.1f '
            'API.' % (0.9, api.CURRENT_VERSION), status_code=403)

    def test_addon_detail_missing(self):
        """
        Check missing addons.
        """
        response = self.client.get('/en-US/firefox/api/%.1f/addon/999' %
            api.CURRENT_VERSION)

        self.assertContains(response, 'Add-on not found!', status_code=404)

    def test_addon_detail_appid(self):
        """
        Make sure we serve an appid.  See
        https://bugzilla.mozilla.org/show_bug.cgi?id=546542.
        """
        response = self.client.get('/en-US/firefox/api/%.1f/addon/3615' %
                                   api.CURRENT_VERSION)
        self.assertContains(response,
                '<appID>{ec8030f7-c20a-464f-9b0e-13a3a9e97384}</appID>')

    def test_addon_detail_empty_eula(self):
        """
        Empty EULA should show up as '' not None.  See
        https://bugzilla.mozilla.org/show_bug.cgi?id=546542.
        """
        response = self.client.get('/en-US/firefox/api/%.1f/addon/4664' %
                                   api.CURRENT_VERSION)
        self.assertContains(response, '<eula></eula>')

    def test_addon_detail_rating(self):
        """
        We use the ceiling value of average rating for an addon.
        See https://bugzilla.mozilla.org/show_bug.cgi?id=546542.
        """
        a = Addon.objects.get(pk=4664)
        response = self.client.get('/en-US/firefox/api/%.1f/addon/4664' %
                                   api.CURRENT_VERSION)
        self.assertContains(response, '<rating>%d</rating>' %
                            int(math.ceil(a.bayesian_rating)))

    def test_addon_detail(self):
        """
        Test for expected strings in the XML.
        """
        response = self.client.get('/en-US/firefox/api/%.1f/addon/3615' % 1.2)

        self.assertContains(response, "<name>Delicious Bookmarks</name>")
        self.assertContains(response, """id="1">Extension</type>""")
        self.assertContains(response,
                """<guid>{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}</guid>""")
        self.assertContains(response, "<version>1.0.43</version>")
        self.assertContains(response, """<status id="4">Public</status>""")
        self.assertContains(response, "<author>carlsjr</author>")
        self.assertContains(response, "<summary>Best Addon Evar</summary>")
        self.assertContains(response,
                "<description>Delicious blah blah blah</description>")

        icon_url = settings.ADDON_ICON_URL % (3615, 1256144332)
        self.assertContains(response, icon_url + '</icon>')
        self.assertContains(response, "<application>")
        self.assertContains(response, "<name>Firefox</name>")
        self.assertContains(response, "<application_id>1</application_id>")
        self.assertContains(response, "<min_version>1</min_version>")
        self.assertContains(response, "<max_version>2</max_version>")
        self.assertContains(response, "<os>ALL</os>")
        self.assertContains(response, "<eula></eula>")
        self.assertContains(response, "/img/no-preview.png</thumbnail>")
        self.assertContains(response, "<rating>4</rating>")
        self.assertContains(response,
                "/en-US/firefox/addon/3615/?src=api</learnmore>")
        self.assertContains(response,
                """hash="sha256:5b5aaf7b38e332cc95d92ba759c01"""
                "c3076b53a840f6c16e01dc272eefcb29566")

    def test_15_addon_detail(self):
        """
        For an api>1.5 we need to verify we have:
        # Contributions information, including a link to contribute, suggested
          amount, and Meet the Developers page
        # Number of user reviews and link to view them
        # Total downloads, weekly downloads, and latest daily user counts
        # Add-on creation date
        # Link to the developer's profile
        # File size
        """
        needles = (
                "<contribution_data>",
                "/en-US/firefox/addons/contribute/4664?src=api</link>",
                "<suggested_amount>0.99</suggested_amount>",
                "/en-US/firefox/addon/4664/developers?src=api"
                "</meet_developers>",
                """<reviews num="101">""",
                "/en-US/firefox/addon/4664/reviews?src=api</reviews>",
                "<total_downloads>867952</total_downloads>",
                "<weekly_downloads>23646</weekly_downloads>",
                "<daily_users>44693</daily_users>",
                "<created>2007-03-17 05:23:55</created>",
                "/en-US/firefox/user/2519/?src=api</link>",
                'size="90"',
                'units="kb"',
                )

        response = make_call('addon/4664', version=1.5)

        for needle in needles:
            self.assertContains(response, needle)

    def test_sphinx_off(self):
        """
        This tests that if sphinx is turned off that you will get an error.
        """
        stop_sphinx()
        response = self.client.get("/en-US/firefox/api/1.2/search/foo")
        self.assertContains(response, "Could not connect to Sphinx search.",
                            status_code=503)

    test_sphinx_off.sphinx = True


class ListTest(TestCase):
    """
    Tests the list view with various urls.
    """
    fixtures = ['base/featured']

    def test_defaults(self):
        """
        This tests the default settings for /list.
        i.e. We should get 3 items by default.
        """
        request = make_call('list')
        self.assertContains(request, '<addon>', 3)

    def test_randomness(self):
        """
        This tests that we're sufficiently random when recommending addons.

        We can test for this by querying /list/recommended a number of times
        until we get two request.contents that do not match.
        """
        request = make_call('list/recommended')

        all_identical = True

        for i in range(99):
            current_request = make_call('list/recommended')
            if current_request.content != request.content:
                all_identical = False

        assert not all_identical, (
                "All 100 requests returned the exact same response.")

    def test_type_filter(self):
        """
        This tests that list filtering works.
        E.g. /list/recommended/theme gets only shows themes
        """
        request = make_call('list/recommended/9/1')

        self.assertContains(request, """<type id="9">Persona</type>""", 1)

    def test_limits(self):
        """
        Assert /list/recommended/all/1 gets one item only.
        """
        request = make_call('list/recommended/all/1')
        self.assertContains(request, "<addon>", 1)

    def test_version_filter(self):
        """
        Assert that filtering by application version works.

        E.g.
        /list/new/all/1/mac/4.0 gives us nothing
        """
        request = make_call('list/new/all/1/all/4.0')
        self.assertNotContains(request, "<addon>")

    def test_backfill(self):
        """
        The /list/recommended should first populate itself with addons in its
        locale.  If it doesn't reach the desired limit, it should backfill from
        the general population of featured addons.
        """
        request = make_call('list', lang='fr')
        self.assertContains(request, "<addon>", 3)

        request = make_call('list', lang='he')
        self.assertContains(request, "<addon>", 3)

    def test_browser_featured_list(self):
        """
        This is a query that a browser would use to show it's featured list.

        c.f.: https://bugzilla.mozilla.org/show_bug.cgi?id=548114
        """
        request = make_call('list/featured/all/10/Linux/3.7a2pre',
                            version=1.3)
        self.assertContains(request, "<addons>")


class SearchTest(SphinxTestCase):
    no_results = """<searchresults total_results="0">"""

    def test_zero_results(self):
        """
        Tests that the search API correctly gives us zero results found.
        """
        # The following URLs should yield zero results.
        zeros = (
                 "/en-US/sunbird/api/1.2/search/yslow",
                 "yslow category:alerts",
                 "jsonview version:1.0",
                 "firebug type:dictionary",
                 "grapple platform:linux",
                 "firebug/3",
                 "grapple/all/10/Linux",
                 "jsonview/all/10/Darwin/1.0",)

        for url in zeros:
            if not url.startswith('/'):
                url = '/en-US/firefox/api/1.2/search/' + url

            response = self.client.get(url)
            self.assertContains(response, self.no_results, msg_prefix=url)

    def test_search_for_specifics(self):
        """
        Tests that the search API correctly returns specific results.
        """
        expect = {
                  'yslow': 'YSlow',
                  'yslow category:web': 'YSlow',
                  'jsonview version:3.5': 'JSONView',
                  'firebug type:extension': 'Firebug',
                  'grapple platform:mac': 'GrApple',
                  'firebug/1': 'Firebug',
                  'grapple/all/10/Darwin': 'GrApple',
                  'jsonview/all/10/Darwin/3.5': 'JSONView',
                  '/en-US/mobile/api/1.2/search/twitter/all/10/Linux/1.0b4':
                  'TwitterBar',
                  }

        for url, text in expect.iteritems():
            if not url.startswith('/'):
                url = '/en-US/firefox/api/1.2/search/' + url

            response = self.client.get(url)
            self.assertContains(response, text, msg_prefix=url)

    def test_search_limits(self):
        """
        Test that we limit our results correctly.
        """
        response = self.client.get(
                "/en-US/firefox/api/1.2/search/firebug/all/1")
        eq_(response.content.count("<addon>"), 1)

    def test_total_results(self):
        """
        The search for firebug should result in 2 total addons, even though
        we limit (and therefore show) only 1.
        """
        response = self.client.get(
                "/en-US/firefox/api/1.2/search/firebug/all/1")
        self.assertContains(response, """<searchresults total_results="2">""")

    def test_sandbox_search(self):
        """
        For API < 1.5 and where ?hide_sandbox=1 we should show no addons when
        searching for MozEx (a sandboxed addon).  However, for API version 1.5
        we should find it.
        """
        # API < 1.5
        response = make_call('search/mozex', version=1.4)
        self.assertContains(response, self.no_results,
                            msg_prefix=response.request['PATH_INFO'])

        # API = 1.5, hide_sandbox
        response = self.client.get(
                api_url('search/mozex', version=1.5) + '?hide_sandbox=1')
        self.assertContains(response, self.no_results,
                            msg_prefix=response.request['PATH_INFO'])

        # API = 1.5
        response = make_call('search/mozex', version=1.5)
        self.assertContains(response, """<status id="1">""")

# /class SearchTest
