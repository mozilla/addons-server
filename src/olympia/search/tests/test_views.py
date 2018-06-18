# -*- coding: utf-8 -*-
import json
import urlparse

from django.http import QueryDict
from django.test.client import RequestFactory

import mock
import pytest

from elasticsearch import Elasticsearch
from pyquery import PyQuery as pq

from olympia import amo
from olympia.addons.models import (
    Addon, AddonCategory, AddonUser, Category, Persona)
from olympia.amo.templatetags.jinja_helpers import locale_url, urlparams
from olympia.amo.tests import (
    ESTestCaseWithAddons, addon_factory, create_switch)
from olympia.amo.urlresolvers import reverse
from olympia.search import views
from olympia.search.utils import floor_version
from olympia.search.views import version_sidebar
from olympia.tags.models import AddonTag, Tag
from olympia.users.models import UserProfile
from olympia.versions.compare import (
    MAXVERSION, num as vnum, version_int as vint)


pytestmark = pytest.mark.django_db


class TestSearchboxTarget(ESTestCaseWithAddons):

    def check(self, url, placeholder, cat=None, action=None, q=None):
        # Checks that we search within addons & personas.
        form = pq(self.client.get(url).content)('.header-search form')
        assert form.attr('action') == action or reverse('search.search')
        if cat:
            assert form('input[name=cat]').val() == cat
        q_field = form('input[name=q]')
        assert q_field.attr('placeholder') == placeholder
        if q:
            assert q_field.val() == q

    def test_addons_is_default(self):
        self.check(reverse('home'), 'search for add-ons')

    def test_themes(self):
        self.check(reverse('browse.themes'), 'search for add-ons',
                   '%s,0' % amo.ADDON_THEME)

    def test_personas(self):
        self.check(reverse('browse.personas'), 'search for themes',
                   'themes')

    def test_addons_search(self):
        self.check(reverse('search.search'), 'search for add-ons')

    def test_addons_search_term(self):
        self.check(reverse('search.search') + '?q=ballin',
                   'search for add-ons', q='ballin')


class SearchBase(ESTestCaseWithAddons):

    def get_results(self, r, sort=True):
        """Return pks of add-ons shown on search results page."""
        results = [a.id for a in r.context['pager'].object_list]
        if sort:
            results = sorted(results)
        return results

    def check_sort_links(self, key, title=None, sort_by=None, reverse=True,
                         params=None):
        if params is None:
            params = {}
        response = self.client.get(urlparams(self.url, sort=key, **params))
        assert response.status_code == 200
        doc = pq(response.content)
        if title:
            assert doc('#sorter .selected').text() == title
        if sort_by:
            results = response.context['pager'].object_list
            if sort_by == 'name':
                expected = sorted(results, key=lambda x: unicode(x.name))
            else:
                expected = sorted(results, key=lambda x: getattr(x, sort_by),
                                  reverse=reverse)
            assert list(results) == expected

    def check_name_results(self, params, expected):
        r = self.client.get(urlparams(self.url, **params), follow=True)
        assert r.status_code == 200
        got = self.get_results(r)
        assert got == expected, params

    def check_appver_platform_ignored(self, expected):
        # Persona search should not filter on `appver` nor `platform`.
        permutations = [
            {},
            {'appver': amo.FIREFOX.id},
            {'appver': amo.THUNDERBIRD.id},
            {'platform': amo.PLATFORM_MAC.id},
            {'appver': amo.SEAMONKEY.id, 'platform': amo.PLATFORM_WIN.id},
        ]
        for p in permutations:
            self.check_name_results(p, expected)

    def check_heading(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        assert pq(r.content)('.results-count strong').text() is ''

        r = self.client.get(self.url + '&q=ballin')
        assert r.status_code == 200
        assert pq(r.content)('.results-count strong').text() == 'ballin'


class TestESSearch(SearchBase):
    fixtures = ['base/category']

    def setUp(self):
        super(TestESSearch, self).setUp()
        self.url = reverse('search.search')
        self.addons = Addon.objects.filter(status=amo.STATUS_PUBLIC,
                                           disabled_by_user=False)
        for addon in self.addons:
            AddonCategory.objects.create(addon=addon, category_id=1)
            addon.save()
        self.refresh()

    def test_get(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'X-PJAX' in response['vary'].split(',')
        self.assertTemplateUsed(response, 'search/results.html')

    def test_es_queries_made_get_with_results(self):
        with mock.patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            response = self.client.get(self.url)
            assert response.status_code == 200
            assert search_mock.call_count == 1

    def test_es_queries_made_get_without_results(self):
        with mock.patch.object(
                Elasticsearch, 'search',
                wraps=amo.search.get_es().search) as search_mock:
            response = self.client.get(self.url, {'q': 'foo'})
            assert response.status_code == 200
            assert search_mock.call_count == 1

    def test_search_space(self):
        response = self.client.get(urlparams(self.url, q='+'))
        assert response.status_code == 200

    def test_search_tools_omit_users(self):
        response = self.client.get(
            self.url, {'cat': '%s,5' % amo.ADDON_SEARCH})
        assert response.status_code == 200
        sorter = pq(response.content)('#sorter')
        assert sorter.length == 1
        assert 'sort=users' not in sorter.text(), (
            'Sort by "Most Users" should not appear for search tools.')

    def test_results_sort_default(self):
        self.check_sort_links(None, 'Relevance', 'weekly_downloads')

    def test_results_sort_unknown(self):
        self.check_sort_links('xxx', 'Relevance')

    def test_results_sort_users(self):
        self.check_sort_links('users', 'Most Users', 'average_daily_users')

    def test_results_sort_rating(self):
        self.check_sort_links('rating', 'Top Rated', 'bayesian_rating')

    def test_results_sort_newest(self):
        self.check_sort_links('created', 'Newest', 'created')

    def test_results_sort_updated(self):
        self.check_sort_links('updated', 'Recently Updated')

    def test_results_sort_downloads(self):
        self.check_sort_links('downloads', 'Weekly Downloads',
                              'weekly_downloads')

    def test_results_sort_name(self):
        self.check_sort_links('name', 'Name', 'name', reverse=False)

    def test_new_frontend_type_redirect(self):
        response = self.client.get(self.url + u'?q=fôo&type=extension')
        # Can't use assert3xx because the query parameters ordering is not
        # guaranteed.
        assert response.status_code == 302
        expected_params = 'q=f%C3%B4o&atype=1'
        redirected = response.url
        parsed = urlparse.urlparse(redirected)
        params = parsed.query
        assert parsed.path == self.url
        assert urlparse.parse_qs(params) == urlparse.parse_qs(expected_params)

    def test_legacy_redirects(self):
        response = self.client.get(self.url + '?sort=averagerating')
        self.assert3xx(response, self.url + '?sort=rating', status_code=301)

    def test_legacy_redirects_to_non_ascii(self):
        # see http://sentry.dmz.phx1.mozilla.com/addons/group/2186/
        url = '/ga-IE/seamonkey/tag/%E5%95%86%E5%93%81%E6%90%9C%E7%B4%A2'
        from_ = ('?sort=updated&lver=1.0&advancedsearch=1'
                 '&tag=dearbhair&cat=4%2C84')
        to = ('?sort=updated&advancedsearch=1&appver=1.0'
              '&tag=dearbhair&cat=4%2C84')
        r = self.client.get(url + from_)
        assert r.status_code == 301
        redirected = r.url
        parsed = urlparse.urlparse(redirected)
        params = parsed.query
        assert parsed.path == url
        assert urlparse.parse_qs(params) == urlparse.parse_qs(to[1:])

    def check_platform_filters(self, platform, expected=None):
        r = self.client.get('%s?platform=%s' % (self.url, platform),
                            follow=True)
        plats = r.context['platforms']
        for idx, plat in enumerate(plats):
            name, selected = expected[idx]
            label = unicode(plat.text)
            assert label == name
            assert plat.selected == selected

    def test_platform_default(self):
        expected = [
            ('All Systems', True),
            ('Linux', False),
            ('Mac OS X', False),
            ('Windows', False),
        ]
        self.check_platform_filters('', expected)
        self.check_platform_filters('all', expected)
        self.check_platform_filters('any', expected)
        self.check_platform_filters('amiga', expected)

    def test_platform_listed(self):
        expected = [
            ('All Systems', False),
            ('Linux', True),
            ('Mac OS X', False),
            ('Windows', False),
        ]
        self.check_platform_filters('linux', expected)

        expected = [
            ('All Systems', False),
            ('Linux', False),
            ('Mac OS X', False),
            ('Windows', True),
        ]
        self.check_platform_filters('windows', expected)

        expected = [
            ('All Systems', False),
            ('Linux', False),
            ('Mac OS X', True),
            ('Windows', False),
        ]
        self.check_platform_filters('mac', expected)

    def test_platform_incompatible(self):
        expected = [
            ('All Systems', True),
            ('Linux', False),
            ('Mac OS X', False),
            ('Windows', False),
        ]
        self.check_platform_filters('any', expected)

    def test_platform_legacy_params(self):
        ALL = (amo.PLATFORM_ALL, amo.PLATFORM_ANY)
        listed = ALL + (amo.PLATFORM_LINUX, amo.PLATFORM_MAC, amo.PLATFORM_WIN)
        for idx, platform in amo.PLATFORMS.iteritems():
            expected = [
                ('All Systems', platform in ALL),
                ('Linux', platform == amo.PLATFORM_LINUX),
                ('Mac OS X', platform == amo.PLATFORM_MAC),
                ('Windows', platform == amo.PLATFORM_WIN),
            ]
            if platform not in listed:
                expected.append((platform.name, True))
            self.check_platform_filters(str(idx), expected)

    def check_appver_filters(self, appver, expected):
        request = RequestFactory()
        request.GET = {}
        request.APP = amo.FIREFOX

        facets = {
            u'platforms': [{u'doc_count': 58, u'key': 1}],
            u'appversions': [{u'doc_count': 58, u'key': 5000000200100}],
            u'categories': [{u'doc_count': 55, u'key': 1}],
            u'tags': []
        }

        versions = version_sidebar(request,
                                   {'appver': floor_version(appver)}, facets)

        all_ = versions.pop(0)
        assert all_.text == 'Any %s' % unicode(request.APP.pretty)
        assert not all_.selected == expected

        return [v.__dict__ for v in versions]

    def test_appver_default(self):
        assert self.check_appver_filters('', '') == (
            [{'text': u'Firefox 5.0',
              'selected': False,
              'urlparams': {'appver': '5.0'},
              'children': []}])

    def test_appver_known(self):
        assert self.check_appver_filters('5.0', '5.0') == (
            [{'text': u'Firefox 5.0',
              'selected': True,
              'urlparams': {'appver': '5.0'},
              'children': []}])

    def test_appver_oddballs(self):
        assert self.check_appver_filters('3.6.22', '3.6') == (
            [{'text': u'Firefox 5.0',
              'selected': False,
              'urlparams': {'appver': '5.0'},
              'children': []},
             {'text': u'Firefox 3.6',
              'selected': True,
              'urlparams': {'appver': '3.6'},
              'children': []}])

    def test_appver_long(self):
        too_big = vnum(vint(MAXVERSION + 1))
        just_right = vnum(vint(MAXVERSION))

        assert self.check_appver_filters(too_big, floor_version(just_right)), (
            'All I ask is do not crash')

        assert self.check_appver_filters('9999999', '9999999.0') == (
            [{'text': u'Firefox 9999999.0',
              'selected': True,
              'urlparams': {'appver': '9999999.0'},
              'children': []},
             {'text': u'Firefox 5.0',
              'selected': False,
              'urlparams': {'appver': '5.0'},
              'children': []}])

        assert self.check_appver_filters('99999999', '99999999.0') == (
            [{'text': u'Firefox 99999999.0',
              'selected': True,
              'urlparams': {'appver': '99999999.0'},
              'children': []},
             {'text': u'Firefox 5.0',
              'selected': False,
              'urlparams': {'appver': '5.0'},
              'children': []}])

    def test_appver_bad(self):
        assert self.check_appver_filters('.', '.')
        assert self.check_appver_filters('_', '_')
        assert self.check_appver_filters('y.y', 'y.y')
        assert self.check_appver_filters('*', '*')

    def test_non_pjax_results(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        assert r.context['is_pjax'] is None

        # These context variables should exist for normal requests.
        for var in ('categories', 'platforms', 'versions', 'tags'):
            assert var in r.context, '%r missing context var in view' % var

        doc = pq(r.content)
        assert doc('html').length == 1
        assert doc('#pjax-results').length == 1
        assert doc('#search-facets .facets.pjax-trigger').length == 1
        assert doc('#sorter.pjax-trigger').length == 1

    def test_pjax_results(self):
        r = self.client.get(self.url, HTTP_X_PJAX=True)
        assert r.status_code == 200
        assert r.context['is_pjax']

        doc = pq(r.content)
        assert doc('html').length == 0
        assert doc('#pjax-results').length == 0
        assert doc('#search-facets .facets.pjax-trigger').length == 0
        assert doc('#sorter.pjax-trigger').length == 1

    def test_facet_data_params_default(self):
        r = self.client.get(self.url)
        a = pq(r.content)('#search-facets a[data-params]:first')
        assert json.loads(a.attr('data-params')) == {
            'atype': None, 'cat': None, 'page': None}

    def test_facet_data_params_filtered(self):
        r = self.client.get(self.url + '?appver=3.6&platform=mac&page=3')
        a = pq(r.content)('#search-facets a[data-params]:first')
        assert json.loads(a.attr('data-params')) == {
            'atype': None, 'cat': None, 'page': None}

    def check_cat_filters(self, params=None, selected='All Add-ons'):
        if not params:
            params = {}

        r = self.client.get(urlparams(self.url, **params))
        assert sorted(a.id for a in self.addons) == (
            sorted(a.id for a in r.context['pager'].object_list))

        cat = self.addons[0].all_categories[0]
        links = pq(r.content)('#category-facets li a')
        expected = [
            ('All Add-ons', self.url),
            ('Extensions', urlparams(self.url, atype=amo.ADDON_EXTENSION)),
            (unicode(cat.name), urlparams(self.url, atype=amo.ADDON_EXTENSION,
                                          cat=cat.id)),
        ]
        amo.tests.check_links(expected, links, selected, verify=False)

    def test_defaults_atype_no_cat(self):
        self.check_cat_filters({'atype': 1})

    def test_defaults_atype_unknown_cat(self):
        self.check_cat_filters({'atype': amo.ADDON_EXTENSION, 'cat': 999})

    def test_defaults_no_atype_unknown_cat(self):
        self.check_cat_filters({'cat': 999})

    def test_defaults_atype_foreign_cat(self):
        cat = Category.objects.create(application=amo.THUNDERBIRD.id,
                                      type=amo.ADDON_EXTENSION)
        self.check_cat_filters({'atype': amo.ADDON_EXTENSION, 'cat': cat.id})

    def test_listed_cat(self):
        cat = self.addons[0].all_categories[0]
        self.check_cat_filters(
            {'atype': amo.ADDON_EXTENSION, 'cat': cat.id},
            selected=unicode(cat.name))

    def test_cat_facet_stale(self):
        AddonCategory.objects.all().delete()

        r = self.client.get(self.url)
        expected = [
            ('All Add-ons', self.url),
            ('Extensions', urlparams(self.url, atype=amo.ADDON_EXTENSION)),
        ]
        amo.tests.check_links(expected, pq(r.content)('#category-facets li a'),
                              verify=False)

    def test_cat_facet_fresh(self):
        AddonCategory.objects.all().delete()
        # Save to reindex with new categories.
        self.reindex(Addon)

        r = self.client.get(self.url)
        amo.tests.check_links([('All Add-ons', self.url)],
                              pq(r.content)('#category-facets li a'),
                              verify=False)

    def test_unknown_tag_filter(self):
        r = self.client.get(urlparams(self.url, tag='xxx'))
        a = pq(r.content)('#tag-facets li.selected a')
        assert a.length == 1
        assert a.text() == 'xxx'
        assert list(r.context['pager'].object_list) == []

    def test_tag_filters_on_search_page(self):
        Tag(tag_text='sky').save_tag(self.addons[0])
        Tag(tag_text='sky').save_tag(self.addons[1])
        Tag(tag_text='sky').save_tag(self.addons[2])
        Tag(tag_text='earth').save_tag(self.addons[0])
        Tag(tag_text='earth').save_tag(self.addons[1])
        Tag(tag_text='ocean').save_tag(self.addons[0])
        self.reindex(Addon)

        response = self.client.get(self.url, {'tag': 'sky'})
        assert response.status_code == 200
        assert self.get_results(response)

        # Tags filter UI should show 4 items ("All Tags" + 3 different tags)
        tags_links = pq(response.content)('#tag-facets li a[data-params]')
        assert len(tags_links) == 4

        # First link should be "All Tags".
        assert tags_links[0].attrib['href'] == self.url
        assert json.loads(tags_links[0].attrib['data-params']) == {
            'tag': None, 'page': None
        }

        # Then we should have the tags.
        expected_tags = ('sky', 'earth', 'ocean')
        for index, link in enumerate(tags_links[1:]):
            tag_text = expected_tags[index]
            assert link.attrib['href'] == urlparams(self.url, tag=tag_text)
            assert json.loads(link.attrib['data-params']) == {
                'tag': tag_text, 'page': None
            }

        # Selected tag should be the one we passed in the URL: 'sky'.
        link = pq(response.content)('#tag-facets li.selected a[data-params]')
        assert json.loads(link.attr('data-params')) == {
            'tag': 'sky', 'page': None
        }

    def test_no_tag_filters_on_tags_page(self):
        r = self.client.get(reverse('tags.detail', args=['sky']))
        assert r.status_code == 200
        assert pq(r.content)('#tag-facets').length == 0

    def get_results(self, response, sort=True):
        """Return pks of add-ons shown on search results page."""
        addons = pq(response.content)('#pjax-results div[data-addon]')
        pks = [int(pq(a).attr('data-addon')) for a in addons]
        if sort:
            return sorted(pks)
        return pks

    def test_results_filtered_atype(self):
        theme = self.addons[0]
        theme.type = amo.ADDON_THEME
        theme.save()
        self.reindex(Addon)

        themes = sorted(self.addons.filter(type=amo.ADDON_THEME)
                        .values_list('id', flat=True))
        assert themes == [theme.id]

        extensions = sorted(self.addons.filter(type=amo.ADDON_EXTENSION)
                            .values_list('id', flat=True))
        assert extensions == sorted(a.id for a in self.addons[1:])

        # Extensions should show only extensions.
        r = self.client.get(self.url, {'atype': amo.ADDON_EXTENSION})
        assert r.status_code == 200
        assert self.get_results(r) == extensions

        # Themes should show only themes.
        r = self.client.get(self.url, {'atype': amo.ADDON_THEME})
        assert r.status_code == 200
        assert self.get_results(r) == themes

    def test_appversion_filtering(self):
        # All test add-ons have min version 4.0.99, max version 5.0.99. They
        # don't have strict compatibility enabled.
        # Search for add-ons compatible with Firefox 4.0: none should be found.
        response = self.client.get(self.url, {'appver': '4.0'})
        assert self.get_results(response) == []

        # Search for add-ons compatible with Firefox 10.0: all should be found.
        response = self.client.get(self.url, {'appver': '10.0'})
        expected_addons_pks = sorted(self.addons.values_list('id', flat=True))
        assert self.get_results(response) == expected_addons_pks

        # Set strict compatibility to True on one of them, it should no longer
        # be returned when searching for add-ons compatible with 10.0 since the
        # max version is 5.0.99.
        addon = self.addons[0]
        addon.current_version.files.update(strict_compatibility=True)
        addon.save()
        self.refresh()
        response = self.client.get(self.url, {'appver': '10.0'})
        expected_addons_pks = sorted(
            self.addons.exclude(pk=addon.pk).values_list('id', flat=True))
        assert self.get_results(response) == expected_addons_pks

    def test_results_platform_filter_all(self):
        for platform in ('', 'all'):
            r = self.client.get(self.url, {'platform': platform})
            assert self.get_results(r) == (
                sorted(self.addons.values_list('id', flat=True)))

    def test_slug_indexed_but_not_searched(self):
        a = self.addons[0]

        r = self.client.get(self.url, {'q': 'omgyes'})
        assert self.get_results(r) == []

        a.update(slug='omgyes')
        self.refresh()
        r = self.client.get(self.url, {'q': 'omgyes'})
        assert self.get_results(r) == []

    def test_authors_indexed(self):
        a = self.addons[0]

        r = self.client.get(self.url, {'q': 'boop'})
        assert self.get_results(r) == []

        AddonUser.objects.create(
            addon=a, user=UserProfile.objects.create(username='boop'))
        AddonUser.objects.create(
            addon=a, user=UserProfile.objects.create(username='ponypet'))
        a.save()
        self.refresh()
        r = self.client.get(self.url, {'q': 'garbage'})
        assert self.get_results(r) == []
        r = self.client.get(self.url, {'q': 'boop'})
        assert self.get_results(r) == [a.id]
        r = self.client.get(self.url, {'q': 'pony'})
        assert self.get_results(r) == [a.id]

    def test_tag_search(self):
        a = self.addons[0]

        tag_name = 'tagretpractice'
        r = self.client.get(self.url, {'q': tag_name})
        assert self.get_results(r) == []

        AddonTag.objects.create(
            addon=a, tag=Tag.objects.create(tag_text=tag_name))

        a.save()
        self.refresh()

        r = self.client.get(self.url, {'q': tag_name})
        assert self.get_results(r) == [a.id]

        # Multiple tags.
        tag_name_2 = 'bagemtagem'
        AddonTag.objects.create(
            addon=a, tag=Tag.objects.create(tag_text=tag_name_2))
        a.save()
        self.refresh()
        r = self.client.get(self.url, {'q': '%s %s' % (tag_name, tag_name_2)})
        assert self.get_results(r) == [a.id]

    def test_search_doesnt_return_unlisted_addons(self):
        addon = self.addons[0]
        response = self.client.get(self.url, {'q': 'Addon'})
        assert addon.pk in self.get_results(response)

        self.make_addon_unlisted(addon)
        addon.reload()
        self.refresh()
        response = self.client.get(self.url, {'q': 'Addon'})
        assert addon.pk not in self.get_results(response)

    def test_webextension_boost(self):
        web_extension = list(sorted(
            self.addons, key=lambda x: x.name, reverse=True))[0]
        web_extension.current_version.files.update(is_webextension=True)
        web_extension.save()
        self.refresh()

        response = self.client.get(self.url, {'q': 'Addon'})
        result = self.get_results(response, sort=False)
        assert result[0] != web_extension.pk

        create_switch('boost-webextensions-in-search')
        # The boost chosen should have made that addon the first one.
        response = self.client.get(self.url, {'q': 'Addon'})
        result = self.get_results(response, sort=False)
        assert result[0] == web_extension.pk

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

        addon_en = addon_factory(
            slug='English Addon', name=u'My English Addôn')

        self.refresh()

        # Make sure we have en-US active
        for locale in ('en-US', 'en-GB', 'es'):
            with self.activate(locale):
                url = self.url.replace('en-US', locale)

                response = self.client.get(url, {'q': ''})
                result = self.get_results(response, sort=False)

                # 3 add-ons in self.addon + the two just created
                assert addon_en.pk in result
                assert addon.pk in result

                response = self.client.get(url, {'q': 'Banana'})
                result = self.get_results(response, sort=False)

                assert result[0] == addon.pk

                response = self.client.get(url, {'q': 'plátanos'})
                result = self.get_results(response, sort=False)

                assert result[0] == addon.pk


class TestPersonaSearch(SearchBase):

    def setUp(self):
        super(TestPersonaSearch, self).setUp()
        self.url = urlparams(reverse('search.search'), atype=amo.ADDON_PERSONA)

    def _generate_personas(self):
        # Add some public personas.
        self.personas = []
        for status in [amo.STATUS_PUBLIC] * 3:
            addon = amo.tests.addon_factory(type=amo.ADDON_PERSONA,
                                            status=status)
            self.personas.append(addon)
            self._addons.append(addon)

        # Add some unreviewed personas.
        for status in set(Addon.STATUS_CHOICES) - set(amo.REVIEWED_STATUSES):
            self._addons.append(amo.tests.addon_factory(type=amo.ADDON_PERSONA,
                                                        status=status))

        # Add a disabled persona.
        self._addons.append(amo.tests.addon_factory(type=amo.ADDON_PERSONA,
                                                    disabled_by_user=True))

        # NOTE: There are also some add-ons in the setUpClass for good measure.

        self.refresh()

    def test_sort_order_default(self):
        self._generate_personas()
        self.check_sort_links(None, sort_by='average_daily_users')

    def test_sort_order_unknown(self):
        self._generate_personas()
        self.check_sort_links('xxx')

    def test_sort_order_users(self):
        self._generate_personas()
        self.check_sort_links('users', sort_by='average_daily_users')

    def test_sort_order_rating(self):
        self._generate_personas()
        self.check_sort_links('rating', sort_by='bayesian_rating')

    def test_sort_order_newest(self):
        self._generate_personas()
        self.check_sort_links('created', sort_by='created')

    def test_heading(self):
        self.check_heading()

    def test_results_blank_query(self):
        self._generate_personas()
        personas_ids = sorted(p.id for p in self.personas)  # Not PersonaID ;)
        r = self.client.get(self.url, follow=True)
        assert r.status_code == 200
        assert self.get_results(r) == personas_ids
        doc = pq(r.content)
        assert doc('.personas-grid li').length == len(personas_ids)
        assert doc('.listing-footer').length == 0

    def test_results_name_query(self):
        self._generate_personas()

        p1 = self.personas[0]
        p1.name = 'Harry Potter'
        p1.save()

        p2 = self.personas[1]
        p2.name = 'The Life Aquatic with SeaVan'
        p2.save()
        self.refresh()

        # Empty search term should return everything.
        self.check_name_results({'q': ''}, sorted(p.id for p in self.personas))

        # Garbage search terms should return nothing.
        for term in ('xxx', 'garbage', '£'):
            self.check_name_results({'q': term}, [])

        # Try to match 'Harry Potter'.
        for term in ('harry', 'potter', 'har', 'pot', 'harry pooper'):
            self.check_name_results({'q': term}, [p1.pk])

        # Try to match 'The Life Aquatic with SeaVan'.
        # We have prefix_length=4 so fuzziness matching starts
        # at the 4th character for performance reasons.
        for term in ('life', 'aquatic', 'seavan', 'sea van'):
            self.check_name_results({'q': term}, [p2.pk])

    def test_results_popularity(self):
        personas = [
            ('Harry Potter', 2000),
            ('Japanese Koi Tattoo', 67),
            ('Japanese Tattoo', 250),
            ('Japanese Tattoo boop', 50),
            ('Japanese Tattoo ballin', 200),
            ('The Japanese Tattooed Girl', 242),
        ]
        for name, popularity in personas:
            self._addons.append(amo.tests.addon_factory(name=name,
                                                        type=amo.ADDON_PERSONA,
                                                        popularity=popularity))
        self.refresh()

        # Japanese Tattoo should be the #1 most relevant result. Obviously.
        expected_name, expected_popularity = personas[2]
        for sort in ('downloads', 'popularity', 'users'):
            r = self.client.get(urlparams(self.url, q='japanese tattoo',
                                          sort=sort), follow=True)
            assert r.status_code == 200
            results = list(r.context['pager'].object_list)
            first = results[0]
            assert unicode(first.name) == expected_name, (
                'Was not first result for %r. Results: %s' % (sort, results))
            assert first.persona.popularity == expected_popularity, (
                'Incorrect popularity for %r. Got %r. Expected %r.' % (
                    sort, first.persona.popularity, results))
            assert first.average_daily_users == expected_popularity, (
                'Incorrect users for %r. Got %r. Expected %r.' % (
                    sort, first.average_daily_users, results))
            assert first.weekly_downloads == expected_popularity, (
                'Incorrect weekly_downloads for %r. Got %r. Expected %r.' % (
                    sort, first.weekly_downloads, results))

    def test_results_appver_platform(self):
        self._generate_personas()
        self.check_appver_platform_ignored(sorted(p.id for p in self.personas))

    def test_results_other_applications(self):
        self._generate_personas()
        # Now ensure we get the same results for Firefox as for Thunderbird.
        self.url = self.url.replace('firefox', 'thunderbird')
        self.check_name_results({}, sorted(p.id for p in self.personas))

    # Pretend we only want 2 personas per result page.
    @mock.patch('olympia.search.views.DEFAULT_NUM_PERSONAS', 2)
    def test_pagination(self):
        self._generate_personas()  # This creates 3 public personas.

        # Page one should show 2 personas.
        r = self.client.get(self.url, follow=True)
        assert r.status_code == 200
        assert pq(r.content)('.personas-grid li').length == 2

        # Page two should show 1 persona.
        r = self.client.get(self.url + '&page=2', follow=True)
        assert r.status_code == 200
        assert pq(r.content)('.personas-grid li').length == 1


@pytest.mark.parametrize("test_input,expected", [
    ('q=yeah&sort=newest', 'q=yeah&sort=updated'),
    ('sort=weeklydownloads', 'sort=users'),
    ('sort=averagerating', 'sort=rating'),
    ('lver=5.*', 'appver=5.*'),
    ('q=woo&sort=averagerating&lver=6.0', 'q=woo&sort=rating&appver=6.0'),
    ('pid=2', 'platform=linux'),
    ('q=woo&lver=6.0&sort=users&pid=5',
     'q=woo&appver=6.0&sort=users&platform=windows'),
    ('type=extension', 'atype=1'),
    ('type=dictionary', 'atype=3'),
    ('type=search', 'atype=4'),
    ('type=language', 'atype=5'),
])
def test_search_redirects(test_input, expected):
    assert views.fix_search_query(QueryDict(test_input)) == (
        dict(urlparse.parse_qsl(expected)))


@pytest.mark.parametrize("test_input", [
    'q=yeah',
    'q=yeah&sort=users',
    'sort=users',
    'q=yeah&appver=6.0',
    'q=yeah&appver=6.0&platform=mac',
])
def test_search_redirects2(test_input):
    q = QueryDict(test_input)
    assert views.fix_search_query(q) is q


class TestAjaxSearch(ESTestCaseWithAddons):

    def search_addons(self, url, params, addons=None, types=amo.ADDON_TYPES,
                      src=None):
        if addons is None:
            addons = []
        response = self.client.get(url + '?' + params)
        assert response.status_code == 200
        data = json.loads(response.content)

        assert len(data) == len(addons)
        for got, expected in zip(
                sorted(data, key=lambda x: x['id']),
                sorted(addons, key=lambda x: x.id)):
            expected.reload()
            assert int(got['id']) == expected.id
            assert got['name'] == unicode(expected.name)
            expected_url = expected.get_url_path()
            if src:
                expected_url += '?src=ss'
            assert got['url'] == expected_url
            assert got['icons'] == {'32': expected.get_icon_url(32),
                                    '64': expected.get_icon_url(64)}

            assert expected.status in amo.REVIEWED_STATUSES, (
                'Unreviewed add-ons should not appear in search results.')
            assert not expected.is_disabled
            assert expected.type in types, (
                'Add-on type %s should not be searchable.' % expected.type)
        return data


class TestGenericAjaxSearch(TestAjaxSearch):

    def search_addons(self, params, addons=None):
        if addons is None:
            addons = []
        [a.save() for a in Addon.objects.all()]
        self.refresh()
        return super(TestGenericAjaxSearch, self).search_addons(
            reverse('search.ajax'), params, addons)

    def test_ajax_search_by_id(self):
        addon = Addon.objects.public().all()[0]
        self.search_addons('q=%s' % addon.id, [addon])

    def test_ajax_search_by_bad_id(self):
        self.search_addons('q=999', [])

    def test_ajax_search_nominated_by_id(self):
        addon = Addon.objects.all()[3]
        addon.update(status=amo.STATUS_NOMINATED)
        self.search_addons('q=999', [])

    def test_ajax_search_user_disabled_by_id(self):
        addon = Addon.objects.filter(disabled_by_user=True)[0]
        self.search_addons('q=%s' % addon.id, [])

    def test_ajax_search_admin_disabled_by_id(self):
        addon = Addon.objects.filter(status=amo.STATUS_DISABLED)[0]
        self.search_addons('q=%s' % addon.id, [])

    def test_ajax_search_admin_deleted_by_id(self):
        self._addons.append(amo.tests.addon_factory(status=amo.STATUS_DELETED))
        self.refresh()
        addon = Addon.unfiltered.filter(status=amo.STATUS_DELETED)[0]
        self.search_addons('q=%s' % addon.id, [])

    def test_ajax_search_personas_by_id(self):
        addon = Addon.objects.all()[3]
        addon.update(type=amo.ADDON_PERSONA)
        addon.update(status=amo.STATUS_PUBLIC)
        Persona.objects.create(persona_id=addon.id, addon_id=addon.id)
        self.search_addons('q=%s' % addon.id, [addon])

    def test_ajax_search_by_name(self):
        addon = amo.tests.addon_factory(
            name='uniqueaddon',
            status=amo.STATUS_PUBLIC,
            type=amo.ADDON_EXTENSION,
        )
        self._addons.append(addon)
        self.refresh()
        self.search_addons('q=' + unicode(addon.name), [addon])

    def test_ajax_search_by_bad_name(self):
        self.search_addons('q=some+filthy+bad+word', [])

    def test_basic_search(self):
        public_addons = Addon.objects.public().all()
        self.search_addons('q=addon', public_addons)

    def test_webextension_boost(self):
        public_addons = Addon.objects.public().all()
        web_extension = public_addons.order_by('name')[0]
        web_extension.current_version.files.update(is_webextension=True)
        web_extension.save()
        self.refresh()

        data = self.search_addons('q=Addon', public_addons)
        assert int(data[0]['id']) != web_extension.id

        create_switch('boost-webextensions-in-search')
        # The boost chosen should have made that addon the first one.
        data = self.search_addons('q=Addon', public_addons)
        assert int(data[0]['id']) == web_extension.id


class TestSearchSuggestions(TestAjaxSearch):

    def setUp(self):
        super(TestSearchSuggestions, self).setUp()
        self.url = reverse('search.suggestions')
        self._addons += [
            amo.tests.addon_factory(name='addon persona',
                                    type=amo.ADDON_PERSONA),
            amo.tests.addon_factory(name='addon persona',
                                    type=amo.ADDON_PERSONA,
                                    disabled_by_user=True,
                                    status=amo.STATUS_NULL),
        ]
        self.refresh()

    def search_addons(self, params, addons=None,
                      types=views.AddonSuggestionsAjax.types):
        return super(TestSearchSuggestions, self).search_addons(
            self.url, params, addons, types, src='ss')

    def search_applications(self, params, apps=None):
        if apps is None:
            apps = []
        response = self.client.get(self.url + '?' + params)
        assert response.status_code == 200
        data = json.loads(response.content)

        data = sorted(data, key=lambda x: x['id'])
        apps = sorted(apps, key=lambda x: x.id)

        assert len(data) == len(apps)
        for got, expected in zip(data, apps):
            assert int(got['id']) == expected.id
            assert got['name'] == '%s Add-ons' % unicode(expected.pretty)
            assert got['url'] == locale_url(expected.short)
            assert got['cls'] == 'app ' + expected.short

    def test_get(self):
        r = self.client.get(self.url)
        assert r.status_code == 200

    def test_addons(self):
        addons = (Addon.objects.public()
                  .filter(disabled_by_user=False,
                          type__in=views.AddonSuggestionsAjax.types))
        self.search_addons('q=add', list(addons))
        self.search_addons('q=add&cat=all', list(addons))

    def test_unicode(self):
        self.search_addons('q=%C2%B2%C2%B2', [])

    def test_personas(self):
        personas = (Addon.objects.public()
                    .filter(type=amo.ADDON_PERSONA, disabled_by_user=False))
        personas, types = list(personas), [amo.ADDON_PERSONA]
        self.search_addons('q=add&cat=themes', personas, types)
        self.search_addons('q=persona&cat=themes', personas, types)
        self.search_addons('q=PERSONA&cat=themes', personas, types)
        self.search_addons('q=persona&cat=all', [])

    def test_applications(self):
        self.search_applications('', [])
        self.search_applications('q=FIREFOX', [amo.FIREFOX, amo.ANDROID])
        self.search_applications('q=firefox', [amo.FIREFOX, amo.ANDROID])
        self.search_applications('q=bird', [amo.THUNDERBIRD])
        self.search_applications('q=mozilla', [])
