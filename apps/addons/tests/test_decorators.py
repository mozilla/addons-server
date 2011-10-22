from django import http

import mock
from nose.tools import eq_
from test_utils import RequestFactory

import amo.tests
from addons.models import Addon
from addons import decorators as dec


class TestAddonView(amo.tests.TestCase):

    def setUp(self):
        self.addon = Addon.objects.create(slug='x', type=1)
        self.func = mock.Mock()
        self.func.return_value = mock.sentinel.OK
        self.func.__name__ = 'mock_function'
        self.view = dec.addon_view(self.func)
        self.request = mock.Mock()
        self.slug_path = '/addon/%s/reviews' % self.addon.slug
        self.request.path = self.id_path = '/addon/%s/reviews' % self.addon.id
        self.request.GET = {}

    def test_301_by_id(self):
        r = self.view(self.request, str(self.addon.id))
        eq_(r.status_code, 301)
        eq_(r['Location'], self.slug_path)

    def test_301_with_querystring(self):
        self.request.GET = mock.Mock()
        self.request.GET.urlencode.return_value = 'q=1'
        r = self.view(self.request, str(self.addon.id))
        eq_(r.status_code, 301)
        eq_(r['Location'], self.slug_path + '?q=1')

    def test_200_by_slug(self):
        r = self.view(self.request, self.addon.slug)
        eq_(r, mock.sentinel.OK)

    def test_404_by_id(self):
        with self.assertRaises(http.Http404):
            self.view(self.request, str(self.addon.id * 2))

    def test_404_by_slug(self):
        with self.assertRaises(http.Http404):
            self.view(self.request, self.addon.slug + 'xx')

    def test_alternate_qs_301_by_id(self):
        qs = lambda: Addon.objects.filter(type=1)
        view = dec.addon_view_factory(qs=qs)(self.func)
        r = view(self.request, str(self.addon.id))
        eq_(r.status_code, 301)
        eq_(r['Location'], self.slug_path)

    def test_alternate_qs_200_by_slug(self):
        qs = lambda: Addon.objects.filter(type=1)
        view = dec.addon_view_factory(qs=qs)(self.func)
        r = view(self.request, self.addon.slug)
        eq_(r, mock.sentinel.OK)

    def test_alternate_qs_404_by_id(self):
        qs = lambda: Addon.objects.filter(type=2)
        view = dec.addon_view_factory(qs=qs)(self.func)
        with self.assertRaises(http.Http404):
            view(self.request, str(self.addon.id))

    def test_alternate_qs_404_by_slug(self):
        qs = lambda: Addon.objects.filter(type=2)
        view = dec.addon_view_factory(qs=qs)(self.func)
        with self.assertRaises(http.Http404):
            view(self.request, self.addon.slug)

    def test_addon_no_slug(self):
        a = Addon.objects.create(type=1, name='xxxx')
        r = self.view(self.request, a.slug)
        eq_(r, mock.sentinel.OK)

    def test_slug_isdigit(self):
        a = Addon.objects.create(type=1, name='xxxx')
        a.update(slug=str(a.id))
        r = self.view(self.request, a.slug)
        eq_(r, mock.sentinel.OK)
        request, addon = self.func.call_args[0]
        eq_(addon, a)

    def test_app(self):
        a = Addon.objects.create(type=amo.ADDON_WEBAPP, name='xxxx')
        a.update(slug=str(a.id) + 'foo', app_slug=str(a.id))
        r = self.view(self.request, app_slug=str(a.id))
        eq_(r, mock.sentinel.OK)
        eq_(self.func.call_args[0][1].type, amo.ADDON_WEBAPP)


class TestPremiumDecorators(amo.tests.TestCase):

    def setUp(self):
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.func = mock.Mock()
        self.func.return_value = True
        self.func.__name__ = 'mock_function'

    def test_cant_become_premium(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        view = dec.can_become_premium(self.func)
        res = view(RequestFactory().get('/'), self.addon.pk, self.addon)
        eq_(res.status_code, 403)

    def test_can_become_premium(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        view = dec.can_become_premium(self.func)
        assert view(RequestFactory().get('/'), self.addon.pk, self.addon)
