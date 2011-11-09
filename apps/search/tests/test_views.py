# -*- coding: utf8 -*-
import json
import urlparse

from django.http import QueryDict
from django.test import client

from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.helpers import locale_url, urlparams
from amo.urlresolvers import reverse
from addons.models import Addon, AddonCategory, Category, Persona
from search import views
from search.tests import SphinxTestCase
from search.utils import floor_version
from tags.models import Tag
from versions.models import ApplicationsVersions


def test_parse_bad_type():
    """
    Given a type that doesn't exist, we should not throw a KeyError.

    Note: This does not require sphinx to be running.
    """
    c = client.Client()
    try:
        c.get("/en-US/firefox/api/1.2/search/firebug%20type:dict")
    except KeyError:  # pragma: no cover
        assert False, ("We should not throw a KeyError just because we had a "
                       "nonexistent addon type.")


class ViewTest(amo.tests.TestCase):
    """Tests some of the functions used in building the view."""

    fixtures = ('base/category',)

    def setUp(self):
        self.fake_request = Mock()
        self.fake_request.get_full_path = lambda: 'http://fatgir.ls/'

    def test_get_categories(self):
        cats = Category.objects.all()
        cat = cats[0].id

        # Select a category.
        items = views._get_categories(self.fake_request, cats, category=cat)
        eq_(len(cats), len(items[1].children))
        assert any((i.selected for i in items[1].children))

        # Select an addon type.
        atype = cats[0].type
        items = views._get_categories(self.fake_request, cats,
                                      addon_type=atype)
        assert any((i.selected for i in items))

    def test_get_tags(self):
        t = Tag(tag_text='yermom')
        assert views._get_tags(self.fake_request, tags=[t], selected='yermom')


class TestAdminDisabledAddons(SphinxTestCase):
    fixtures = ('base/addon_3615',)

    def setUp(self):
        Addon.objects.get(pk=3615).update(status=amo.STATUS_DISABLED)
        super(TestAdminDisabledAddons, self).setUp()


class TestSearchboxTarget(amo.tests.TestCase):
    # Check that we search within addons/personas/collections as appropriate.

    def check(self, url, placeholder, cat):
        doc = pq(self.client.get(url).content)('.header-search form')
        eq_(doc('input[name=q]').attr('placeholder'), placeholder)
        eq_(doc('input[name=cat]').val(), cat)

    def test_addons_is_default(self):
        self.check(reverse('home'), 'search for add-ons', 'all')

    def test_themes(self):
        self.check(reverse('browse.themes'), 'search for add-ons',
                   '%s,0' % amo.ADDON_THEME)

    def test_collections(self):
        self.check(reverse('collections.list'), 'search for collections',
                   'collections')

    def test_personas(self):
        self.check(reverse('browse.personas'), 'search for personas',
                   'personas')


class TestESSearch(amo.tests.ESTestCase):
    fixtures = ['base/apps', 'base/category', 'tags/tags']

    @classmethod
    def setUpClass(cls):
        super(TestESSearch, cls).setUpClass()
        cls.setUpIndex()

    def setUp(self):
        self.url = reverse('search.search')
        self.search_views = ('search.search', 'apps.search')
        addons = Addon.objects.filter(status=amo.STATUS_PUBLIC,
                                      disabled_by_user=False)
        for addon in addons:
            AddonCategory.objects.create(addon=addon, category_id=1)
        self.refresh()

    def test_get(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        assert 'X-PJAX' in r['vary'].split(','), (
            'Expected "Vary: X-PJAX" header')
        self.assertTemplateUsed(r, 'search/results.html')

    @amo.tests.mobile_test
    def test_mobile_results(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/mobile/results.html')

    def check_sort_links(self, key, title, sort_by=None, reverse=True):
        r = self.client.get('%s?sort=%s' % (self.url, key))
        eq_(r.status_code, 200)
        menu = pq(r.content)('#sort-menu')
        eq_(menu.find('span').text(), title)
        eq_(menu.find('li.selected').text(), title)
        if sort_by:
            a = r.context['pager'].object_list
            eq_(list(a),
                sorted(a, key=lambda x: getattr(x, sort_by), reverse=reverse))

    @amo.tests.mobile_test
    def test_mobile_results_sort_default(self):
        self.check_sort_links('relevance', 'Relevance', 'weekly_downloads')

    @amo.tests.mobile_test
    def test_mobile_results_sort_relevance(self):
        self.check_sort_links('relevance', 'Relevance')

    @amo.tests.mobile_test
    def test_mobile_results_sort_users(self):
        self.check_sort_links('users', 'Most Users', 'average_daily_users')

    @amo.tests.mobile_test
    def test_mobile_results_sort_rating(self):
        self.check_sort_links('rating', 'Top Rated', 'bayesian_rating')

    @amo.tests.mobile_test
    def test_mobile_results_sort_newest(self):
        self.check_sort_links('created', 'Newest', 'created')

    @amo.tests.mobile_test
    def test_mobile_results_sort_unknown(self):
        self.check_sort_links('updated', 'Relevance')

    def test_legacy_redirects(self):
        r = self.client.get(self.url + '?sort=averagerating')
        self.assertRedirects(r, self.url + '?sort=rating', status_code=301)

    def check_platform_filters(self, platform, expected=None):
        r = self.client.get('%s?platform=%s' % (self.url, platform),
                            follow=True)
        plats = r.context['platforms']
        for idx, plat in enumerate(plats):
            name, selected = expected[idx]
            label = unicode(plat.text)
            assert label == name, (
                '%r platform had the wrong label: %s' % (platform, label))
            assert plat.selected == selected, (
                '%r platform should have been selected' % platform)

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
        self.check_platform_filters('xxx', expected)
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

        expected = [
            ('All Systems', False),
            ('Linux', False),
            ('Mac OS X', False),
            ('Windows', False),
            ('Maemo', True),
        ]
        self.check_platform_filters('maemo', expected)

    def test_platform_legacy_params(self):
        ALL = (amo.PLATFORM_ALL, amo.PLATFORM_ANY, amo.PLATFORM_ALL_MOBILE)
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

    def check_appver_filters(self, appver='', expected=''):
        if not expected:
            expected = appver
        r = self.client.get('%s?appver=%s' % (self.url, appver))

        vs = list(ApplicationsVersions.objects.values_list(
            'max__version', flat=True).distinct())
        try:
            if expected not in vs and float(floor_version(expected)):
                vs.append(expected)
        except ValueError:
            pass
        vs = [float(floor_version(v)) for v in vs]

        ul = pq(r.content)('#search-facets ul.facet-group').eq(1)

        app = unicode(r.context['request'].APP.pretty)
        eq_(r.context['query']['appver'], expected)
        all_ = r.context['versions'].pop(0)
        eq_(all_.text, 'Any %s' % app)
        eq_(all_.selected, not expected)
        eq_(json.loads(ul.find('a:first').attr('data-params')),
            dict(appver='', page=None))

        for label, av in zip(r.context['versions'], sorted(vs, reverse=True)):
            av = str(av)
            eq_(label.text, '%s %s' % (app, av))
            eq_(label.selected, expected == av)
            a = ul.find('a').filter(lambda x: pq(this).text() == label.text)
            eq_(json.loads(a.attr('data-params')), dict(appver=av, page=None))

    def test_appver_default(self):
        self.check_appver_filters()

    def test_appver_known(self):
        self.check_appver_filters('5.0')

    def test_appver_oddballs(self):
        self.check_appver_filters('3', '3.0')
        self.check_appver_filters('3.6')
        self.check_appver_filters('3.6.22', '3.6')
        self.check_appver_filters('5.0a2', '5.0')
        self.check_appver_filters('8.0')
        self.check_appver_filters('8.0.10a', '8.0')
        self.check_appver_filters('10.0b2pre', '10.0')
        self.check_appver_filters('8.*', '8.0')
        self.check_appver_filters('8.0*', '8.0')
        self.check_appver_filters('8.0.*', '8.0')
        self.check_appver_filters('8.x', '8.0')
        self.check_appver_filters('8.0x', '8.0')
        self.check_appver_filters('8.0.x', '8.0')

    def test_appver_bad(self):
        self.check_appver_filters('.')
        self.check_appver_filters('_')
        self.check_appver_filters('x.x')
        self.check_appver_filters('y.y')

    def test_non_pjax_results(self):
        # These context variables should exist for normal requests.
        expected_context_vars = {
            'search.search': ('categories', 'platforms', 'versions', 'tags'),
            'apps.search': ('categories', 'tags'),
        }

        for view in self.search_views:
            r = self.client.get(reverse(view))
            eq_(r.status_code, 200)
            eq_(r.context['is_pjax'], None)

            for var in expected_context_vars[view]:
                assert var in r.context, (
                    '%r missing context var in view %r' % (var, view))

            doc = pq(r.content)
            eq_(doc('html').length, 1)
            eq_(doc('#pjax-results').length, 1)
            eq_(doc('#search-facets .facets.pjax-trigger').length, 1)
            eq_(doc('#sorter.pjax-trigger').length, 1)

    def test_pjax_results(self):
        for view in self.search_views:
            r = self.client.get(reverse(view), HTTP_X_PJAX=True)
            eq_(r.status_code, 200)
            eq_(r.context['is_pjax'], True)

            doc = pq(r.content)
            eq_(doc('html').length, 0)
            eq_(doc('#pjax-results').length, 0)
            eq_(doc('#search-facets .facets.pjax-trigger').length, 0)
            eq_(doc('#sorter.pjax-trigger').length, 1)

    def test_facet_data_params_default(self):
        r = self.client.get(self.url)
        a = pq(r.content)('#search-facets a[data-params]:first')
        eq_(json.loads(a.attr('data-params')),
            dict(atype=None, cat=None, page=None))

    def test_facet_data_params_filtered(self):
        r = self.client.get(self.url + '?appver=3.6&platform=mac&page=3')
        a = pq(r.content)('#search-facets a[data-params]:first')
        eq_(json.loads(a.attr('data-params')),
            dict(atype=None, cat=None, page=None))

    def check_cat_filters(self, params=None):
        if not params:
            params = {}

        r = self.client.get(self.url)
        pager = r.context['pager']

        r = self.client.get(urlparams(self.url, **params))
        a = pq(r.content)('#category-facets li.selected a')
        eq_(a.length, 1)
        eq_(a.text(), 'All Add-ons')
        eq_(list(r.context['pager'].object_list), list(pager.object_list))

    def test_defaults_atype_no_cat(self):
        self.check_cat_filters(dict(atype=1))

    def test_defaults_atype_unknown_cat(self):
        self.check_cat_filters(dict(atype=1, cat=999))

    def test_defaults_no_atype_unknown_cat(self):
        self.check_cat_filters(dict(cat=999))

    def test_defaults_atype_foreign_cat(self):
        cat = Category.objects.create(application_id=amo.THUNDERBIRD.id,
                                      type=amo.ADDON_EXTENSION)
        self.check_cat_filters(dict(atype=1, cat=cat.id))

    def test_no_tag_filter(self):
        r = self.client.get(self.url)
        a = pq(r.content)('#tag-facets li.selected a')
        eq_(a.length, 1)
        eq_(a.text(), 'All Tags')
        assert list(r.context['pager'].object_list), 'Expected results'

    def test_unknown_tag_filter(self):
        r = self.client.get(urlparams(self.url, tag='xxx'))
        a = pq(r.content)('#tag-facets li.selected a')
        eq_(a.length, 1)
        eq_(a.text(), 'xxx')
        eq_(list(r.context['pager'].object_list), [])

    def test_known_tag_filter(self):
        for url in (urlparams(self.url, tag='sky'),
                    reverse('tags.detail', args=['sky'])):
            r = self.client.get(url)
            a = pq(r.content)('#tag-facets li.selected a[data-params]')
            eq_(json.loads(a.attr('data-params')), dict(tag='sky', page=None))

    def test_tag_titles(self):
        tag_url = reverse('tags.detail', args=['sky'])

        titles = {
            tag_url: (
                'sky :: Tag :: Add-ons for Firefox',
                'Search Results for tag "sky"',
            ),
            urlparams(tag_url, q='sky'): (
                'sky :: Search :: Add-ons for Firefox',
                'Search Results for "sky"',
            ),
            urlparams(self.url, tag='sky'): (
                'Search :: Add-ons for Firefox',
                'Search',
            )
        }

        for url, titles in titles.iteritems():
            r = self.client.get(url)
            doc = pq(r.content)
            title, heading = titles
            eq_(doc('title').text(), title)
            eq_(doc('.primary h1').text(), heading)


def test_search_redirects():
    changes = (
        ('q=yeah&sort=newest', 'q=yeah&sort=updated'),
        ('sort=weeklydownloads', 'sort=users'),
        ('sort=averagerating', 'sort=rating'),
        ('lver=5.*', 'appver=5.*'),
        ('q=woo&sort=averagerating&lver=6.0', 'q=woo&sort=rating&appver=6.0'),
        ('pid=2', 'platform=linux'),
        ('q=woo&lver=6.0&sort=users&pid=5',
         'q=woo&appver=6.0&sort=users&platform=windows'),
    )

    def check(before, after):
        eq_(views.fix_search_query(QueryDict(before)),
            dict(urlparse.parse_qsl(after)))
    for before, after in changes:
        yield check, before, after

    queries = (
        'q=yeah',
        'q=yeah&sort=users',
        'sort=users',
        'q=yeah&appver=6.0',
        'q=yeah&appver=6.0&platform=mac',
    )

    def same(qs):
        q = QueryDict(qs)
        assert views.fix_search_query(q) is q
    for qs in queries:
        yield same, qs


class TestWebappSearch(amo.tests.ESTestCase):

    def setUp(self):
        self.url = reverse('apps.search')

    def test_get(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        assert 'X-PJAX' in r['vary'].split(','), (
            'Expected "Vary: X-PJAX" header')
        self.assertTemplateUsed(r, 'search/results.html')

    @amo.tests.mobile_test
    def test_mobile_get(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/mobile/results.html')

    def test_no_compat_facets(self):
        assert not pq(self.client.get(self.url).content)('#compat-facets')


class TestAjaxSearch(amo.tests.ESTestCase):

    @classmethod
    def setUpClass(cls):
        super(TestAjaxSearch, cls).setUpClass()
        cls.setUpIndex()

    def search_addons(self, url, params, addons=[],
                      types=amo.ADDON_SEARCH_TYPES, src=None):
        r = self.client.get('?'.join([url, params]))
        eq_(r.status_code, 200)
        data = json.loads(r.content)

        data = sorted(data, key=lambda x: x['id'])
        addons = sorted(addons, key=lambda x: x.id)

        eq_(len(data), len(addons))
        for got, expected in zip(data, addons):
            eq_(int(got['id']), expected.id)
            eq_(got['name'], unicode(expected.name))
            expected_url = expected.get_url_path()
            if src:
                expected_url += '?src=ss'
            eq_(got['url'], expected_url)
            eq_(got['icon'], expected.icon_url)

            assert expected.status in amo.REVIEWED_STATUSES, (
                'Unreviewed add-ons should not appear in search results.')
            eq_(expected.is_disabled, False)
            assert expected.type in types, (
                'Add-on type %s should not be searchable.' % expected.type)


class TestBaseAjaxSearch(TestAjaxSearch):

    def search_addons(self, params, addons=[]):
        self.refresh()
        super(TestBaseAjaxSearch, self).search_addons(
            reverse('search.ajax'), params, addons)

    def test_ajax_search_by_id(self):
        addon = Addon.objects.reviewed().all()[0]
        self.search_addons('q=%s' % addon.id, [addon])

    def test_ajax_search_by_bad_id(self):
        self.search_addons('q=999', [])

    def test_ajax_search_unreviewed_by_id(self):
        addon = Addon.objects.all()[3]
        addon.update(status=amo.STATUS_UNREVIEWED)
        self.search_addons('q=999', [])

    def test_ajax_search_lite_reviewed_by_id(self):
        addon = Addon.objects.all()[3]
        addon.update(status=amo.STATUS_LITE)
        q = 'q=%s' % addon.id
        self.search_addons(q, [addon])

        addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.search_addons(q, [addon])

    def test_ajax_search_user_disabled_by_id(self):
        addon = Addon.objects.filter(disabled_by_user=True)[0]
        self.search_addons('q=%s' % addon.id, [])

    def test_ajax_search_admin_disabled_by_id(self):
        addon = Addon.objects.filter(status=amo.STATUS_DISABLED)[0]
        self.search_addons('q=%s' % addon.id, [])

    def test_ajax_search_personas_by_id(self):
        addon = Addon.objects.all()[3]
        addon.update(type=amo.ADDON_PERSONA)
        Persona.objects.create(persona_id=addon.id, addon_id=addon.id)
        self.search_addons('q=%s' % addon.id, [addon])

    def test_ajax_search_char_limit(self):
        self.search_addons('q=ad', [])

    def test_ajax_search_by_name(self):
        from nose import SkipTest
        raise SkipTest
        self.search_addons('q=add', list(Addon.objects.reviewed()))

    def test_ajax_search_by_bad_name(self):
        self.search_addons('q=some+filthy+bad+word', [])


class TestSearchSuggestions(TestAjaxSearch):

    def setUp(self):
        self.url = reverse('search.suggestions')
        amo.tests.addon_factory(name='addon webapp', type=amo.ADDON_WEBAPP)
        amo.tests.addon_factory(name='addon persona', type=amo.ADDON_PERSONA)
        amo.tests.addon_factory(name='addon persona', type=amo.ADDON_PERSONA,
                                disabled_by_user=True, status=amo.STATUS_NULL)
        self.refresh()

    def search_addons(self, params, addons=[],
                          types=views.AddonSuggestionsAjax.types):
        super(TestSearchSuggestions, self).search_addons(
            self.url, params, addons, types, src='ss')

    def search_applications(self, params, apps=[]):
        r = self.client.get('?'.join([self.url, params]))
        eq_(r.status_code, 200)
        data = json.loads(r.content)

        data = sorted(data, key=lambda x: x['id'])
        apps = sorted(apps, key=lambda x: x.id)

        eq_(len(data), len(apps))
        for got, expected in zip(data, apps):
            eq_(int(got['id']), expected.id)
            eq_(got['name'], '%s Add-ons' % unicode(expected.pretty))
            eq_(got['url'], locale_url(expected.short))
            eq_(got['cls'], 'app ' + expected.short)

    def test_get(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_addons(self):
        addons = (Addon.objects.reviewed()
                  .filter(disabled_by_user=False,
                          type__in=views.AddonSuggestionsAjax.types))
        self.search_addons('q=add', list(addons))
        self.search_addons('q=add&cat=all', list(addons))

    def test_personas(self):
        personas = (Addon.objects.reviewed()
                    .filter(type=amo.ADDON_PERSONA, disabled_by_user=False))
        personas, types = list(personas), [amo.ADDON_PERSONA]
        self.search_addons('q=add&cat=personas', personas, types)
        self.search_addons('q=persona&cat=personas', personas, types)
        self.search_addons('q=PERSONA&cat=personas', personas, types)
        self.search_addons('q=persona&cat=all', [])

    def test_webapps(self):
        apps = list(Addon.objects.reviewed()
                    .filter(type=amo.ADDON_WEBAPP, disabled_by_user=False))
        types = [amo.ADDON_WEBAPP]
        self.search_addons('q=add&cat=apps', apps, types)
        self.search_addons('q=WEBAPP&cat=apps', apps, types)

    def test_applications(self):
        self.search_applications('', [])
        self.search_applications('q=FIREFOX', [amo.FIREFOX])
        self.search_applications('q=firefox', [amo.FIREFOX])
        self.search_applications('q=thunder', [amo.THUNDERBIRD])
        self.search_applications('q=monkey', [amo.SEAMONKEY])
        self.search_applications('q=sun', [amo.SUNBIRD])
        self.search_applications('q=bird', [amo.THUNDERBIRD, amo.SUNBIRD])
        self.search_applications('q=mobile', [amo.MOBILE])
        self.search_applications('q=mozilla', [])
