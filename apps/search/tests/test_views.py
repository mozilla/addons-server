# -*- coding: utf-8 -*-
import json
import urlparse

from django.http import QueryDict

from jingo.helpers import datetime as datetime_filter
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
from tower import strip_whitespace

import amo
import amo.tests
from amo.helpers import locale_url, numberfmt, urlparams
from amo.urlresolvers import reverse
from addons.models import Addon, AddonCategory, AddonUser, Category, Persona
from search import views
from search.utils import floor_version
from search.views import DEFAULT_NUM_PERSONAS
from users.models import UserProfile
from versions.compare import num as vnum, version_int as vint, MAXVERSION
from versions.models import ApplicationsVersions


class TestSearchboxTarget(amo.tests.ESTestCase):

    @classmethod
    def setUpClass(cls):
        super(TestSearchboxTarget, cls).setUpClass()
        cls.setUpIndex()

    def check(self, url, placeholder, cat=None, action=None, q=None):
        # Checks that we search within addons, personas, collections, etc.
        form = pq(self.client.get(url).content)('.header-search form')
        eq_(form.attr('action'), action or reverse('search.search'))
        if cat:
            eq_(form('input[name=cat]').val(), cat)
        q_field = form('input[name=q]')
        eq_(q_field.attr('placeholder'), placeholder)
        if q:
            eq_(q_field.val(), q)

    def test_addons_is_default(self):
        self.check(reverse('home'), 'search for add-ons')

    def test_themes(self):
        self.check(reverse('browse.themes'), 'search for add-ons',
                   '%s,0' % amo.ADDON_THEME)

    def test_collections(self):
        self.check(reverse('collections.list'), 'search for collections',
                   'collections')

    def test_personas(self):
        self.check(reverse('browse.personas'), 'search for personas',
                   'personas')

    def test_addons_search(self):
        self.check(reverse('search.search'), 'search for add-ons')

    def test_addons_search_term(self):
        self.check(reverse('search.search') + '?q=ballin',
                   'search for add-ons', q='ballin')


class SearchBase(amo.tests.ESTestCase):

    def get_results(self, r, sort=True):
        """Return pks of add-ons shown on search results page."""
        results = [a.id for a in r.context['pager'].object_list]
        if sort:
            results = sorted(results)
        return results

    def check_sort_links(self, key, title=None, sort_by=None, reverse=True,
                         params={}):
        r = self.client.get(urlparams(self.url, sort=key, **params))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        if title:
            if hasattr(self, 'MOBILE'):
                menu = doc('#sort-menu')
                eq_(menu.find('span').text(), title)
                eq_(menu.find('.selected').text(), title)
            else:
                eq_(doc('#sorter .selected').text(), title)
        if sort_by:
            results = r.context['pager'].object_list
            if sort_by == 'name':
                expected = sorted(results, key=lambda x: unicode(x.name))
            else:
                expected = sorted(results, key=lambda x: getattr(x, sort_by),
                                  reverse=reverse)
            eq_(list(results), expected)

    def check_name_results(self, params, expected):
        r = self.client.get(urlparams(self.url, **params), follow=True)
        eq_(r.status_code, 200)
        got = self.get_results(r)
        eq_(got, expected,
            'Got: %s. Expected: %s. Parameters: %s' % (got, expected, params))

    def check_appver_platform_ignored(self, expected):
        # Collection results should not filter on `appver` nor `platform`.
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
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.results-count strong').text(), None)

        r = self.client.get(self.url + '&q=ballin')
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.results-count strong').text(), 'ballin')


class TestESSearch(SearchBase):
    fixtures = ['base/apps', 'base/category', 'tags/tags']

    @classmethod
    def setUpClass(cls):
        super(TestESSearch, cls).setUpClass()
        cls.setUpIndex()

    def setUp(self):
        self.url = reverse('search.search')
        self.addons = Addon.objects.filter(status=amo.STATUS_PUBLIC,
                                           disabled_by_user=False)
        for addon in self.addons:
            AddonCategory.objects.create(addon=addon, category_id=1)
            addon.save()
        self.refresh()

    def refresh_addons(self):
        [a.save() for a in Addon.objects.all()]
        self.refresh()

    def test_get(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        assert 'X-PJAX' in r['vary'].split(','), 'Expected "Vary: X-PJAX"'
        self.assertTemplateUsed(r, 'search/results.html')

    @amo.tests.mobile_test
    def test_get_mobile(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/mobile/results.html')

    @amo.tests.mobile_test
    def test_mobile_results_downloads(self):
        r = self.client.get(urlparams(self.url, sort='downloads'))
        assert pq(r.content)('#content .item .vital.downloads'), (
            'Expected weekly downloads')

    def test_search_tools_omit_users(self):
        r = self.client.get(self.url, dict(cat='%s,5' % amo.ADDON_SEARCH))
        eq_(r.status_code, 200)
        sorter = pq(r.content)('#sorter')
        eq_(sorter.length, 1)
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

    def test_mobile_results_sort_name(self):
        self.check_sort_links('name', 'Name', 'name', reverse=False)

    @amo.tests.mobile_test
    def test_mobile_results_sort_default(self):
        self.check_sort_links(None, 'Relevance', 'weekly_downloads')

    @amo.tests.mobile_test
    def test_mobile_results_sort_unknown(self):
        self.check_sort_links('xxx', 'Relevance')

    @amo.tests.mobile_test
    def test_mobile_results_sort_users(self):
        self.check_sort_links('users', 'Most Users', 'average_daily_users')

    @amo.tests.mobile_test
    def test_mobile_results_sort_rating(self):
        self.check_sort_links('rating', 'Top Rated', 'bayesian_rating')

    @amo.tests.mobile_test
    def test_mobile_results_sort_newest(self):
        self.check_sort_links('created', 'Newest', 'created')

    def test_legacy_redirects(self):
        r = self.client.get(self.url + '?sort=averagerating')
        self.assertRedirects(r, self.url + '?sort=rating', status_code=301)

    def test_legacy_redirects_to_non_ascii(self):
        # see http://sentry.dmz.phx1.mozilla.com/addons/group/2186/
        url = '/ga-IE/seamonkey/tag/%E5%95%86%E5%93%81%E6%90%9C%E7%B4%A2'
        from_ = ('?sort=updated&lver=1.0&advancedsearch=1'
                 '&tag=dearbhair&cat=4%2C84')
        to = ('?sort=updated&advancedsearch=1&appver=1.0'
              '&tag=dearbhair&cat=4%2C84')
        r = self.client.get(url + from_)
        self.assertRedirects(r, url + to, status_code=301)

    def check_platform_filters(self, platform, expected=None):
        r = self.client.get('%s?platform=%s' % (self.url, platform),
                            follow=True)
        plats = r.context['platforms']
        for idx, plat in enumerate(plats):
            name, selected = expected[idx]
            label = unicode(plat.text)
            eq_(label, name,
                '%r platform had the wrong label: %s' % (platform, label))
            eq_(plat.selected, selected,
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
        r = self.client.get(self.url, dict(appver=appver))
        eq_(r.status_code, 200)

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
        self.check_appver_filters('3.6.22', '3.6')

    def test_appver_long(self):
        too_big = vnum(vint(MAXVERSION + 1))
        just_right = vnum(vint(MAXVERSION))
        self.check_appver_filters(too_big, floor_version(just_right))
        self.check_appver_filters('9999999', '9999999.0')
        self.check_appver_filters('99999999', '99999999.0')

    def test_appver_bad(self):
        self.check_appver_filters('.')
        self.check_appver_filters('_')
        self.check_appver_filters('y.y')

    def test_non_pjax_results(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(r.context['is_pjax'], None)

        # These context variables should exist for normal requests.
        for var in ('categories', 'platforms', 'versions', 'tags'):
            assert var in r.context, '%r missing context var in view' % var

        doc = pq(r.content)
        eq_(doc('html').length, 1)
        eq_(doc('#pjax-results').length, 1)
        eq_(doc('#search-facets .facets.pjax-trigger').length, 1)
        eq_(doc('#sorter.pjax-trigger').length, 1)

    def test_pjax_results(self):
        r = self.client.get(self.url, HTTP_X_PJAX=True)
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

    def check_cat_filters(self, params=None, selected='All Add-ons'):
        if not params:
            params = {}

        r = self.client.get(urlparams(self.url, **params))
        eq_(sorted(a.id for a in self.addons),
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
        self.check_cat_filters(dict(atype=1))

    def test_defaults_atype_unknown_cat(self):
        self.check_cat_filters(dict(atype=amo.ADDON_EXTENSION, cat=999))

    def test_defaults_no_atype_unknown_cat(self):
        self.check_cat_filters(dict(cat=999))

    def test_defaults_atype_foreign_cat(self):
        cat = Category.objects.create(application_id=amo.THUNDERBIRD.id,
                                      type=amo.ADDON_EXTENSION)
        self.check_cat_filters(dict(atype=amo.ADDON_EXTENSION, cat=cat.id))

    def test_listed_cat(self):
        cat = self.addons[0].all_categories[0]
        self.check_cat_filters(dict(atype=amo.ADDON_EXTENSION, cat=cat.id),
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
        self.refresh_addons()

        r = self.client.get(self.url)
        amo.tests.check_links([('All Add-ons', self.url)],
                              pq(r.content)('#category-facets li a'),
                              verify=False)

    def test_unknown_tag_filter(self):
        r = self.client.get(urlparams(self.url, tag='xxx'))
        a = pq(r.content)('#tag-facets li.selected a')
        eq_(a.length, 1)
        eq_(a.text(), 'xxx')
        eq_(list(r.context['pager'].object_list), [])

    def test_tag_filters_on_search_page(self):
        r = self.client.get(self.url, dict(tag='sky'))
        a = pq(r.content)('#tag-facets li.selected a[data-params]')
        eq_(json.loads(a.attr('data-params')), dict(tag='sky', page=None))

    def test_no_tag_filters_on_tags_page(self):
        r = self.client.get(reverse('tags.detail', args=['sky']))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#tag-facets').length, 0)

    def get_results(self, r):
        """Return pks of add-ons shown on search results page."""
        pks = pq(r.content)('#pjax-results div[data-addon]')
        return sorted(int(pq(a).attr('data-addon')) for a in pks)

    def test_results_filtered_atype(self):
        theme = self.addons[0]
        theme.type = amo.ADDON_THEME
        theme.save()
        self.refresh_addons()

        themes = sorted(self.addons.filter(type=amo.ADDON_THEME)
                        .values_list('id', flat=True))
        eq_(themes, [theme.id])

        extensions = sorted(self.addons.filter(type=amo.ADDON_EXTENSION)
                            .values_list('id', flat=True))
        eq_(extensions, sorted(a.id for a in self.addons[1:]))

        # Extensions should show only extensions.
        r = self.client.get(self.url, dict(atype=amo.ADDON_EXTENSION))
        eq_(r.status_code, 200)
        eq_(self.get_results(r), extensions)

        # Themes should show only themes.
        r = self.client.get(self.url, dict(atype=amo.ADDON_THEME))
        eq_(r.status_code, 200)
        eq_(self.get_results(r), themes)

    def test_results_respect_appver_filtering(self):
        r = self.client.get(self.url, dict(appver='9.00'))
        eq_(self.get_results(r), [])

    def test_results_skip_appver_filtering_for_d2c(self):
        r = self.client.get(self.url, dict(appver='10.0a1'))
        eq_(self.get_results(r),
            sorted(self.addons.values_list('id', flat=True)))

    def test_results_respect_appver_filtering_for_non_extensions(self):
        self.addons.update(type=amo.ADDON_THEME)
        r = self.client.get(self.url, dict(appver='10.0a1',
                                           type=amo.ADDON_THEME))
        eq_(self.get_results(r),
            sorted(self.addons.values_list('id', flat=True)))

    def test_results_platform_filter_all(self):
        for platform in ('', 'all'):
            r = self.client.get(self.url, dict(platform=platform))
            eq_(self.get_results(r),
                sorted(self.addons.values_list('id', flat=True)))

    def test_slug_indexed(self):
        a = self.addons[0]

        r = self.client.get(self.url, dict(q='omgyes'))
        eq_(self.get_results(r), [])

        a.update(slug='omgyes')
        self.refresh()
        r = self.client.get(self.url, dict(q='omgyes'))
        eq_(self.get_results(r), [a.id])

    def test_authors_indexed(self):
        a = self.addons[0]

        r = self.client.get(self.url, dict(q='boop'))
        eq_(self.get_results(r), [])

        AddonUser.objects.create(addon=a,
            user=UserProfile.objects.create(username='boop'))
        AddonUser.objects.create(addon=a,
            user=UserProfile.objects.create(username='ponypet'))
        a.save()
        self.refresh()
        r = self.client.get(self.url, dict(q='garbage'))
        eq_(self.get_results(r), [])
        r = self.client.get(self.url, dict(q='boop'))
        eq_(self.get_results(r), [a.id])
        r = self.client.get(self.url, dict(q='pony'))
        eq_(self.get_results(r), [a.id])


class TestPersonaSearch(SearchBase):
    fixtures = ['base/apps']

    @classmethod
    def setUpClass(cls):
        super(TestPersonaSearch, cls).setUpClass()
        cls.setUpIndex()

    def setUp(self):
        self.url = urlparams(reverse('search.search'), atype=amo.ADDON_PERSONA)

    def _generate_personas(self):
        # Add some public personas.
        self.personas = []
        for status in amo.REVIEWED_STATUSES:
            self.personas.append(
                amo.tests.addon_factory(type=amo.ADDON_PERSONA, status=status))

        # Add some unreviewed personas.
        for status in set(amo.STATUS_CHOICES) - set(amo.REVIEWED_STATUSES):
            amo.tests.addon_factory(type=amo.ADDON_PERSONA, status=status)

        # Add a disabled persona.
        amo.tests.addon_factory(type=amo.ADDON_PERSONA, disabled_by_user=True)

        # NOTE: There are also some add-ons in `setUpIndex` for good measure.

        self.refresh()

    def test_sort_order_default(self):
        self._generate_personas()
        self.check_sort_links(None, sort_by='weekly_downloads')

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
        eq_(r.status_code, 200)
        eq_(self.get_results(r), personas_ids)
        doc = pq(r.content)
        eq_(doc('.personas-grid li').length, len(personas_ids))
        eq_(doc('.listing-footer').length, 0)

    def test_results_name_query(self):
        raise SkipTest
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
            amo.tests.addon_factory(name=name, type=amo.ADDON_PERSONA,
                                    popularity=popularity)
        self.refresh()

        # Japanese Tattoo should be the #1 most relevant result. Obviously.
        expected_name, expected_popularity = personas[2]
        for sort in ('downloads', 'popularity', 'users'):
            r = self.client.get(urlparams(self.url, q='japanese tattoo',
                                          sort=sort), follow=True)
            eq_(r.status_code, 200)
            results = list(r.context['pager'].object_list)
            first = results[0]
            eq_(unicode(first.name), expected_name,
                'Was not first result for %r. Results: %s' % (sort, results))
            eq_(first.persona.popularity, expected_popularity,
                'Incorrect popularity for %r. Got %r. Expected %r.' % (
                sort, first.persona.popularity, results))
            eq_(first.average_daily_users, expected_popularity,
                'Incorrect users for %r. Got %r. Expected %r.' % (
                sort, first.average_daily_users, results))
            eq_(first.weekly_downloads, expected_popularity,
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

    def test_pagination(self):
        # TODO: Figure out why ES wonks out when we index a plethora of junk.
        raise SkipTest

        # Generate some (22) personas to get us to two pages.
        left_to_add = DEFAULT_NUM_PERSONAS - len(self.personas) + 1
        for x in xrange(left_to_add):
            self.personas.append(
                amo.tests.addon_factory(type=amo.ADDON_PERSONA))
        self.refresh()

        # Page one should show 21 personas.
        r = self.client.get(self.url, follow=True)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.personas-grid li').length, DEFAULT_NUM_PERSONAS)

        # Page two should show 1 persona.
        r = self.client.get(self.url + '&page=2', follow=True)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.personas-grid li').length, 1)


class TestCollectionSearch(SearchBase):
    fixtures = ['base/apps']

    @classmethod
    def setUpClass(cls):
        # Set up the mapping.
        super(TestCollectionSearch, cls).setUpClass()

    def setUp(self):
        self.url = urlparams(reverse('search.search'), cat='collections')

    def _generate(self):
        # Add some public collections.
        self.collections = []
        for x in xrange(3):
            self.collections.append(
                amo.tests.collection_factory(name='Collection %s' % x))

        # Synchronized, favorites, and unlisted collections should be excluded.
        for type_ in (amo.COLLECTION_SYNCHRONIZED, amo.COLLECTION_FAVORITES):
            amo.tests.collection_factory(type=type_)
        amo.tests.collection_factory(listed=False)

        self.refresh()

    def test_legacy_redirect(self):
        # Ensure `sort=newest` redirects to `sort=created`.
        r = self.client.get(urlparams(self.url, sort='newest'))
        self.assertRedirects(r, urlparams(self.url, sort='created'), 301)

    def test_sort_order_unknown(self):
        self._generate()
        self.check_sort_links('xxx')

    def test_sort_order_default(self):
        self._generate()
        self.check_sort_links(None, sort_by='weekly_subscribers')

    def test_sort_order_weekly(self):
        self._generate()
        self.check_sort_links('weekly', sort_by='weekly_subscribers')

    def test_sort_order_default_with_term(self):
        self._generate()
        self.check_sort_links(None, sort_by='weekly_subscribers',
                              params={'q': 'collection'})

    def test_sort_order_weekly_with_term(self):
        self._generate()
        self.check_sort_links('weekly', sort_by='weekly_subscribers',
                              params={'q': 'collection'})

    def test_sort_order_monthly(self):
        self._generate()
        self.check_sort_links('monthly', sort_by='monthly_subscribers')

    def test_sort_order_all(self):
        self._generate()
        self.check_sort_links('all', sort_by='subscribers')

    def test_sort_order_rating(self):
        self._generate()
        self.check_sort_links('rating', sort_by='rating')

    def test_sort_order_name(self):
        self._generate()
        self.check_sort_links('name', sort_by='name', reverse=False)

    def test_sort_order_created(self):
        self._generate()
        self.check_sort_links('created', sort_by='created')

    def test_sort_order_updated(self):
        self._generate()
        self.check_sort_links('updated', sort_by='modified')

    def test_created_timestamp(self):
        self._generate()
        r = self.client.get(urlparams(self.url, sort='created'))
        items = pq(r.content)('.primary .item')
        for idx, c in enumerate(r.context['pager'].object_list):
            eq_(strip_whitespace(items.eq(idx).find('.modified').text()),
                'Added %s' % strip_whitespace(datetime_filter(c.created)))

    def test_updated_timestamp(self):
        self._generate()
        r = self.client.get(urlparams(self.url, sort='updated'))
        items = pq(r.content)('.primary .item')
        for idx, c in enumerate(r.context['pager'].object_list):
            eq_(strip_whitespace(items.eq(idx).find('.modified').text()),
                'Updated %s' % strip_whitespace(datetime_filter(c.modified)))

    def check_followers_count(self, sort, column):
        # Checks that we show the correct type/number of followers.
        r = self.client.get(urlparams(self.url, sort=sort))
        items = pq(r.content)('.primary .item')
        for idx, c in enumerate(r.context['pager'].object_list):
            eq_(items.eq(idx).find('.followers').text().split()[0],
                numberfmt(getattr(c, column)))

    def test_followers_all(self):
        self._generate()
        for sort in ('', 'all', 'rating', 'created', 'modified', 'name'):
            self.check_followers_count(sort, column='subscribers')

    def test_followers_monthly(self):
        self._generate()
        self.check_followers_count('monthly', column='monthly_subscribers')

    def test_followers_weekly(self):
        self._generate()
        self.check_followers_count('weekly', column='weekly_subscribers')

    def test_heading(self):
        # One is a lonely number. But that's all we need.
        amo.tests.collection_factory()
        self.check_heading()

    def test_results_blank_query(self):
        self._generate()
        collection_ids = sorted(p.id for p in self.collections)
        r = self.client.get(self.url, follow=True)
        eq_(r.status_code, 200)
        eq_(self.get_results(r), collection_ids)
        doc = pq(r.content)
        eq_(doc('.primary .item').length, len(collection_ids))
        eq_(doc('.listing-footer').length, 0)

    def test_results_name_query(self):
        # TODO: Figure out why this flakes out on jenkins every so often.
        raise SkipTest

        self._generate()

        c1 = self.collections[0]
        c1.name = 'SeaVans: A Collection of Cars at the Beach'
        c1.save()

        c2 = self.collections[1]
        c2.name = 'The Life Aquatic with SeaVan: An Underwater Collection'
        c2.save()

        self.refresh()

        # These contain terms that are in every result - so return everything.
        for term in ('', 'collection',
                     'seavan: a collection of cars at the beach'):
            self.check_name_results({}, sorted(p.id for p in self.collections))

        # Garbage search terms should return nothing.
        for term in ('xxx', 'garbage', '£'):
            self.check_name_results({'q': term}, [])

        # Try to match 'SeaVans: A Collection of Cars at the Beach'.
        for term in ('cars', 'beach'):
            self.check_name_results({'q': term}, [c1.pk])

        # Match 'The Life Aquatic with SeaVan: An Underwater Collection'.
        for term in ('life aquatic', 'life', 'aquatic', 'underwater', 'under'):
            self.check_name_results({'q': term}, [c2.pk])

        # Match both results above.
        for term in ('seavan', 'seavans', 'sea van'):
            self.check_name_results({'q': term}, sorted([c1.pk, c2.pk]))

    def test_results_popularity(self):
        collections = [
            ('Traveler Pack', 2000),
            ('Tools for Developer', 67),
            ('Web Developer', 250),
            ('Web Developer Necessities', 50),
            ('Web Pro', 200),
            ('Web Developer Pack', 242),
        ]
        for name, subscribers in collections:
            amo.tests.collection_factory(name=name, subscribers=subscribers,
                                         weekly_subscribers=subscribers)
        self.refresh()

        # "Web Developer Collection" should be the #1 most relevant result.
        expected_name, expected_subscribers = collections[2]
        for sort in ('', 'all'):
            r = self.client.get(urlparams(self.url, q='web developer',
                                          sort=sort), follow=True)
            eq_(r.status_code, 200)
            results = list(r.context['pager'].object_list)
            first = results[0]
            eq_(unicode(first.name), expected_name,
                'Was not first result for %r. Results: %s' % (sort, results))
            eq_(first.subscribers, expected_subscribers,
                'Incorrect subscribers for %r. Got %r. Expected %r.' % (
                sort, first.subscribers, results))

    def test_results_appver_platform(self):
        self._generate()
        self.check_appver_platform_ignored(
            sorted(c.id for c in self.collections))

    def test_results_other_applications(self):
        tb_collection = amo.tests.collection_factory(
            application_id=amo.THUNDERBIRD.id)
        sm_collection = amo.tests.collection_factory(
            application_id=amo.SEAMONKEY.id)
        self.refresh()

        r = self.client.get(self.url)
        eq_(self.get_results(r), [])

        r = self.client.get(self.url.replace('firefox', 'thunderbird'))
        eq_(self.get_results(r), [tb_collection.id])

        r = self.client.get(self.url.replace('firefox', 'seamonkey'))
        eq_(self.get_results(r), [sm_collection.id])


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


class TestAjaxSearch(amo.tests.ESTestCase):

    @classmethod
    def setUpClass(cls):
        super(TestAjaxSearch, cls).setUpClass()
        cls.setUpIndex()

    def search_addons(self, url, params, addons=[], types=amo.ADDON_TYPES,
                      src=None):
        r = self.client.get(url + '?' + params)
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


class TestGenericAjaxSearch(TestAjaxSearch):

    def search_addons(self, params, addons=[]):
        [a.save() for a in Addon.objects.all()]
        self.refresh()
        super(TestGenericAjaxSearch, self).search_addons(
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

    def test_ajax_search_admin_deleted_by_id(self):
        amo.tests.addon_factory(status=amo.STATUS_DELETED)
        self.refresh()
        addon = Addon.with_deleted.filter(status=amo.STATUS_DELETED)[0]
        self.search_addons('q=%s' % addon.id, [])

    def test_ajax_search_personas_by_id(self):
        addon = Addon.objects.all()[3]
        addon.update(type=amo.ADDON_PERSONA)
        Persona.objects.create(persona_id=addon.id, addon_id=addon.id)
        self.search_addons('q=%s' % addon.id, [addon])

    def test_ajax_search_by_name(self):
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
        r = self.client.get(self.url + '?' + params)
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

    def test_unicode(self):
        self.search_addons('q=%C2%B2%C2%B2', [])

    def test_personas(self):
        personas = (Addon.objects.reviewed()
                    .filter(type=amo.ADDON_PERSONA, disabled_by_user=False))
        personas, types = list(personas), [amo.ADDON_PERSONA]
        self.search_addons('q=add&cat=personas', personas, types)
        self.search_addons('q=persona&cat=personas', personas, types)
        self.search_addons('q=PERSONA&cat=personas', personas, types)
        self.search_addons('q=persona&cat=all', [])

    def test_applications(self):
        self.search_applications('', [])
        self.search_applications('q=FIREFOX', [amo.FIREFOX])
        self.search_applications('q=firefox', [amo.FIREFOX])
        self.search_applications('q=bird', [amo.THUNDERBIRD])
        self.search_applications('q=mobile', [amo.MOBILE])
        self.search_applications('q=mozilla', [])
