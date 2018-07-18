# -*- coding: utf-8 -*-
import json

from textwrap import dedent

from django.conf import settings
from django.test.client import Client
from django.utils import translation

import jinja2
import pytest

from mock import patch
from pyquery import PyQuery as pq

from olympia import amo, legacy_api
from olympia.addons.models import (
    Addon,
    AppSupport,
    CompatOverride,
    CompatOverrideRange,
    Persona,
    Preview,
)
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.tests import ESTestCase, TestCase, addon_factory
from olympia.amo.urlresolvers import reverse
from olympia.amo.views import handler500
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import (
    Collection,
    CollectionAddon,
    FeaturedCollection,
)
from olympia.files.models import File
from olympia.files.tests.test_models import UploadTest
from olympia.legacy_api.utils import addon_to_dict
from olympia.legacy_api.views import addon_filter
from olympia.tags.models import AddonTag, Tag


pytestmark = pytest.mark.django_db


def api_url(x, app='firefox', lang='en-US', version=1.2):
    return '/%s/%s/api/%s/%s' % (lang, app, version, x)


client = Client()


def make_call(*args, **kwargs):
    return client.get(api_url(*args, **kwargs))


def test_json_not_implemented():
    assert legacy_api.views.APIView().render_json({}) == (
        '{"msg": "Not implemented yet."}'
    )


class UtilsTest(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(UtilsTest, self).setUp()
        self.a = Addon.objects.get(pk=3615)

    def test_dict(self):
        """Verify that we're getting dict."""
        d = addon_to_dict(self.a)
        assert d, 'Add-on dictionary not found'
        assert d['learnmore'].endswith(
            '/addon/a3615/?src=api'
        ), 'Add-on details URL does not end with "?src=api"'

    def test_dict_disco(self):
        """Check for correct add-on detail URL for discovery pane."""
        d = addon_to_dict(self.a, disco=True, src='discovery-personalrec')
        u = '%s%s?src=discovery-personalrec' % (
            settings.SERVICES_URL,
            reverse('discovery.addons.detail', args=['a3615']),
        )
        assert d['learnmore'] == u

    def test_sanitize(self):
        """Check that tags are stripped for summary and description."""
        self.a.summary = self.a.description = 'i <3 <a href="">amo</a>!'
        self.a.save()
        d = addon_to_dict(self.a)
        assert d['summary'] == 'i &lt;3 amo!'
        assert d['description'] == 'i &lt;3 amo!'

    def test_simple_contributions(self):
        self.a.update(contributions='https://paypal.me/blah')
        d = addon_to_dict(self.a)
        assert d['contribution']['meet_developers'] == self.a.contributions
        assert 'link' not in d['contribution']


class No500ErrorsTest(TestCase):
    """
    A series of unfortunate urls that have caused 500 errors in the past.
    """

    def test_search_bad_type(self):
        """
        For search/:term/:addon_type <-- addon_type should be an integer.
        """
        response = make_call('/search/foo/theme')
        # We'll likely get a 503 since Sphinx is off and that
        # is good.  We just don't want 500 errors.
        assert response.status_code != 500, "We received a 500 error, wtf?"

    def test_list_bad_type(self):
        """
        For list/new/:addon_type <-- addon_type should be an integer.
        """
        response = make_call('/list/new/extension')
        assert response.status_code != 500, "We received a 500 error, wtf?"

    def test_utf_redirect(self):
        """Test that urls with unicode redirect properly."""
        response = make_call(u'search/ツールバー', version=1.5)
        assert response.status_code != 500, "Unicode failed to redirect."

    def test_manual_utf_search(self):
        """If someone searches for non doubly encoded data using an old API we
        should not try to decode it."""
        response = make_call(u'search/für', version=1.2)
        assert response.status_code != 500, "ZOMG Unicode fails."

    def test_broken_guid(self):
        response = make_call(u'search/guid:+972"e4c6-}', version=1.5)
        assert response.status_code != 500, "Failed to cope with guid"


class ControlCharacterTest(TestCase):
    """This test is to assure we aren't showing control characters."""

    fixtures = ('base/addon_3615',)

    def test(self):
        a = Addon.objects.get(pk=3615)
        char = chr(12)
        a.name = "I %sove You" % char
        a.save()
        response = make_call('addon/3615')
        self.assertNotContains(response, char)


class StripHTMLTest(TestCase):
    fixtures = ('base/addon_3615',)

    def test(self):
        """For API < 1.5 we remove HTML."""
        a = Addon.objects.get(pk=3615)
        a.eula = '<i>free</i> stock tips'
        a.summary = '<i>xxx video</i>s'
        a.description = 'FFFF<b>UUUU</b>'
        a.save()

        r = make_call('addon/3615', version=1.5)
        doc = pq(r.content)
        assert doc('eula').html() == '<i>free</i> stock tips'
        assert doc('summary').html() == '&lt;i&gt;xxx video&lt;/i&gt;s'
        assert doc('description').html() == 'FFFF<b>UUUU</b>'

        r = make_call('addon/3615')
        doc = pq(r.content)
        assert doc('eula').html() == 'free stock tips'
        assert doc('summary').html() == 'xxx videos'
        assert doc('description').html() == 'FFFFUUUU'


class APITest(TestCase):
    fixtures = [
        'base/addon_3615',
        'base/addon_4664_twitterbar',
        'base/addon_5299_gcal',
    ]

    def test_api_caching(self):
        response = self.client.get('/en-US/firefox/api/1.5/addon/3615')
        assert response.status_code == 200
        self.assertContains(response, '<author id="')

        # Make sure we don't cache the 1.5 response for 1.2.
        response = self.client.get('/en-US/firefox/api/1.2/addon/3615')
        assert response.status_code == 200
        self.assertContains(response, '<author>')

    def test_redirection(self):
        """
        Test that /api/addon is redirected to /api/LATEST_API_VERSION/addon
        """
        response = self.client.get('/en-US/firefox/api/addon/12', follow=True)
        last_link = response.redirect_chain[-1]
        assert last_link[0].endswith(
            'en-US/firefox/api/%.1f/addon/12' % legacy_api.CURRENT_VERSION
        )

    def test_forbidden_api(self):
        """
        APIs older than api.MIN_VERSION are deprecated, and we send a 403.
        We suggest people to use api.CURRENT_VERSION.
        """

        response = self.client.get('/en-US/firefox/api/0.9/addon/12')
        self.assertContains(
            response,
            'The API version, %.1f, you are using is not valid. Please upgrade'
            ' to the current version %.1f API.'
            % (0.9, legacy_api.CURRENT_VERSION),
            status_code=403,
        )

    def test_addon_detail_missing(self):
        """
        Check missing addons.
        """
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/999' % legacy_api.CURRENT_VERSION
        )

        self.assertContains(response, 'Add-on not found!', status_code=404)

    def test_handler404(self):
        """
        Check separate handler404 response for API.
        """
        response = self.client.get('/en-US/firefox/api/nonsense')
        doc = pq(response.content)
        assert response.status_code == 404
        d = doc('error')
        self.assertTemplateUsed(response, 'legacy_api/message.xml')
        assert d.length == 1
        assert d.text() == 'Not Found'

    def test_handler500(self):
        """
        Check separate handler500 response for API.
        """
        req = self.client.get('/en-US/firefox/api/').context['request']
        try:
            raise NameError('an error')
        except NameError:
            r = handler500(req)
            assert r.status_code == 500
            doc = pq(r.content)
            d = doc('error')
            assert d.length == 1
            assert d.text() == 'Server Error'

    def test_addon_detail_appid(self):
        """
        Make sure we serve an appid.  See
        https://bugzilla.mozilla.org/show_bug.cgi?id=546542.
        """
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/3615' % legacy_api.CURRENT_VERSION
        )
        self.assertContains(
            response, '<appID>{ec8030f7-c20a-464f-9b0e-13a3a9e97384}</appID>'
        )

    def test_addon_detail_empty_eula(self):
        """
        Empty EULA should show up as '' not None.  See
        https://bugzilla.mozilla.org/show_bug.cgi?id=546542.
        """
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/4664' % legacy_api.CURRENT_VERSION
        )
        self.assertContains(response, '<eula></eula>')

    def test_addon_detail_rating(self):
        a = Addon.objects.get(pk=4664)
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/4664' % legacy_api.CURRENT_VERSION
        )
        self.assertContains(
            response, '<rating>%d</rating>' % int(round(a.average_rating))
        )

    def test_addon_detail_xml(self):
        response = self.client.get('/en-US/firefox/api/%.1f/addon/3615' % 1.2)

        self.assertContains(response, "<name>Delicious Bookmarks</name>")
        self.assertContains(response, """id="1">Extension</type>""")
        self.assertContains(
            response, "<guid>{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}</guid>"
        )
        self.assertContains(response, "<version>2.1.072</version>")
        self.assertContains(response, '<status id="4">Approved</status>')
        self.assertContains(
            response, u'<author>55021 \u0627\u0644\u062a\u0637\u0628</author>'
        )
        self.assertContains(response, "<summary>Delicious Bookmarks is the")
        self.assertContains(response, "<description>This extension integrates")

        icon_url = "%s3/3615-32.png" % jinja_helpers.user_media_url(
            'addon_icons'
        )
        self.assertContains(response, '<icon size="32">' + icon_url)
        self.assertContains(response, "<application>")
        self.assertContains(response, "<name>Firefox</name>")
        self.assertContains(response, "<application_id>1</application_id>")
        self.assertContains(response, "<min_version>2.0</min_version>")
        self.assertContains(response, "<max_version>4.0</max_version>")
        self.assertContains(response, "<os>ALL</os>")
        self.assertContains(response, "<eula>")
        self.assertContains(response, "/icons/no-preview.png</thumbnail>")
        self.assertContains(response, "<rating>3</rating>")
        self.assertContains(
            response, "/en-US/firefox/addon/a3615/?src=api</learnmore>"
        )
        self.assertContains(
            response,
            'hash="sha256:3808b13ef8341378b9c8305ca648200954ee7dcd8dce09fef55f'
            '2673458bc31f"',
        )

    def test_addon_detail_json(self):
        addon = Addon.objects.get(id=3615)
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/3615?format=json' % 1.2
        )
        data = json.loads(response.content)
        assert data['name'] == unicode(addon.name)
        assert data['type'] == 'extension'
        assert data['guid'] == addon.guid
        assert data['version'] == '2.1.072'
        assert data['status'] == 'public'
        assert data['authors'] == (
            [
                {
                    'id': 55021,
                    'name': u'55021 \u0627\u0644\u062a\u0637\u0628',
                    'link': jinja_helpers.absolutify(
                        u'/en-US/firefox/user/55021/?src=api'
                    ),
                }
            ]
        )
        assert data['summary'] == unicode(addon.summary)
        assert data['description'] == (
            'This extension integrates your browser with Delicious '
            '(http://delicious.com), the leading social bookmarking '
            'service on the Web.'
        )
        assert data['icon'] == (
            '%s3/3615-32.png?modified=1275037317'
            % jinja_helpers.user_media_url('addon_icons')
        )
        assert data['compatible_apps'] == (
            [{'Firefox': {'max': '4.0', 'min': '2.0'}}]
        )
        assert data['eula'] == unicode(addon.eula)
        assert data['learnmore'] == (
            jinja_helpers.absolutify('/en-US/firefox/addon/a3615/?src=api')
        )
        assert 'theme' not in data

    def test_theme_detail(self):
        addon = Addon.objects.get(id=3615)
        addon.update(type=amo.ADDON_PERSONA)
        Persona.objects.create(persona_id=3, addon=addon)
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/3615?format=json' % 1.2
        )
        data = json.loads(response.content)
        assert data['id'] == 3615
        # `id` should be `addon_id`, not `persona_id`
        assert data['theme']['id'] == '3615'

    def test_addon_license(self):
        """Test for license information in response."""
        addon = Addon.objects.get(id=3615)
        license = addon.current_version.license
        license.name = 'My License'
        license.url = 'someurl'
        license.save()
        api_url = (
            '/en-US/firefox/api/%.1f/addon/3615' % legacy_api.CURRENT_VERSION
        )
        response = self.client.get(api_url)
        doc = pq(response.content)
        assert doc('license').length == 1
        assert doc('license name').length == 1
        assert doc('license url').length == 1
        assert doc('license name').text() == unicode(license.name)
        assert doc('license url').text() == jinja_helpers.absolutify(
            license.url
        )

        license.url = ''
        license.save()
        addon.save()
        response = self.client.get(api_url)
        doc = pq(response.content)
        license_url = addon.current_version.license_url()
        assert doc('license url').text() == jinja_helpers.absolutify(
            license_url
        )

        license.delete()
        response = self.client.get(api_url)
        doc = pq(response.content)
        assert doc('license').length == 0

    def test_whitespace(self):
        """Whitespace is apparently evil for learnmore and install."""
        r = make_call('addon/3615')
        doc = pq(r.content)
        learnmore = doc('learnmore')[0].text
        assert learnmore == learnmore.strip()

        install = doc('install')[0].text
        assert install == install.strip()

    def test_absolute_install_url(self):
        response = make_call('addon/4664', version=1.2)
        doc = pq(response.content)
        url = doc('install').text()
        expected = '%s/firefox/downloads/file' % settings.SITE_URL
        assert url.startswith(expected), url

    def test_15_addon_detail(self):
        """
        For an api>1.5 we need to verify we have:
        # Contributions information, which is now just the contributions url,
        # sent as the link to Meet the Developers
        # Number of user reviews and link to view them
        # Total downloads, weekly downloads, and latest daily user counts
        # Add-on creation date
        # Link to the developer's profile
        # File size
        """

        def urlparams(x, *args, **kwargs):
            return jinja2.escape(jinja_helpers.urlparams(x, *args, **kwargs))

        needles = (
            '<addon id="4664">',
            '<contribution_data>',
            '<meet_developers>',
            'https://patreon.com/blah',
            '</meet_developers>',
            '<reviews num="131">',
            '%s/en-US/firefox/addon/4664/reviews/?src=api' % settings.SITE_URL,
            '<total_downloads>1352192</total_downloads>',
            '<weekly_downloads>13849</weekly_downloads>',
            '<daily_users>67075</daily_users>',
            '<author id="2519"',
            '%s/en-US/firefox/user/cfinke/?src=api</link>' % settings.SITE_URL,
            '<previews>',
            'preview position="0">',
            '<caption>TwitterBar places an icon in the address bar.</caption>',
            'full type="image/png">',
            '<thumbnail type="image/png">',
            (
                '<developer_comments>Embrace hug love hug meow meow'
                '</developer_comments>'
            ),
            'size="100352"',
            (
                '<homepage>http://www.chrisfinke.com/addons/twitterbar/'
                '</homepage>'
            ),
            '<support>http://www.chrisfinke.com/addons/twitterbar/</support>',
        )

        # For urls with several parameters, we need to use self.assertUrlEqual,
        # as the parameters could be in random order. Dicts aren't ordered!
        # We need to subtract 7 hours from the modified time since May 3, 2008
        # is during daylight savings time.
        url_needles = {
            "full": urlparams(
                '{previews}full/20/20397.png'.format(
                    previews=jinja_helpers.user_media_url('previews')
                ),
                src='api',
                modified=1209834208 - 7 * 3600,
            ),
            "thumbnail": urlparams(
                '{previews}thumbs/20/20397.png'.format(
                    previews=jinja_helpers.user_media_url('previews')
                ),
                src='api',
                modified=1209834208 - 7 * 3600,
            ),
        }

        response = make_call('addon/4664', version=1.5)
        doc = pq(response.content)

        tags = {
            'created': ({'epoch': '1174109035'}, '2007-03-17T05:23:55Z'),
            'last_updated': ({'epoch': '1272301783'}, '2010-04-26T17:09:43Z'),
        }

        for tag, v in tags.items():
            attrs, text = v
            el = doc(tag)
            for attr, val in attrs.items():
                assert el.attr(attr) == val

            assert el.text() == text

        for needle in needles:
            self.assertContains(response, needle)

        for tag, needle in url_needles.iteritems():
            url = doc(tag).text()
            self.assertUrlEqual(url, needle)

    def test_slug(self):
        Addon.objects.get(pk=5299).update(type=amo.ADDON_EXTENSION)
        self.assertContains(
            make_call('addon/5299', version=1.5),
            '<slug>%s</slug>' % Addon.objects.get(pk=5299).slug,
        )

    def test_is_featured(self):
        self.assertContains(
            make_call('addon/5299', version=1.5), '<featured>0</featured>'
        )
        c = CollectionAddon.objects.create(
            addon=Addon.objects.get(id=5299),
            collection=Collection.objects.create(),
        )
        FeaturedCollection.objects.create(
            locale='ja', application=amo.FIREFOX.id, collection=c.collection
        )
        for lang, app, result in [
            ('ja', 'firefox', 1),
            ('en-US', 'firefox', 0),
            ('ja', 'seamonkey', 0),
        ]:
            self.assertContains(
                make_call('addon/5299', version=1.5, lang=lang, app=app),
                '<featured>%s</featured>' % result,
            )

    def test_default_icon(self):
        addon = Addon.objects.get(pk=5299)
        addon.update(icon_type='')
        self.assertContains(make_call('addon/5299'), '<icon size="32"></icon>')

    def test_thumbnail_size(self):
        addon = Addon.objects.get(pk=5299)
        preview = Preview.objects.create(addon=addon)
        preview.sizes = {'thumbnail': [200, 150]}
        preview.save()
        result = make_call('addon/5299', version=1.5)
        self.assertContains(result, '<full type="image/png">')
        self.assertContains(
            result, '<thumbnail type="image/png" width="200" height="150">'
        )

    def test_disabled_addon(self):
        Addon.objects.get(pk=3615).update(disabled_by_user=True)
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/3615' % legacy_api.CURRENT_VERSION
        )
        doc = pq(response.content)
        assert doc[0].tag == 'error'
        assert response.status_code == 404

    def test_addon_with_no_listed_versions(self):
        self.make_addon_unlisted(Addon.objects.get(pk=3615))
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/3615' % legacy_api.CURRENT_VERSION
        )
        doc = pq(response.content)
        assert doc[0].tag == 'error'
        assert response.status_code == 404

    def test_cross_origin(self):
        # Add-on details should allow cross-origin requests.
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/3615' % legacy_api.CURRENT_VERSION
        )

        assert response['Access-Control-Allow-Origin'] == '*'
        assert response['Access-Control-Allow-Methods'] == 'GET'

        # Even those that are not found.
        response = self.client.get(
            '/en-US/firefox/api/%.1f/addon/999' % legacy_api.CURRENT_VERSION
        )

        assert response['Access-Control-Allow-Origin'] == '*'
        assert response['Access-Control-Allow-Methods'] == 'GET'


class ListTest(TestCase):
    """Tests the list view with various urls."""

    fixtures = [
        'base/users',
        'base/addon_3615',
        'base/featured',
        'addons/featured',
        'bandwagon/featured_collections',
        'base/collections',
    ]

    def test_defaults(self):
        """
        This tests the default settings for /list.
        i.e. We should get 3 items by default.
        """
        response = make_call('list')
        self.assertContains(response, '<addon id', 3)

    def test_type_filter(self):
        """
        This tests that list filtering works.
        E.g. /list/recommended/theme gets only shows themes
        """
        response = make_call('list/recommended/9/1')
        self.assertContains(response, """<type id="9">Theme</type>""", 1)

    def test_persona_search_15(self):
        response = make_call('list/recommended/9/1', version=1.5)
        self.assertContains(response, """<type id="9">Theme</type>""", 1)

    def test_limits(self):
        """
        Assert /list/recommended/all/1 gets one item only.
        """
        response = make_call('list/recommended/all/1')
        self.assertContains(response, "<addon id", 1)

    def test_version_filter(self):
        """
        Assert that filtering by application version works.

        E.g.
        /list/new/all/1/mac/4.0 gives us nothing
        """
        response = make_call('list/new/1/1/all/4.0')
        self.assertNotContains(response, "<addon id")

    def test_backfill(self):
        """
        The /list/recommended should first populate itself with addons in its
        locale.  If it doesn't reach the desired limit, it should backfill from
        the general population of featured addons.
        """
        response = make_call('list', lang='fr')
        self.assertContains(response, "<addon id", 3)

        response = make_call('list', lang='he')

        self.assertContains(response, "<addon id", 3)

    def test_browser_featured_list(self):
        """
        This is a query that a browser would use to show it's featured list.

        c.f.: https://bugzilla.mozilla.org/show_bug.cgi?id=548114
        """
        response = make_call(
            'list/featured/all/10/Linux/3.7a2pre', version=1.3
        )
        self.assertContains(response, "<addons>")

    def test_average_daily_users(self):
        """Verify that average daily users returns data in order."""
        r = make_call('list/by_adu', version=1.5)
        doc = pq(r.content)
        vals = [int(a.text) for a in doc("average_daily_users")]
        sorted_vals = sorted(vals, reverse=True)
        assert vals == sorted_vals

    def test_adu_no_personas(self):
        """Verify that average daily users does not return Themes."""
        response = make_call('list/by_adu')
        self.assertNotContains(response, """<type id="9">Theme</type>""")

    def test_featured_no_personas(self):
        """Verify that featured does not return Themes."""
        response = make_call('list/featured')
        self.assertNotContains(response, """<type id="9">Theme</type>""")

    def test_json(self):
        """Verify that we get some json."""
        r = make_call('list/by_adu?format=json', version=1.5)
        assert json.loads(r.content)

    def test_unicode(self):
        make_call(u'list/featured/all/10/Linux/3.7a2prexec\xb6\u0153\xec\xb2')


class AddonFilterTest(TestCase):
    """Tests the addon_filter, including the various d2c cases."""

    fixtures = ['base/appversion']

    def setUp(self):
        super(AddonFilterTest, self).setUp()
        # Start with 2 compatible add-ons.
        self.addon1 = addon_factory(version_kw={'max_app_version': '5.0'})
        self.addon2 = addon_factory(version_kw={'max_app_version': '6.0'})
        self.addons = [self.addon1, self.addon2]

    def _defaults(self, **kwargs):
        # Default args for addon_filter.
        defaults = {
            'addons': self.addons,
            'addon_type': 'ALL',
            'limit': 0,
            'app': amo.FIREFOX,
            'platform': 'all',
            'version': '5.0',
            'compat_mode': 'strict',
            'shuffle': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_basic(self):
        addons = addon_filter(**self._defaults())
        assert addons == self.addons

    def test_limit(self):
        addons = addon_filter(**self._defaults(limit=1))
        assert addons == [self.addon1]

    def test_app_filter(self):
        self.addon1.update(type=amo.ADDON_DICT)
        addons = addon_filter(
            **self._defaults(addon_type=str(amo.ADDON_EXTENSION))
        )
        assert addons == [self.addon2]

    def test_platform_filter(self):
        file = self.addon1.current_version.files.all()[0]
        file.update(platform=amo.PLATFORM_WIN.id)
        # Transformers don't know 'bout my files.
        self.addons[0] = Addon.objects.get(pk=self.addons[0].pk)
        addons = addon_filter(
            **self._defaults(platform=amo.PLATFORM_LINUX.shortname)
        )
        assert addons == [self.addon2]

    def test_version_filter_strict(self):
        addons = addon_filter(**self._defaults(version='6.0'))
        assert addons == [self.addon2]

    def test_version_filter_ignore(self):
        addons = addon_filter(
            **self._defaults(version='6.0', compat_mode='ignore')
        )
        assert addons == self.addons

    def test_version_version_less_than_min(self):
        # Ensure we filter out addons with a higher min than our app.
        addon3 = addon_factory(
            version_kw={'min_app_version': '12.0', 'max_app_version': '14.0'}
        )
        addons = self.addons + [addon3]
        addons = addon_filter(
            **self._defaults(
                addons=addons, version='11.0', compat_mode='ignore'
            )
        )
        assert addons == self.addons

    def test_version_filter_normal_strict_opt_in(self):
        # Ensure we filter out strict opt-in addons in normal mode.
        addon3 = addon_factory(
            version_kw={'max_app_version': '7.0'},
            file_kw={'strict_compatibility': True},
        )
        addons = self.addons + [addon3]
        addons = addon_filter(
            **self._defaults(
                addons=addons, version='11.0', compat_mode='normal'
            )
        )
        assert addons == self.addons

    def test_version_filter_normal_binary_components(self):
        # Ensure we filter out strict opt-in addons in normal mode.
        addon3 = addon_factory(
            version_kw={'max_app_version': '7.0'},
            file_kw={'binary_components': True},
        )
        addons = self.addons + [addon3]
        addons = addon_filter(
            **self._defaults(
                addons=addons, version='11.0', compat_mode='normal'
            )
        )
        assert addons == self.addons

    def test_version_filter_normal_compat_override(self):
        # Ensure we filter out strict opt-in addons in normal mode.
        addon3 = addon_factory()
        addons = self.addons + [addon3]

        # Add override for this add-on.
        compat = CompatOverride.objects.create(guid='three', addon=addon3)
        CompatOverrideRange.objects.create(
            compat=compat,
            app=1,
            min_version=addon3.current_version.version,
            max_version='*',
        )

        addons = addon_filter(
            **self._defaults(
                addons=addons, version='11.0', compat_mode='normal'
            )
        )
        assert addons == self.addons

    def test_locale_preferencing(self):
        # Add-ons matching the current locale get prioritized.
        addon3 = addon_factory()
        addon3.description = {'de': 'Unst Unst'}
        addon3.save()

        addons = self.addons + [addon3]

        translation.activate('de')
        addons = addon_filter(**self._defaults(addons=addons))
        assert addons == [addon3] + self.addons
        translation.deactivate()


class SeamonkeyFeaturedTest(TestCase):
    fixtures = ['base/seamonkey']

    def test_seamonkey_wankery(self):
        """
        An add-on used to support seamonkey, but not in its current_version.
        This was making our filters crash.
        """
        response = make_call('/list/featured/all/10/all/1', app='seamonkey')
        assert response.context['addons'] == []


class TestGuidSearch(TestCase):
    fixtures = ('base/addon_6113', 'base/addon_3615')
    # These are the guids for addon 6113 and 3615.
    good = (
        'search/guid:{22870005-adef-4c9d-ae36-d0e1f2f27e5a},'
        '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
    )

    def setUp(self):
        super(TestGuidSearch, self).setUp()
        addon = Addon.objects.get(id=3615)
        c = CompatOverride.objects.create(guid=addon.guid)
        app = addon.compatible_apps.keys()[0]
        CompatOverrideRange.objects.create(compat=c, app=app.id)

    def test_success(self):
        r = make_call(self.good)
        dom = pq(r.content)
        assert set(['3615', '6113']) == (
            set([a.attrib['id'] for a in dom('addon')])
        )

        # Make sure the <addon_compatibility> blocks are there.
        assert ['3615'] == [a.attrib['id'] for a in dom('addon_compatibility')]

    @patch('waffle.switch_is_active', lambda x: True)
    def test_api_caching_locale(self):
        addon = Addon.objects.get(pk=3615)
        addon.summary = {'en-US': 'Delicious', 'fr': 'Francais'}
        addon.save()

        # This will prime the cache with the en-US version.
        response = make_call(self.good)
        self.assertContains(response, '<summary>Delicious')

        # We should get back the fr version, not the en-US one.
        response = make_call(self.good, lang='fr')
        self.assertContains(response, '<summary>Francais')

    def test_api_caching_app(self):
        response = make_call(self.good)
        assert 'en-US/firefox/addon/None/reviews/?src=api' in response.content
        assert 'en-US/android/addon/None/reviews/' not in response.content

        response = make_call(self.good, app='android')
        assert 'en-US/android/addon/None/reviews/?src=api' in response.content
        assert 'en-US/firefox/addon/None/reviews/' not in response.content

    def test_xss(self):
        addon_factory(guid='test@xss', name='<script>alert("test");</script>')
        r = make_call('search/guid:test@xss')
        assert '<script>alert' not in r.content
        assert '&lt;script&gt;alert' in r.content

    def test_block_inactive(self):
        Addon.objects.filter(id=6113).update(disabled_by_user=True)
        r = make_call(self.good)
        assert set(['3615']) == (
            set([a.attrib['id'] for a in pq(r.content)('addon')])
        )

    def test_block_nonpublic(self):
        Addon.objects.filter(id=6113).update(status=amo.STATUS_NOMINATED)
        r = make_call(self.good)
        assert set(['3615']) == (
            set([a.attrib['id'] for a in pq(r.content)('addon')])
        )

    def test_empty(self):
        """
        Bug: https://bugzilla.mozilla.org/show_bug.cgi?id=607044
        guid:foo, should search for just 'foo' and not empty guids.
        """
        r = make_call('search/guid:koberger,')
        doc = pq(r.content)
        # No addons should exist with guid koberger and the , should not
        # indicate that we are searching for null guid.
        assert len(doc('addon')) == 0

    def test_addon_compatibility(self):
        addon = Addon.objects.get(id=3615)
        r = make_call('search/guid:%s' % addon.guid)
        dom = pq(r.content, parser='xml')
        assert len(dom('addon_compatibility')) == 1
        assert dom('addon_compatibility')[0].attrib['id'] == '3615'
        assert dom('addon_compatibility')[0].attrib['hosted'] == 'true'

        assert dom('addon_compatibility guid').text() == addon.guid
        assert dom('addon_compatibility > name').text() == ''

        assert dom(
            'addon_compatibility version_ranges version_range '
            'compatible_applications application appID'
        ).text() == (amo.FIREFOX.guid)

    def test_addon_compatibility_not_hosted(self):
        c = CompatOverride.objects.create(guid='yeah', name='ok')
        CompatOverrideRange.objects.create(
            app=1,
            compat=c,
            min_version='1',
            max_version='2',
            min_app_version='3',
            max_app_version='4',
        )

        r = make_call('search/guid:%s' % c.guid)
        dom = pq(r.content, parser='xml')
        assert len(dom('addon_compatibility')) == 1
        assert dom('addon_compatibility')[0].attrib['hosted'] == 'false'
        assert 'id' not in dom('addon_compatibility')[0].attrib

        assert dom('addon_compatibility guid').text() == c.guid
        assert dom('addon_compatibility > name').text() == c.name

        cr = c.compat_ranges[0]
        assert dom('version_range')[0].attrib['type'] == cr.override_type()
        assert dom('version_range > min_version').text() == cr.min_version
        assert dom('version_range > max_version').text() == cr.max_version
        assert dom('application name').text() == amo.FIREFOX.pretty
        assert dom('application application_id').text() == str(amo.FIREFOX.id)
        assert dom('application appID').text() == amo.FIREFOX.guid
        assert dom('application min_version').text() == cr.min_app_version
        assert dom('application max_version').text() == cr.max_app_version


class SearchTest(ESTestCase):
    fixtures = (
        'base/appversion',
        'base/addon_6113',
        'base/addon_40',
        'base/addon_3615',
        'base/addon_6704_grapple',
        'base/addon_4664_twitterbar',
        'base/addon_10423_youtubesearch',
        'base/featured',
    )

    no_results = """<searchresults total_results="0">"""

    def setUp(self):
        super(SearchTest, self).setUp()
        self.addons = Addon.objects.filter(
            status=amo.STATUS_PUBLIC, disabled_by_user=False
        )
        t = Tag.objects.create(tag_text='ballin')
        a = Addon.objects.get(pk=3615)
        AddonTag.objects.create(tag=t, addon=a)

        [addon.save() for addon in self.addons]
        self.refresh()

        self.url = (
            '/en-US/firefox/api/%(api_version)s/search/%(query)s/'
            '%(type)s/%(limit)s/%(platform)s/%(app_version)s/'
            '%(compat_mode)s'
        )
        self.defaults = {
            'api_version': '1.5',
            'type': 'all',
            'limit': '30',
            'platform': 'Linux',
            'app_version': '4.0',
            'compat_mode': 'strict',
        }

    def test_double_escaping(self):
        """
        For API < 1.5 we use double escaping in search.
        """
        resp = make_call(
            'search/%25E6%2596%25B0%25E5%2590%258C%25E6%2596%'
            '2587%25E5%25A0%2582/all/10/WINNT/3.6',
            version=1.2,
        )
        self.assertContains(resp, '<addon id="6113">')

    def test_zero_results(self):
        """
        Tests that the search API correctly gives us zero results found.
        """
        # The following URLs should yield zero results.
        zeros = (
            'yslow',
            'jsonview',
            'firebug/3',
            'grapple/all/10/Linux',
            'jsonview/all/10/Darwin/1.0',
        )

        for url in zeros:
            if not url.startswith('/'):
                url = '/en-US/firefox/api/1.2/search/' + url

            response = self.client.get(url)
            self.assertContains(response, self.no_results, msg_prefix=url)

        for url in zeros:
            if not url.startswith('/'):
                url = '/en-US/firefox/api/1.5/search/' + url

            response = self.client.get(url)
            self.assertContains(response, self.no_results, msg_prefix=url)

    def test_search_for_specifics(self):
        """
        Tests that the search API correctly returns specific results.
        """
        expect = {
            'delicious': 'Delicious Bookmarks',
            'delicious/1': 'Delicious Bookmarks',
            'grapple/all/10/Darwin': 'GrApple',
            'delicious/all/10/Darwin/3.5': 'Delicious Bookmarks',
            '/en-US/firefox/api/1.2/search/twitter/all/10/Linux/3.5': 'TwitterBar',
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
            "/en-US/firefox/api/1.2/search/delicious/all/1"
        )
        assert response.content.count("<addon id") == 1

    def test_total_results(self):
        """
        The search for firefox should result in 2 total addons, even though we
        limit (and therefore show) only 1.
        """
        response = self.client.get("/en-US/firefox/api/1.2/search/fox/all/1")
        self.assertContains(response, """<searchresults total_results="2">""")
        self.assertContains(response, "</addon>", 1)

    def test_unlisted_are_ignored(self):
        """
        Test that unlisted add-ons are not shown.
        """
        addon = Addon.objects.get(pk=3615)
        self.make_addon_unlisted(addon)
        addon.reload()
        self.refresh()
        response = self.client.get("/en-US/firefox/api/1.2/search/delicious")
        self.assertContains(response, """<searchresults total_results="0">""")
        self.assertContains(response, "</addon>", 0)

    def test_experimental_are_ignored(self):
        """
        Test that experimental add-ons are not shown.
        """
        addon = Addon.objects.get(pk=3615)
        addon.update(is_experimental=True)
        self.refresh()
        response = self.client.get("/en-US/firefox/api/1.2/search/delicious")
        self.assertContains(response, """<searchresults total_results="0">""")
        self.assertContains(response, "</addon>", 0)

    def test_compat_mode_url(self):
        """
        Test the compatMode paramenter in the URL is optional and only accepts
        values of: strict, normal, and ignore.
        """
        base = '/en-US/firefox/api/1.5/search/firefox/all/1/Linux/3.0'
        assert self.client.head(base).status_code == 200
        assert self.client.head(base + '/strict').status_code == 200
        assert self.client.head(base + '/normal').status_code == 200
        assert self.client.head(base + '/ignore').status_code == 200
        assert self.client.head(base + '/junk').status_code == 404

    def test_compat_mode_ignore(self):
        # Delicious currently supports Firefox 2.0 - 3.7a1pre. Strict mode will
        # not find it. Ignore mode should include it if the appversion is
        # specified as higher.
        self.defaults.update(
            query='delicious', app_version='5.0'
        )  # Defaults to strict.
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)
        self.defaults.update(query='delicious', compat_mode='ignore')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

    def test_compat_mode_normal_and_strict_opt_in(self):
        # Under normal compat mode we ignore max version unless the add-on has
        # opted into strict mode. Test before and after search queries.
        addon = Addon.objects.get(pk=3615)
        self.defaults.update(query='delicious', app_version='5.0')

        self.defaults.update(compat_mode='normal')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

        # Make add-on opt into strict compatibility.
        file = addon.current_version.files.all()[0]
        file.update(strict_compatibility=True)
        assert File.objects.get(pk=file.id).strict_compatibility
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure compat_mode=strict also doesn't find it.
        self.defaults.update(compat_mode='strict')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure we find it with compat_mode=ignore
        self.defaults.update(compat_mode='ignore')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

    def test_compat_mode_normal_and_binary_components(self):
        # We ignore max version as long as the add-on has no binary components.
        # Test before and after search queries.
        addon = Addon.objects.get(pk=3615)
        self.defaults.update(query='delicious', app_version='5.0')

        self.defaults.update(compat_mode='normal')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

        # Make add-on contain binary components.
        file = addon.current_version.files.all()[0]
        file.update(binary_components=True)
        assert File.objects.get(pk=file.id).binary_components
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure compat_mode=strict also doesn't find it.
        self.defaults.update(compat_mode='strict')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure we find it with compat_mode=ignore
        self.defaults.update(compat_mode='ignore')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

    def test_compat_mode_normal_and_binary_components_multi_file(self):
        # This checks that versions with multiple files uses the platform to
        # pick the right file for checking binary_components.
        addon = Addon.objects.get(pk=3615)

        file1 = addon.current_version.files.all()[0]
        file1.update(platform=amo.PLATFORM_LINUX.id)

        # Make a 2nd file just like the 1st, but with a different platform that
        # uses binary_components.
        file2 = file1
        file2.id = None
        file2.platform = amo.PLATFORM_WIN.id
        file2.binary_components = True
        file2.save()

        self.defaults.update(query='delicious', app_version='5.0')

        # Linux doesn't use binary components.
        self.defaults.update(compat_mode='normal')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

        # Windows does use binary components, so it should find no results.
        self.defaults.update(platform='WINNT')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure compat_mode=strict also doesn't find it.
        self.defaults.update(compat_mode='strict')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure we find it with compat_mode=ignore
        self.defaults.update(compat_mode='ignore')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

    def test_compat_mode_normal_max_version(self):
        # We ignore versions that don't qualify for d2c by not having the
        # minimum maxVersion support (e.g. Firefox >= 4.0).
        fx30 = AppVersion.objects.get(application=1, version="3.0")
        fx35 = AppVersion.objects.get(application=1, version="3.5")
        addon = Addon.objects.get(pk=3615)
        av = addon.current_version.apps.filter(application=1)[0]
        av.min = fx30
        av.max = fx35
        av.save()
        addon.save()

        # Make sure compat_mode=strict doesn't find it. This won't find it
        # because app version doesn't fall within supported app range.
        self.defaults.update(query='delicious')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure compat_mode=normal doesn't find it. This shouldn't find it
        # because the min maxVersion isn't >= 4.0 so it's not deemed
        # compatible.
        self.defaults.update(compat_mode='normal')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure compat_mode=normal finds it since 3.0 <= 4.0.
        self.defaults.update(compat_mode='ignore')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

    def test_compat_override(self):
        # Under normal compat mode we ignore add-ons with a compat override.
        addon = Addon.objects.get(pk=3615)
        self.defaults.update(query='delicious', app_version='5.0')

        self.defaults.update(compat_mode='normal')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

        # Make add-on have a compat override.
        co = CompatOverride.objects.create(
            name='test', guid=addon.guid, addon=addon
        )
        CompatOverrideRange.objects.create(
            compat=co,
            app=1,
            min_version='0',
            max_version='*',
            min_app_version='0',
            max_app_version='*',
        )
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure compat_mode=strict also doesn't find it.
        self.defaults.update(compat_mode='strict')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, self.no_results)

        # Make sure we find it with compat_mode=ignore
        self.defaults.update(compat_mode='ignore')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Delicious Bookmarks')

    def test_cross_origin(self):
        # The search view doesn't allow cross-origin requests.
        # First we check for a search without results.
        response = self.client.get(
            '/en-US/firefox/api/%.1f/search/firebug/3'
            % legacy_api.CURRENT_VERSION
        )

        assert not response.has_header('Access-Control-Allow-Origin')
        assert not response.has_header('Access-Control-Allow-Methods')

        # Now a search with results.
        response = self.client.get(
            '/en-US/firefox/api/%.1f/search/delicious'
            % legacy_api.CURRENT_VERSION
        )

        assert not response.has_header('Access-Control-Allow-Origin')
        assert not response.has_header('Access-Control-Allow-Methods')

    def test_persona_search(self):
        self.defaults.update(query='lady')
        # Personas aren't returned in a standard API search.
        response = self.client.get(self.url % self.defaults)
        self.assertNotContains(response, 'Lady Gaga')

        # But they are if you specifically ask for Personas (type=9).
        self.defaults.update(type='9')
        response = self.client.get(self.url % self.defaults)
        self.assertContains(response, 'Lady Gaga')

    def test_suggestions(self):
        response = self.client.get(
            '/en-US/firefox/api/%.1f/search_suggestions/?q=delicious'
            % legacy_api.CURRENT_VERSION
        )
        data = json.loads(response.content)['suggestions'][0]
        a = Addon.objects.get(pk=3615)
        assert data['id'] == str(a.pk)
        assert data['name'] == a.name
        assert data['rating'] == a.average_rating

    def test_no_category_suggestions(self):
        response = self.client.get(
            '/en-US/firefox/api/%.1f/search_suggestions/?q=Feed'
            % legacy_api.CURRENT_VERSION
        )
        assert json.loads(response.content)['suggestions'] == []

    def test_suggestions_throttle(self):
        self.create_sample('autosuggest-throttle')
        response = self.client.get(
            '/en-US/firefox/api/%.1f/search_suggestions/?q=delicious'
            % legacy_api.CURRENT_VERSION
        )
        assert response.status_code == 503


class LanguagePacksTest(UploadTest):
    fixtures = ['addons/listed']

    def setUp(self):
        super(LanguagePacksTest, self).setUp()
        self.url = reverse('legacy_api.language', args=['1.5'])
        self.tb_url = self.url.replace('firefox', 'thunderbird')
        self.addon = Addon.objects.get(pk=3723)

    def test_search_language_pack(self):
        self.addon.update(type=amo.ADDON_LPAPP, status=amo.STATUS_PUBLIC)
        res = self.client.get(self.url)
        self.assertContains(res, "<guid>{835A3F80-DF39")

    def test_search_no_language_pack(self):
        res = self.client.get(self.url)
        self.assertNotContains(res, "<guid>{835A3F80-DF39")

    def test_search_app(self):
        self.addon.update(type=amo.ADDON_LPAPP, status=amo.STATUS_PUBLIC)
        AppSupport.objects.create(addon=self.addon, app=amo.THUNDERBIRD.id)
        res = self.client.get(self.tb_url)
        self.assertContains(res, "<guid>{835A3F80-DF39")

    def test_search_no_app(self):
        self.addon.update(type=amo.ADDON_LPAPP, status=amo.STATUS_PUBLIC)
        res = self.client.get(self.tb_url)
        self.assertNotContains(res, "<guid>{835A3F80-DF39")

    def test_search_no_localepicker(self):
        self.addon.update(type=amo.ADDON_LPAPP, status=amo.STATUS_PUBLIC)
        res = self.client.get(self.tb_url)
        self.assertNotContains(res, "<strings><![CDATA[")

    def setup_localepicker(self, platform):
        self.addon.update(type=amo.ADDON_LPAPP, status=amo.STATUS_PUBLIC)
        version = self.addon.versions.all()[0]
        File.objects.create(
            version=version, platform=platform, status=amo.STATUS_PUBLIC
        )

    def test_search_wrong_platform(self):
        self.setup_localepicker(amo.PLATFORM_MAC.id)
        assert self.addon.get_localepicker() == ''

    @patch('olympia.files.models.File.get_localepicker')
    def test_search_right_platform(self, get_localepicker):
        get_localepicker.return_value = 'some data'
        self.setup_localepicker(amo.PLATFORM_ANDROID.id)
        assert self.addon.get_localepicker() == 'some data'

    @patch('olympia.addons.models.Addon.get_localepicker')
    def test_localepicker(self, get_localepicker):
        get_localepicker.return_value = unicode('title=اختر لغة', 'utf8')
        self.addon.update(type=amo.ADDON_LPAPP, status=amo.STATUS_PUBLIC)
        res = self.client.get(self.url)
        self.assertContains(
            res,
            dedent(
                """
                                                <strings><![CDATA[
                                            title=اختر لغة
                                                ]]></strings>"""
            ),
        )
