from django import http

import mock
import test_utils
from nose.tools import eq_

from addons.models import Addon
from addons import decorators as dec


class TestAddonView(test_utils.TestCase):

    def setUp(self):
        self.addon = Addon.objects.create(slug='x', type=1)
        self.func = mock.Mock()
        self.func.return_value = mock.sentinel.OK
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
