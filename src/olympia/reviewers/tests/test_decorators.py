from django import http

from unittest import mock
from urllib.parse import quote

from olympia.amo.tests import TestCase, addon_factory
from olympia.reviewers import decorators as dec


class TestReviewerAddonView(TestCase):
    def setUp(self):
        super().setUp()
        self.addon = addon_factory()
        self.func = mock.Mock()
        self.func.return_value = mock.sentinel.OK
        self.func.__name__ = 'mock_function'
        self.view = dec.reviewer_addon_view(self.func)
        self.request = mock.Mock()
        self.request.path = self.id_path = (
            'http://testserver/addon/%s/reviews' % self.addon.id
        )
        self.request.GET = {}

    def test_200_by_id(self):
        res = self.view(self.request, str(self.addon.id))
        assert res == mock.sentinel.OK

    def test_301_by_slug(self):
        self.request.path = f'http://testserver/addon/{self.addon.slug}/reviews'
        res = self.view(self.request, self.addon.slug)
        self.assert3xx(res, self.id_path, 301)

    def test_301_by_guid(self):
        self.request.path = f'http://testserver/addon/{self.addon.guid}/reviews'
        res = self.view(self.request, self.addon.guid)
        self.assert3xx(res, self.id_path, 301)

    def test_slug_replace_no_conflict(self):
        slug = self.addon.slug
        self.request.path = f'http://testserver/addon/{slug}/reviews/{slug}/path'

        res = self.view(self.request, self.addon.slug)
        # We only replace the part of the URL that matters to look up the
        # add-on (in this case, the slug, only once).
        redirection = (
            f'http://testserver/addon/{self.addon.id}/reviews/{quote(slug)}/path'
        )

        self.assert3xx(res, redirection, 301)

    def test_301_with_querystring(self):
        self.request.GET = mock.Mock()
        self.request.GET.urlencode.return_value = 'q=1'
        res = self.view(self.request, self.addon.slug)
        self.assert3xx(res, self.id_path + '?q=1', 301)

    def test_404_by_id(self):
        with self.assertRaises(http.Http404):
            self.view(self.request, str(self.addon.id * 2))

    def test_404_by_slug(self):
        with self.assertRaises(http.Http404):
            self.view(self.request, self.addon.slug + 'xx')

    def test_slug_isdigit(self):
        addon = addon_factory()
        addon.update(slug=str(addon.id))
        res = self.view(self.request, addon.slug)
        assert res == mock.sentinel.OK
        request, addon_ = self.func.call_args[0]
        assert addon_ == addon
