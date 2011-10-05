# -*- coding: utf8 -*-
import json
import urllib
import urlparse

from django.http import QueryDict
from django.test import client

from mock import Mock, patch
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from applications.models import AppVersion
from addons.tests.test_views import TestMobile
from search.tests import SphinxTestCase
from search import views
from search.client import SearchError
from addons.models import Addon, Category, Persona
from tags.models import AddonTag, Tag


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


class MobileSearchTest(SphinxTestCase, TestMobile):

    def test_search(self):
        r = self.client.get(reverse('search.search'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/mobile/results.html')


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

    def test_legacy_redirects(self):
        base = reverse('search.es_search')
        r = self.client.get(base + '?sort=averagerating')
        self.assertRedirects(r, base + '?sort=rating', status_code=301)

    def assert_ajax_query(self, params, addons=[]):
        r = self.client.get(reverse('search.ajax') + '?' + params)
        eq_(r.status_code, 200)
        data = json.loads(r.content)

        data = sorted(data, key=lambda x: x['id'])
        addons = sorted(addons, key=lambda x: x.id)

        eq_(len(data), len(addons))
        for got, expected in zip(data, addons):
            eq_(got['id'], expected.id)
            eq_(got['label'], unicode(expected.name))
            eq_(got['url'], expected.get_url_path())
            eq_(got['icon'], expected.icon_url)

            assert expected.status in amo.REVIEWED_STATUSES, (
                'Unreviewed add-ons should not appear in search results.')
            eq_(expected.is_disabled, False)
            assert expected.type in amo.ADDON_SEARCH_TYPES, (
                'Add-on type %s should not be searchable.' % addon.type)

    def test_ajax_search_by_id(self):
        addon = Addon.objects.get(id=4)
        self.assert_ajax_query('q=4', [addon])

    def test_ajax_search_by_bad_id(self):
        self.assert_ajax_query('q=999', [])

    def test_ajax_search_unreviewed_by_id(self):
        addon = Addon.objects.get(id=4)
        addon.update(status=amo.STATUS_UNREVIEWED)
        self.assert_ajax_query('q=999', [])

    def test_ajax_search_lite_reviewed_by_id(self):
        addon = Addon.objects.get(id=4)
        addon.update(status=amo.STATUS_LITE)
        self.assert_ajax_query('q=4', [addon])

        addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.assert_ajax_query('q=4', [addon])

    def test_ajax_search_user_disabled_by_id(self):
        addon = Addon.objects.get(id=1)
        eq_(addon.disabled_by_user, True)
        self.assert_ajax_query('q=1', [])

    def test_ajax_search_admin_disabled_by_id(self):
        addon = Addon.objects.get(id=2)
        eq_(addon.status, amo.STATUS_DISABLED)
        self.assert_ajax_query('q=1', [])

    def test_ajax_search_personas_by_id(self):
        addon = Addon.objects.get(id=4)
        addon.update(type=amo.ADDON_PERSONA)
        Persona.objects.create(persona_id=4, addon_id=4)
        self.assert_ajax_query('q=4', [addon])
        self.assert_ajax_query('q=4&exclude_personas=true', [])

    def test_ajax_search_char_limit(self):
        self.assert_ajax_query('q=ad', [])

    def test_ajax_search_by_name(self):
        raise SkipTest
        # Exclude the following:
        # 1 (user-disabled), 2 (admin-disabled), 3 (unreviewed).
        self.assert_ajax_query('q=add',
            list(Addon.objects.filter(id__in=[4, 5, 6])))

    def test_ajax_search_by_bad_name(self):
        self.assert_ajax_query('q=some+filthy+bad+word', [])


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
        self.assertTemplateUsed(r, 'search/es_results.html')

    @amo.tests.mobile_test
    def test_mobile_get(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/mobile/es_results.html')
