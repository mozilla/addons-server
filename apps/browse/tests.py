# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from dateutil.parser import parse as parse_dt
import re
from urlparse import urlparse

from django import http
from django.conf import settings
from django.core.cache import cache
from django.utils import http as urllib

import mock
from nose import SkipTest
from nose.tools import eq_, assert_raises
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from amo.helpers import absolutify, urlparams
from addons.tests.test_views import TestMobile
from addons.models import (Addon, AddonCategory, Category, AppSupport, Feature,
                           Persona)
from addons.utils import FeaturedManager
from applications.models import Application
from bandwagon.models import Collection, CollectionAddon, FeaturedCollection
from browse import views, feeds
from browse.views import locale_display_name, ImpalaAddonFilter
from translations.models import Translation
from translations.query import order_by_translation
from versions.models import Version


class TestExtensions(amo.tests.ESTestCase):
    es = True

    def setUp(self):
        super(TestExtensions, self).setUp()
        self.url = reverse('browse.es.extensions')

    def test_default_sort(self):
        r = self.client.get(self.url)
        eq_(r.context['sorting'], 'popular')

    def test_name_sort(self):
        r = self.client.get(urlparams(self.url, sort='name'))
        addons = r.context['addons'].object_list
        assert list(addons)
        eq_(list(addons), sorted(addons, key=lambda x: x.name))

    def test_updated_sort(self):
        r = self.client.get(urlparams(self.url, sort='updated'))
        addons = r.context['addons'].object_list
        assert list(addons)
        eq_(list(addons),
            sorted(addons, key=lambda x: x.last_updated, reverse=True))

    def test_created_sort(self):
        r = self.client.get(urlparams(self.url, sort='created'))
        addons = r.context['addons'].object_list
        assert list(addons)
        eq_(list(addons),
            sorted(addons, key=lambda x: x.created, reverse=True))

    def test_popular_sort(self):
        r = self.client.get(urlparams(self.url, sort='popular'))
        addons = r.context['addons'].object_list
        assert list(addons)
        eq_(list(addons),
            sorted(addons, key=lambda x: x.weekly_downloads, reverse=True))

    def test_rating_sort(self):
        r = self.client.get(urlparams(self.url, sort='rating'))
        addons = r.context['addons'].object_list
        assert list(addons)
        eq_(list(addons),
            sorted(addons, key=lambda x: x.bayesian_rating, reverse=True))

    def test_category(self):
        # Stick one add-on in a category, make sure search finds it.
        addon = Addon.objects.filter(status=amo.STATUS_PUBLIC,
                                     disabled_by_user=False)[0]
        c = Category.objects.create(application_id=amo.FIREFOX.id,
                                    slug='alerts', type=addon.type)
        AddonCategory.objects.create(category=c, addon=addon)
        addon.save()
        self.refresh()

        cat_url = reverse('browse.es.extensions', args=['alerts'])
        r = self.client.get(urlparams(cat_url))
        addons = r.context['addons'].object_list
        eq_(list(addons), [addon])

    def test_invalid_sort(self):
        r = self.client.get(urlparams(self.url, sort='wut'))
        addons = r.context['addons'].object_list
        assert list(addons)
        eq_(list(addons),
            sorted(addons, key=lambda x: x.weekly_downloads, reverse=True))


def test_locale_display_name():

    def check(locale, english, native):
        actual = locale_display_name(locale)
        eq_(actual, (english, native))

    check('el', 'Greek', u'Ελληνικά')
    check('el-XX', 'Greek', u'Ελληνικά')
    assert_raises(KeyError, check, 'fake-lang', '', '')


class TestLanguageTools(amo.tests.TestCase):
    fixtures = ['browse/test_views']

    def setUp(self):
        super(TestLanguageTools, self).setUp()
        cache.clear()
        self.url = reverse('browse.language-tools')
        response = self.client.get(self.url, follow=True)
        # For some reason the context doesn't get loaded the first time.
        response = self.client.get(self.url, follow=True)
        self.locales = list(response.context['locales'])

    def test_sorting(self):
        """The locales should be sorted by English display name."""
        displays = [locale.display for _, locale in self.locales]
        eq_(displays, sorted(displays))

    def test_native_missing_region(self):
        """
        If we had to strip a locale's region to find a display name, we
        append it to the native name for disambiguation.
        """
        el = dict(self.locales)['el-XX']
        assert el.native.endswith(' (el-xx)')

    def test_missing_locale(self):
        """If we don't know about a locale, show the addon name and locale."""
        wa = dict(self.locales)['wa']
        eq_(wa.display, 'Walloon Language Pack (wa)')
        eq_(wa.native, '')

    def test_packs_and_dicts(self):
        ca = dict(self.locales)['ca-valencia']
        eq_(len(ca.dicts), 1)
        eq_(len(ca.packs), 3)

    def test_empty_target_locale(self):
        """Make sure nothing breaks with empty target locales."""
        for addon in Addon.objects.all():
            addon.target_locale = ''
            addon.save()
        response = self.client.get(self.url, follow=True)
        eq_(response.status_code, 200)
        eq_(list(response.context['locales']), [])

    def test_null_target_locale(self):
        """Make sure nothing breaks with null target locales."""
        for addon in Addon.objects.all():
            addon.target_locale = None
            addon.save()
        response = self.client.get(self.url, follow=True)
        eq_(response.status_code, 200)
        eq_(list(response.context['locales']), [])


class TestThemes(amo.tests.TestCase):
    fixtures = ('base/category', 'base/addon_6704_grapple', 'base/addon_3615')

    def setUp(self):
        super(TestThemes, self).setUp()
        # Make all the add-ons themes.
        for addon in Addon.objects.all():
            addon.type = amo.ADDON_THEME
            addon.save()
        for category in Category.objects.all():
            category.type = amo.ADDON_THEME
            category.save()

        self.base_url = reverse('browse.themes')
        self.exp_url = urlparams(self.base_url)

    def test_default_sort(self):
        """Default sort should be by popular."""
        response = self.client.get(self.base_url)
        eq_(response.context['sorting'], 'popular')

    def test_unreviewed(self):
        # Only 3 without unreviewed.
        response = self.client.get(self.base_url)
        eq_(len(response.context['themes'].object_list), 2)

        response = self.client.get(self.exp_url)
        eq_(len(response.context['themes'].object_list), 2)

    def _get_sort(self, sort):
        response = self.client.get(urlparams(self.exp_url, sort=sort))
        eq_(response.context['sorting'], sort)
        return [a.id for a in response.context['themes'].object_list]

    def test_download_sort(self):
        ids = self._get_sort('popular')
        eq_(ids, [3615, 6704])

    def test_name_sort(self):
        ids = self._get_sort('name')
        eq_(ids, [3615, 6704])

    def test_created_sort(self):
        ids = self._get_sort('created')
        eq_(ids, [6704, 3615])

    def test_updated_sort(self):
        ids = self._get_sort('updated')
        eq_(ids, [6704, 3615])

    def test_rating_sort(self):
        ids = self._get_sort('rating')
        eq_(ids, [6704, 3615])

    def test_category_count(self):
        cat = Category.objects.filter(name__isnull=False)[0]
        response = self.client.get(reverse('browse.themes', args=[cat.slug]))
        doc = pq(response.content)
        actual_count = int(doc('hgroup h3').text().split()[0])
        page = response.context['themes']
        expected_count = page.paginator.count
        eq_(actual_count, expected_count)


class TestCategoryPages(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/category', 'base/addon_3615',
                'base/featured', 'addons/featured', 'browse/nameless-addon']

    def setUp(self):
        patcher = mock.patch.object(settings, 'NEW_FEATURES', False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_browsing_urls(self):
        """Every browse page URL exists."""
        for _, slug in amo.ADDON_SLUGS.items():
            assert reverse('browse.%s' % slug)

    def test_matching_opts(self):
        """Every filter on landing pages is available on listing pages."""
        for key, _ in views.CategoryLandingFilter.opts:
            if key != 'featured':
                assert key in dict(views.AddonFilter.opts)

    @mock.patch('browse.views.category_landing')
    def test_goto_category_landing(self, landing_mock):
        """We hit a landing page if there's a category and no sorting."""
        landing_mock.return_value = http.HttpResponse()

        self.client.get(reverse('browse.extensions'))
        assert not landing_mock.called

        category = Category.objects.all()[0]
        category_url = reverse('browse.extensions', args=[category.slug])

        self.client.get('%s?sort=created' % category_url)
        assert not landing_mock.called

        self.client.get(category_url)
        assert landing_mock.called

        # Category with fewer than 5 add-ons bypasses landing page.
        category.count = 4
        category.save()
        self.client.get(category_url)
        eq_(landing_mock.call_count, 1)

    def test_creatured_addons(self):
        """Make sure the creatured add-ons are for the right category."""
        # Featured in bookmarks.
        url = reverse('browse.extensions', args=['bookmarks'])
        response = self.client.get(url, follow=True)
        creatured = response.context['filter'].all()['featured']
        eq_(len(creatured), 1)
        eq_(creatured[0].id, 3615)

        # Not featured in search-tools.
        url = reverse('browse.extensions', args=['search-tools'])
        response = self.client.get(url, follow=True)
        creatured = response.context['filter'].all()['featured']
        eq_(len(creatured), 0)

    def test_creatured_only_public(self):
        """Make sure the creatured add-ons are all public."""
        url = reverse('browse.creatured', args=['bookmarks'])
        r = self.client.get(url, follow=True)
        addons = r.context['addons']

        for a in addons:
            assert a.status == amo.STATUS_PUBLIC, "%s is not public" % a.name

        old_count = len(addons)
        addons[0].status = amo.STATUS_UNREVIEWED
        addons[0].save()
        r = self.client.get(url, follow=True)
        addons = r.context['addons']

        for a in addons:
            assert a.status == amo.STATUS_PUBLIC, ("Altered %s is featured"
                                                   % a.name)

        eq_(len(addons), old_count - 1, "The number of addons is the same.")

    def test_added_date(self):
        url = reverse('browse.extensions') + '?sort=created'
        doc = pq(self.client.get(url).content)
        s = doc('.featured .item .updated').text()
        assert s.strip().startswith('Added'), s

    def test_sorting_nameless(self):
        """Nameless add-ons are dropped from the sort."""
        qs = Addon.objects.all()
        ids = order_by_translation(qs, 'name')
        assert 57132 in [a.id for a in qs]
        assert 57132 not in [a.id for a in ids]


class TestImpalaExtensions(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/category', 'base/featured',
                'addons/featured', 'addons/listed', 'base/collections',
                'bandwagon/featured_collections']

    def setUp(self):
        self.reset_featured_addons()
        self.url = reverse('i_browse.extensions')

    def test_added_date(self):
        self.url += '?sort=created'
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.items .item .updated').text().startswith('Added'), True)

    def test_updated_date(self):
        self.url += '?sort=updated'
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.items .item .updated').text().startswith('Updated'), True)

    def test_users_adu_unit(self):
        self.url += '?sort=users'
        doc = pq(self.client.get(self.url).content)
        s = doc('.items .item .adu').text()
        eq_('users' in doc('.items .item .adu').text(), True)

    def test_popular_adu_unit(self):
        self.url += '?sort=popular'
        doc = pq(self.client.get(self.url).content)
        s = doc('.items .item .adu').text()
        eq_('weekly downloads' in doc('.items .item .adu').text(), True)


class TestFeeds(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/category', 'base/featured',
                'addons/featured', 'addons/listed', 'base/collections',
                'bandwagon/featured_collections']

    def setUp(self):
        self.reset_featured_addons()
        self.url = reverse('i_browse.extensions')
        self.rss_url = reverse('browse.extensions.rss')
        self.filter = ImpalaAddonFilter

    def _check_feed(self, browse_url, rss_url, expected_sort='featured'):
        """
        Check RSS feed URLs and that the results on the listing pages match
        those for their respective RSS feeds.
        """
        # Check URLs.
        r = self.client.get(browse_url, follow=True)
        doc = pq(r.content)
        rss_url += '?sort=%s' % expected_sort
        eq_(doc('link[type="application/rss+xml"]').attr('href'), rss_url)
        eq_(doc('#subscribe').attr('href'), rss_url)

        # Ensure that the RSS items match those on the browse listing pages.
        r = self.client.get(rss_url)
        rss_doc = pq(r.content)
        pg_items = doc('.items .item')
        rss_items = rss_doc('item')
        for pg_item, rss_item in zip(pg_items, rss_items):
            pg_item, rss_item = pq(pg_item), pq(rss_item)
            pg_url = absolutify(pg_item.find('h3 a').attr('href'))
            rss_url = rss_item.find('link').text()
            eq_(pg_url, rss_url)
            if expected_sort in ('added', 'updated'):
                # Check timestamps.
                pg_ts = pg_item.find('.updated').text().strip('Added Updated')
                rss_ts = rss_item.find('pubDate').text()
                # Look at YMD, since we don't have h:m on listing pages.
                eq_(parse_dt(pg_ts).isocalendar(),
                    parse_dt(rss_ts).isocalendar())

    def _check_sort_urls(self, items, opts, attr):
        pg_url = self.url
        rss_url = self.rss_url
        filter_ = self.filter
        for item, options in zip(items, getattr(filter_, opts)):
            slug, title = options
            url = '%s?sort=%s' % (pg_url, slug)
            val = item.get(attr)
            if attr == 'href':
                eq_(val, url)
            else:
                eq_(val, slug)
            eq_(item.text, unicode(title))
            self._check_feed(url, rss_url, slug)

    def test_feed(self):
        eq_(self.client.get(self.rss_url).status_code, 200)

    def test_sort_opts_urls(self):
        r = self.client.get(self.url, follow=True)
        s = pq(r.content)('#sorter')
        self._check_feed(self.url, self.rss_url, 'featured')
        self._check_sort_urls(s.find('ul > li a'), 'opts', 'href')
        self._check_sort_urls(s.find('option[value!=""]'), 'extras', 'value')


class TestFeaturedLocale(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/category', 'base/addon_3615',
                'base/featured', 'addons/featured', 'browse/nameless-addon']

    def setUp(self):
        patcher = mock.patch.object(settings, 'NEW_FEATURES', False)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.addon = Addon.objects.get(pk=3615)
        self.persona = Addon.objects.get(pk=15679)
        self.extension = Addon.objects.get(pk=2464)
        self.category = Category.objects.get(slug='bookmarks')

        self.url = reverse('browse.creatured', args=['bookmarks'])
        cache.clear()

    def change_addoncategory(self, addon, locale='es-ES'):
        ac = addon.addoncategory_set.all()[0]
        ac.feature_locales = locale
        ac.save()
        self.reset()

    def change_addon(self, addon, locale='es-ES'):
        feature = addon.feature_set.all()[0]
        feature.locale = locale
        feature.save()
        self.reset()

    def reset(self):
        cache.clear()
        FeaturedManager.redis().flushall()
        self.reset_featured_addons()

    def list_featured(self, content):
        # Not sure we want to get into testing randomness
        # between multiple executions of a page, but if this is a quick
        # way to print out the results and check yourself that they
        # are changing.
        doc = pq(content)
        ass = doc('.featured-inner .item a')
        rx = re.compile('/(en-US|es-ES)/firefox/addon/(\d+)/$')
        for a in ass:
            mtch = rx.match(a.attrib['href'])
            if mtch:
                print mtch.group(2)

    def test_creatured_random_caching(self):
        rnd = AddonCategory.creatured_random
        cat = Category.objects.get(pk=22)
        self.assertNumQueries(0, rnd, cat, 'en-US')
        self.assertNumQueries(0, rnd, cat, 'en-US')
        self.assertNumQueries(0, rnd, cat, 'es-ES')

    def test_featured_random_caching(self):
        rnd = Addon.featured_random
        self.assertNumQueries(0, rnd, amo.FIREFOX, 'en-US')
        self.assertNumQueries(0, rnd, amo.FIREFOX, 'es-ES')
        self.assertNumQueries(0, rnd, amo.THUNDERBIRD, 'es-ES')
        self.assertNumQueries(0, rnd, amo.THUNDERBIRD, 'en-US')

    def test_creatured_locale_en_US(self):
        res = self.client.get(self.url)
        assert self.addon in res.context['addons']

    def test_creatured_locale_nones(self):
        self.change_addoncategory(self.addon, '')
        res = self.client.get(self.url)
        assert self.addon in res.context['addons']

        self.change_addoncategory(self.addon, None)
        res = self.client.get(self.url)
        assert self.addon in res.context['addons']

    def test_creatured_locale_many(self):
        self.change_addoncategory(self.addon, 'en-US,es-ES')
        res = self.client.get(self.url)
        assert self.addon in res.context['addons']

        res = self.client.get(self.url.replace('en-US', 'es-ES'))
        assert self.addon in res.context['addons']

    def test_creatured_locale_not_en_US(self):
        self.change_addoncategory(self.addon, 'es-ES')
        res = self.client.get(self.url)
        assert self.addon not in res.context['addons']

    def test_creatured_locale_es_ES(self):
        res = self.client.get(self.url.replace('en-US', 'es-ES'))
        assert self.addon in res.context['addons']

    def test_featured_locale_en_US(self):
        res = self.client.get(reverse('browse.featured'))
        assert self.extension in res.context['addons']

    def test_featured_locale_not_persona_en_US(self):
        res = self.client.get(reverse('browse.featured'))
        assert not self.persona in res.context['addons']

    def test_featured_locale_es_ES(self):
        self.change_addon(self.extension, 'es-ES')
        url = reverse('browse.featured')
        res = self.client.get(url)
        assert self.extension not in res.context['addons']

        res = self.client.get(url.replace('en-US', 'es-ES'))
        self.change_addon(self.extension, 'es-ES')
        assert self.extension in res.context['addons']

    def test_featured_extensions_no_category_en_US(self):
        addon = self.extension
        res = self.client.get(reverse('browse.extensions'))
        assert addon in res.context['addons'].object_list

    def test_featured_extensions_with_category_es_ES(self):
        addon = self.addon
        res = self.client.get(reverse('browse.extensions', args=['bookmarks']))
        assert addon in res.context['filter'].all()['featured']

        self.change_addoncategory(addon, 'es-ES')
        res = self.client.get(reverse('browse.extensions', args=['bookmarks']))
        assert addon not in res.context['filter'].all()['featured']

    def test_featured_persona_no_category_en_US(self):
        addon = self.persona
        url = reverse('browse.personas')
        res = self.client.get(url)
        assert addon in res.context['featured']

        self.change_addon(addon, 'es-ES')
        res = self.client.get(url)
        assert addon not in res.context['featured']

        res = self.client.get(url.replace('en-US', 'es-ES'))
        assert addon in res.context['featured']

    def test_featured_persona_category_en_US(self):
        addon = self.persona
        category = Category.objects.get(id=22)
        category.update(type=amo.ADDON_PERSONA)

        addon.addoncategory_set.create(category=category, feature=True)
        self.reset()
        url = reverse('browse.personas', args=[category.slug])
        res = self.client.get(url)
        assert addon in res.context['featured']

        self.change_addoncategory(addon, 'es-ES')
        res = self.client.get(url)
        assert addon not in res.context['featured']

        res = self.client.get(url.replace('en-US', 'es-ES'))
        assert addon in res.context['featured']

    def test_homepage(self):
        url = reverse('home')
        res = self.client.get(url)
        assert self.extension in res.context['featured']

        self.change_addon(self.extension, 'es-ES')
        res = self.client.get(url)
        assert self.extension not in res.context['featured']

        res = self.client.get(url.replace('en-US', 'es-ES'))
        assert self.extension in res.context['featured']

    def test_homepage_persona(self):
        res = self.client.get(reverse('home'))
        assert self.persona not in res.context['featured']

    def test_homepage_filter(self):
        # Ensure that the base homepage filter is applied.
        res = self.client.get(reverse('home'))
        listed = [p.pk for p in Addon.objects
                                      .listed(amo.FIREFOX)
                                      .exclude(type=amo.ADDON_PERSONA)]

        featured = Addon.featured_random(amo.FIREFOX, 'en-US')
        actual = [p.pk for p in res.context['featured']]

        eq_(sorted(actual), sorted(set(listed) & set(featured)))

    def test_homepage_listed_single(self):
        listed = [p.pk for p in Addon.objects.listed(amo.FIREFOX)]
        eq_(listed.count(7661), 1)
        addon = Addon.objects.get(pk=7661)
        addon.update(status=amo.STATUS_PUBLIC)
        listed = [p.pk for p in Addon.objects.listed(amo.FIREFOX)]
        eq_(listed.count(7661), 1)

    def test_homepage_order(self):
        # Make these apps listed.
        for pk in [1003, 3481]:
            addon = Addon.objects.get(pk=pk)
            addon.update(status=amo.STATUS_PUBLIC)
            addon.appsupport_set.create(app_id=1)

        # Note 1003 and 3481 are now en-US.
        # And 7661 and 2464 are now None.
        # The order should be random within those boundaries.
        another = Addon.objects.get(id=1003)
        self.change_addon(another, 'en-US')
        self.reset_featured_addons()

        url = reverse('home')
        res = self.client.get(url)
        items = res.context['featured']

        eq_([1003, 3481], sorted([i.pk for i in items[0:2]]))
        eq_([2464, 7661], sorted([i.pk for i in items[2:]]))

        res = self.client.get(url.replace('en-US', 'es-ES'))
        items = res.context['featured']
        eq_([2464, 7661], sorted([i.pk for i in items]))

        self.change_addon(another, 'es-ES')

        res = self.client.get(url.replace('en-US', 'es-ES'))
        items = res.context['featured']
        eq_(items[0].pk, 1003)
        eq_([1003, 2464, 7661], sorted([i.pk for i in items]))

    def test_featured_ids(self):
        another = Addon.objects.get(id=1003)
        self.change_addon(another, 'en-US')
        items = Addon.featured_random(amo.FIREFOX, 'en-US')

        # The order should be random within those boundaries.
        eq_([1003, 3481], sorted(items[0:2]))
        eq_([1001, 2464, 7661, 15679], sorted(items[2:]))

    def test_featured_duplicated(self):
        another = Addon.objects.get(id=1003)
        self.change_addon(another, 'en-US')
        another.feature_set.create(application_id=amo.FIREFOX.id,
                                   locale=None,
                                   start=datetime.today(),
                                   end=datetime.today())
        eq_(Addon.featured_random(amo.FIREFOX, 'en-US').count(1003), 1)


class TestNewFeaturedLocale(TestFeaturedLocale):
    fixtures = (TestFeaturedLocale.fixtures +
                ['base/collections', 'addons/featured', 'base/featured',
                 'bandwagon/featured_collections',
                 'base/addon_3615_featuredcollection'])

    # TODO(cvan): Merge with above once new featured add-ons are enabled.
    def setUp(self):
        super(TestNewFeaturedLocale, self).setUp()
        patcher = mock.patch.object(settings, 'NEW_FEATURES', True)
        patcher.start()
        self.reset_featured_addons()
        self.addCleanup(patcher.stop)

    def test_featured_random_caching(self):
        raise SkipTest()  # We're no longer caching `featured_random`.

    def test_creatured_random_caching(self):
        raise SkipTest()  # We're no longer caching `creatured_random`.

    def change_addon(self, addon, locale='es-ES'):
        fc = FeaturedCollection.objects.filter(collection__addons=addon.id)[0]
        feature = FeaturedCollection.objects.create(locale=locale,
            application=Application.objects.get(id=amo.FIREFOX.id),
            collection=Collection.objects.create())
        c = CollectionAddon.objects.filter(addon=addon,
                                           collection=fc.collection)[0]
        c.collection = feature.collection
        c.save()
        self.reset()

    def change_addoncategory(self, addon, locale='es-ES'):
        CollectionAddon.objects.filter(addon=addon).delete()
        locales = (locale or '').split(',')
        for locale in locales:
            c = CollectionAddon.objects.create(addon=addon,
                collection=Collection.objects.create())
            FeaturedCollection.objects.create(locale=locale,
                application=Application.objects.get(id=amo.FIREFOX.id),
                collection=c.collection)
        self.reset()

    def test_featured_ids(self):
        # TODO(cvan): Change the TestFeaturedLocale test
        # accordingly after we switch over to the new features.
        FeaturedCollection.objects.filter(collection__addons=3615)[0].delete()
        super(TestNewFeaturedLocale, self).test_featured_ids()

    def test_homepage_order(self):
        # TODO(cvan): Change the TestFeaturedLocale test
        # accordingly after we switch over to the new features.
        FeaturedCollection.objects.filter(collection__addons=3615)[0].delete()
        super(TestNewFeaturedLocale, self).test_homepage_order()

    def test_creatured_locale_es_ES(self):
        """Ensure 'en-US'-creatured add-ons do not exist for other locales."""
        res = self.client.get(self.url.replace('en-US', 'es-ES'))
        assert self.addon not in res.context['addons']


class TestListingByStatus(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)

    def get_addon(self, addon_status, file_status):
        self.addon.current_version.all_files[0].update(status=file_status)
        self.addon.update(status=addon_status, _current_version=None)
        self.addon.update_version()
        return Addon.objects.get(id=3615)

    def check(self, exp):
        r = self.client.get(reverse('browse.extensions'))
        addons = list(r.context['addons'].object_list)
        eq_(addons, exp)

    def test_public_public_listed(self):
        self.get_addon(amo.STATUS_PUBLIC, amo.STATUS_PUBLIC)
        self.check([self.addon])

    def test_public_nom_unlisted(self):
        self.get_addon(amo.STATUS_PUBLIC, amo.STATUS_NOMINATED)
        self.check([])

    def test_public_lite_unlisted(self):
        self.get_addon(amo.STATUS_PUBLIC, amo.STATUS_LITE)
        self.check([])

    def test_lite_unreviewed_unlisted(self):
        self.get_addon(amo.STATUS_LITE, amo.STATUS_UNREVIEWED)
        self.check([])

    def test_lite_lite_listed(self):
        self.get_addon(amo.STATUS_LITE, amo.STATUS_LITE)
        self.check([self.addon])

    def test_lite_lan_listed(self):
        self.get_addon(amo.STATUS_LITE, amo.STATUS_LITE_AND_NOMINATED)
        self.check([self.addon])

    def test_lan_unreviewed_unlisted(self):
        self.get_addon(amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_UNREVIEWED)
        self.check([])

    def test_lan_lite_listed(self):
        self.get_addon(amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE)
        self.check([self.addon])

    def test_lan_public_listed(self):
        self.get_addon(amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_PUBLIC)
        self.check([self.addon])

    def test_unreviewed_public_unlisted(self):
        self.get_addon(amo.STATUS_UNREVIEWED, amo.STATUS_PUBLIC)
        self.check([])

    def test_nom_public_unlisted(self):
        self.get_addon(amo.STATUS_NOMINATED, amo.STATUS_PUBLIC)
        self.check([])


class BaseSearchToolsTest(amo.tests.TestCase):
    fixtures = ('base/apps', 'base/featured', 'addons/featured',
                'base/category', 'addons/listed')

    def setUp(self):
        super(BaseSearchToolsTest, self).setUp()
        # Transform bookmarks into a search category:
        Category.objects.filter(slug='bookmarks').update(type=amo.ADDON_SEARCH)

    def setup_featured_tools_and_extensions(self):
        # Pretend all Add-ons are search-related:
        Addon.objects.update(type=amo.ADDON_SEARCH)

        # One will be an extension in the search category:
        limon = Addon.objects.get(
                name__localized_string='Limon free English-Hebrew dictionary')
        limon.type = amo.ADDON_EXTENSION
        limon.status = amo.STATUS_PUBLIC
        limon.save()
        AppSupport(addon=limon, app_id=amo.FIREFOX.id).save()

        # Another will be a search add-on in the search category:
        readit = Addon.objects.get(name__localized_string='Read It Later')
        readit.type = amo.ADDON_SEARCH
        readit.status = amo.STATUS_PUBLIC
        readit.save()

        # Un-feature all others:
        Feature.objects.all().delete()

        # Feature foxy :
        foxy = Addon.objects.get(name__localized_string='FoxyProxy Standard')
        Feature(addon=foxy, application_id=amo.FIREFOX.id,
                start=datetime.now(),
                end=datetime.now() + timedelta(days=30)).save()

        # Feature Limon Dictionary and Read It Later as a category feature:
        s = Category.objects.get(slug='search-tools')
        s.addoncategory_set.add(AddonCategory(addon=limon, feature=True))
        s.addoncategory_set.add(AddonCategory(addon=readit, feature=True))
        s.save()
        self.reset_featured_addons()


class TestSearchToolsPages(BaseSearchToolsTest):

    def test_landing_page(self):
        self.setup_featured_tools_and_extensions()
        response = self.client.get(reverse('browse.search-tools'))
        eq_(response.status_code, 200)
        doc = pq(response.content)

        # Should have only featured add-ons:
        eq_(sorted([a.name.localized_string
                    for a in response.context['addons'].object_list]),
            [u'FoxyProxy Standard', u'Limon free English-Hebrew dictionary',
             u'Read It Later'])

        # Ensure that all heading links have the proper base URL
        # between the category / no category cases.
        sort_links = [urlparse(a.attrib['href']).path for a in
                      doc('.listing-header ul li a')]
        eq_(set(sort_links), set([reverse('browse.search-tools')]))

    def test_sidebar_extensions_links(self):
        response = self.client.get(reverse('browse.search-tools'))
        eq_(response.status_code, 200)
        doc = pq(response.content)

        links = doc('#search-tools-sidebar a')

        eq_([a.text.strip() for a in links], [
             # Search Extensions
             'Most Popular', 'Recently Added',
             # Search Providers
             'Bookmarks'])

        search_ext_url = urlparse(reverse('browse.extensions',
                                  kwargs=dict(category='search-tools')))

        eq_(urlparse(links[0].attrib['href']).path, search_ext_url.path)
        eq_(urlparse(links[1].attrib['href']).path, search_ext_url.path)

    def test_additional_resources(self):
        for prefix, app in (
                ('/en-US/firefox', amo.FIREFOX.pretty),
                ('/en-US/seamonkey', amo.SEAMONKEY.pretty)):
            app = unicode(app)  # get the proxied unicode obj
            response = self.client.get('%s/search-tools/' % prefix)
            eq_(response.status_code, 200)
            doc = pq(response.content)
            txt = doc('#additional-resources ul li:eq(0)').text()
            assert txt.endswith(app), "Expected %r got: %r" % (app, txt)

    def test_search_tools_arent_friends_with_everyone(self):
        # Search tools only show up for Firefox
        response = self.client.get('/en-US/thunderbird/search-tools/')
        doc = pq(response.content)
        assert not doc('#search-tools-sidebar')

    def test_other_pages_exclude_extensions(self):
        # pretend all Add-ons are search-related:
        Addon.objects.update(type=amo.ADDON_SEARCH)
        # randomly make one an extension to be sure it is filtered out:
        Addon.objects.valid()[0].update(type=amo.ADDON_EXTENSION)

        for sort_key in ('name', 'updated', 'created', 'popular', 'rating'):
            url = reverse('browse.search-tools') + '?sort=' + sort_key
            r = self.client.get(url)
            all_addons = r.context['addons'].object_list
            assert len(all_addons)
            for addon in all_addons:
                assert addon.type == amo.ADDON_SEARCH, (
                            "sort=%s; Unexpected Add-on type for %r" % (
                                                        sort_key, addon))

    def test_no_featured_addons_by_category(self):
        Feature.objects.all().delete()
        # Pretend Foxy is a bookmarks related search add-on
        foxy = Addon.objects.get(name__localized_string='FoxyProxy Standard')
        foxy.type = amo.ADDON_SEARCH
        foxy.save()
        bookmarks = Category.objects.get(slug='bookmarks')
        bookmarks.addoncategory_set.add(
                            AddonCategory(addon=foxy, feature=False))
        bookmarks.save()

        response = self.client.get(reverse('browse.search-tools',
                                           args=('bookmarks',)))
        eq_(response.status_code, 200)
        doc = pq(response.content)

        eq_([a.name.localized_string
                for a in response.context['addons'].object_list],
            [u'FoxyProxy Standard'])
        eq_(response.context['filter'].field, 'popular')

        eq_(doc('title').text(),
            'Bookmarks :: Search Tools :: Add-ons for Firefox')

        # Ensure that all heading links have the proper base URL
        # between the category / no category cases.
        sort_links = [urlparse(a.attrib['href']).path for a in
                      doc('.listing-header ul li a')]
        eq_(set(sort_links), set([reverse('browse.search-tools',
                                          args=('bookmarks',))]))

    def test_rss_links_per_page(self):

        def get_link(url):
            r = self.client.get(url)
            eq_(r.status_code, 200)
            doc = pq(r.content)
            return doc('head link[type="application/rss+xml"]').attr('href')

        eq_(get_link(reverse('browse.search-tools')),
            reverse('browse.search-tools.rss') + '?sort=featured')

        eq_(get_link(reverse('browse.search-tools') + '?sort=name'),
            reverse('browse.search-tools.rss') + '?sort=name')

        eq_(get_link(reverse('browse.search-tools', args=('bookmarks',))),
            reverse('browse.search-tools.rss',
                    args=('bookmarks',)) + '?sort=popular')


class TestSearchToolsFeed(BaseSearchToolsTest):

    def test_featured_search_tools(self):
        self.setup_featured_tools_and_extensions()
        url = reverse('browse.search-tools.rss') + '?sort=featured'
        r = self.client.get(url)
        eq_(r.status_code, 200)
        doc = pq(r.content)

        eq_(doc('rss channel title')[0].text,
                'Search Tools :: Add-ons for Firefox')
        link = doc('rss channel link')[0].text
        rel_link = reverse('browse.search-tools.rss') + '?sort=featured'
        assert link.endswith(rel_link), ('Unexpected link: %r' % link)
        eq_(doc('rss channel description')[0].text,
            "Search tools and search-related extensions")

        # There should be two features: one search tool and one extension.
        eq_(sorted([e.text for e in doc('rss channel item title')]),
            ['FoxyProxy Standard 2.17',
             'Limon free English-Hebrew dictionary 0.5.3',
             'Read It Later 2.0.3'])

    def test_search_tools_no_sorting(self):
        url = reverse('browse.search-tools.rss')
        r = self.client.get(url)
        eq_(r.status_code, 200)
        doc = pq(r.content)

        link = doc('rss channel link')[0].text
        rel_link = reverse('browse.search-tools.rss') + '?sort=popular'
        assert link.endswith(rel_link), ('Unexpected link: %r' % link)

    def test_search_tools_by_name(self):
        # Pretend Foxy is a search add-on
        (Addon.objects.filter(name__localized_string='FoxyProxy Standard')
                      .update(type=amo.ADDON_SEARCH))

        url = reverse('browse.search-tools.rss') + '?sort=name'
        r = self.client.get(url)
        eq_(r.status_code, 200)
        doc = pq(r.content)

        eq_(doc('rss channel description')[0].text, 'Search tools')

        # There should be only search tools.
        eq_([e.text for e in doc('rss channel item title')],
            ['FoxyProxy Standard 2.17'])

    def test_search_tools_within_a_category(self):
        # Pretend Foxy is the only bookmarks related search add-on
        AddonCategory.objects.all().delete()
        foxy = Addon.objects.get(name__localized_string='FoxyProxy Standard')
        foxy.type = amo.ADDON_SEARCH
        foxy.save()
        bookmarks = Category.objects.get(slug='bookmarks')
        bookmarks.addoncategory_set.add(
                            AddonCategory(addon=foxy, feature=False))
        bookmarks.save()

        url = reverse('browse.search-tools.rss',
                      args=('bookmarks',)) + '?sort=popular'
        r = self.client.get(url)
        eq_(r.status_code, 200)
        doc = pq(r.content)

        eq_(doc('rss channel title')[0].text,
                'Bookmarks :: Search Tools :: Add-ons for Firefox')

        link = doc('rss channel link')[0].text
        rel_link = reverse('browse.search-tools.rss',
                           args=('bookmarks',)) + '?sort=popular'
        assert link.endswith(rel_link), ('Unexpected link: %r' % link)

        eq_(doc('rss channel description')[0].text,
            "Search tools relating to Bookmarks")

        eq_([e.text for e in doc('rss channel item title')],
            ['FoxyProxy Standard 2.17'])

    def test_non_ascii_titles(self):
        bookmarks = Category.objects.get(slug='bookmarks')
        bookmarks.name = u'Ivan Krstić'
        bookmarks.save()

        url = reverse('browse.search-tools.rss',
                      args=('bookmarks',))
        r = self.client.get(url)
        eq_(r.status_code, 200)
        doc = pq(r.content)

        eq_(doc('rss channel title')[0].text,
                u'Ivan Krstić :: Search Tools :: Add-ons for Firefox')


class TestLegacyRedirects(amo.tests.TestCase):
    fixtures = ('base/category.json',)

    def test_types(self):
        def redirects(from_, to):
            r = self.client.get('/en-US/firefox' + from_)
            self.assertRedirects(r, '/en-US/firefox' + to, status_code=301,
                                 msg_prefix="Redirection failed: %s" % to)

        redirects('/browse/type:1', '/extensions/')
        redirects('/browse/type:1/', '/extensions/')
        redirects('/browse/type:1/cat:all', '/extensions/')
        redirects('/browse/type:1/cat:all/', '/extensions/')
        redirects('/browse/type:1/cat:72', '/extensions/alerts-updates/')
        redirects('/browse/type:1/cat:72/', '/extensions/alerts-updates/')
        redirects('/browse/type:1/cat:72/sort:newest/format:rss',
                  '/extensions/alerts-updates/format:rss?sort=created')
        redirects('/browse/type:1/cat:72/sort:weeklydownloads/format:rss',
                  '/extensions/alerts-updates/format:rss?sort=popular')

        redirects('/browse/type:2', '/themes/')
        redirects('/browse/type:3', '/language-tools/')
        redirects('/browse/type:4', '/search-tools/')
        redirects('/search-engines', '/search-tools/')
        # redirects('/browse/type:7', '/plugins/')
        redirects('/recommended', '/featured')
        redirects('/recommended/format:rss', '/featured/format:rss')


class TestFeaturedPage(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/featured', 'addons/featured']

    @mock.patch.object(settings, 'NEW_FEATURES', False)
    def test_featured_addons(self):
        """Make sure that only featured add-ons are shown."""
        response = self.client.get(reverse('browse.featured'))
        # But not in the content.
        eq_([1001, 1003, 2464, 3481, 7661],
            sorted(a.id for a in response.context['addons']))


class TestCategoriesFeed(amo.tests.TestCase):

    def setUp(self):
        self.feed = feeds.CategoriesRss()
        self.u = u'Ελληνικά'
        self.wut = Translation(localized_string=self.u, locale='el')

        self.feed.request = mock.Mock()
        self.feed.request.APP.pretty = self.u

        self.category = Category(name=self.u)

        self.addon = Addon(name=self.u, id=2, type=1, slug='xx')
        self.addon._current_version = Version(version='v%s' % self.u)

    def test_title(self):
        eq_(self.feed.title(self.category),
            u'%s :: Add-ons for %s' % (self.wut, self.u))

    def test_item_title(self):
        eq_(self.feed.item_title(self.addon),
            u'%s v%s' % (self.u, self.u))

    def test_item_guid(self):
        t = self.feed.item_guid(self.addon)
        url = u'/addon/%s/versions/v%s' % (self.addon.slug,
                                           urllib.urlquote(self.u))
        assert t.endswith(url), t


class TestFeaturedFeed(amo.tests.TestCase):
    fixtures = ['addons/featured', 'base/addon_3615', 'base/apps',
                'base/collections', 'base/featured', 'base/users']

    def setUp(self):
        patcher = mock.patch.object(settings, 'NEW_FEATURES', False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_feed_elements_present(self):
        url = reverse('browse.featured.rss')
        r = self.client.get(url, follow=True)
        doc = pq(r.content)
        eq_(doc('rss channel title')[0].text,
                'Featured Add-ons :: Add-ons for Firefox')
        assert doc('rss channel link')[0].text.endswith('/en-US/firefox/')
        eq_(doc('rss channel description')[0].text,
                "Here's a few of our favorite add-ons to help you get "
                "started customizing Firefox.")
        eq_(len(doc('rss channel item')),
            Addon.objects.featured(amo.FIREFOX).count())


class TestNewFeaturedFeed(TestFeaturedFeed):
    fixtures = TestFeaturedFeed.fixtures + ['bandwagon/featured_collections']

    def setUp(self):
        patcher = mock.patch.object(settings, 'NEW_FEATURES', True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestPersonas(amo.tests.TestCase):
    fixtures = ('base/apps', 'base/featured', 'addons/featured',
                'addons/persona')

    def test_personas_grid(self):
        """Show grid page if there are fewer than 5 Personas."""
        base = (Addon.objects.public().filter(type=amo.ADDON_PERSONA)
                .extra(select={'_app': amo.FIREFOX.id}))
        eq_(base.count(), 2)
        r = self.client.get(reverse('browse.personas'))
        self.assertTemplateUsed(r, 'browse/personas/grid.html')
        eq_(r.status_code, 200)
        assert 'is_homepage' in r.context

    def test_personas_landing(self):
        """Show landing page if there are greater than 4 Personas."""
        for i in xrange(3):
            a = Addon(type=amo.ADDON_PERSONA)
            a.name = 'persona-%s' % i
            a.all_categories = []
            a.save()
            v = Version.objects.get(addon=Addon.objects.get(id=15679))
            v.addon = a
            v.pk = None
            v.save()
            p = Persona(addon_id=a.id, persona_id=i)
            p.save()
            a.persona = p
            a._current_version = v
            a.status = amo.STATUS_PUBLIC
            a.save()
        base = (Addon.objects.public().filter(type=amo.ADDON_PERSONA)
                .extra(select={'_app': amo.FIREFOX.id}))
        eq_(base.count(), 5)
        r = self.client.get(reverse('browse.personas'))
        self.assertTemplateUsed(r, 'browse/personas/category_landing.html')

    def test_personas_category_landing(self):
        """Ensure we hit a grid page if there's a category and no sorting."""
        grid = 'browse/personas/grid.html'
        landing = 'browse/personas/category_landing.html'

        category = Category(type=amo.ADDON_PERSONA, slug='abc',
            application=Application.objects.get(id=amo.FIREFOX.id))
        category.save()
        category_url = reverse('browse.personas', args=[category.slug])

        r = self.client.get(category_url + '?sort=created')
        self.assertTemplateUsed(r, grid)

        r = self.client.get(category_url)
        self.assertTemplateUsed(r, grid)

        # Category with 5 add-ons should bring us to a landing page.
        category.count = 5
        category.save()
        r = self.client.get(category_url)
        self.assertTemplateUsed(r, landing)


class TestMobileFeatured(TestMobile):

    def test_featured(self):
        r = self.client.get(reverse('browse.featured'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'browse/mobile/featured.html')


class TestMobileExtensions(TestMobile):

    def test_extensions(self):
        r = self.client.get(reverse('browse.extensions'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'browse/mobile/extensions.html')
        eq_(r.context['category'], None)

    def test_category(self):
        cat = Category.objects.all()[0]
        r = self.client.get(reverse('browse.extensions', args=[cat.slug]))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'browse/mobile/extensions.html')
        eq_(r.context['category'], cat)


class TestMobilePersonas(TestMobile):
    fixtures = TestMobile.fixtures + ['addons/persona']

    def test_personas_home(self):
        r = self.client.get(reverse('browse.personas'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r,
            'browse/personas/mobile/category_landing.html')
        eq_(r.context['category'], None)
        assert 'is_homepage' in r.context

    def test_personas_home_title(self):
        r = self.client.get(reverse('browse.personas'))
        doc = pq(r.content)
        eq_(doc('title').text(), 'Personas :: Add-ons for Firefox')

    def test_personas_search(self):
        r = self.client.get(reverse('browse.personas'))
        eq_(r.context['search_cat'], 'personas')
        s = pq(r.content)('#search')
        eq_(s.attr('action'), reverse('search.search'))
        eq_(s.find('input[name=q]').attr('placeholder'), 'search for personas')
        eq_(s.find('input[name=cat]').val(), 'personas')

    def _create_persona_cat(self):
        category = Category(type=amo.ADDON_PERSONA, slug='xxx',
                            application_id=amo.FIREFOX.id)
        category.save()
        return category

    def test_personas_grid(self):
        """Ensure we always hit grid page if there's a category or sorting."""
        grid = 'browse/personas/mobile/grid.html'

        category = self._create_persona_cat()
        category_url = reverse('browse.personas', args=[category.slug])

        # Even if the category has 5 add-ons.
        category.count = 5
        category.save()
        r = self.client.get(category_url)
        self.assertTemplateUsed(r, grid)

        # Show the grid page even with sorting.
        r = self.client.get(reverse('browse.personas') + '?sort=created')
        self.assertTemplateUsed(r, grid)
        r = self.client.get(category_url + '?sort=created')
        self.assertTemplateUsed(r, grid)

    def test_personas_category_title(self):
        r = self.client.get(reverse('browse.personas',
                                    args=[self._create_persona_cat().slug]))
        doc = pq(r.content)
        eq_(doc('title').text(), 'None Personas :: Add-ons for Firefox')

    def test_personas_sorting_title(self):
        r = self.client.get(reverse('browse.personas') + '?sort=up-and-coming')
        doc = pq(r.content)
        eq_(doc('title').text(), 'Up & Coming Personas :: Add-ons for Firefox')
