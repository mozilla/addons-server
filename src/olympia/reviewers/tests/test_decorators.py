from django import http

from unittest import mock
from urllib.parse import quote

from olympia.amo.tests import TestCase, addon_factory
from olympia.reviewers import decorators as dec
from olympia.reviewers.views import reviewer_addon_view_factory


class TestReviewerAddonView(TestCase):
    def setUp(self):
        super().setUp()
        self.addon = addon_factory()
        self.func = mock.Mock()
        self.func.return_value = mock.sentinel.OK
        self.func.__name__ = 'mock_function'
        self.view = dec.reviewer_addon_view(self.func)
        self.request = mock.Mock()
        self.slug_path = 'http://testserver/addon/%s/reviews' % quote(
            self.addon.slug.encode('utf-8')
        )
        self.request.path = self.id_path = (
            'http://testserver/addon/%s/reviews' % self.addon.id
        )
        self.request.GET = {}

    def test_200_by_id(self):
        res = self.view(self.request, str(self.addon.id))
        assert res == mock.sentinel.OK

    def test_301_by_slug(self):
        self.request.path = self.slug_path
        res = self.view(self.request, self.addon.slug)
        self.assert3xx(res, self.id_path, 301)

    def test_301_by_guid(self):
        self.request.path = f'http://testserver/addon/{quote(self.addon.guid)}/reviews'
        res = self.view(self.request, self.addon.guid)
        self.assert3xx(res, self.id_path, 301)

    def test_slug_replace_no_conflict(self):
        slug = quote(self.addon.slug.encode('utf8'))
        self.request.path = f'http://testserver/addon/{slug}/reviews/{slug}/path'

        res = self.view(self.request, self.addon.slug)
        redirection = f'http://testserver/addon/{self.addon.id}/reviews/{slug}/path'

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


class TestReviewerAddonViewWithUnlisted(TestReviewerAddonView):
    def setUp(self):
        super().setUp()
        self.view = reviewer_addon_view_factory(self.func)

    @mock.patch(
        'olympia.access.acl.check_unlisted_addons_viewer_or_reviewer', lambda r: False
    )
    @mock.patch(
        'olympia.access.acl.check_addon_ownership', lambda *args, **kwargs: False
    )
    def test_unlisted_addon(self):
        """Return a 404 for non authorized access."""
        self.make_addon_unlisted(self.addon)
        with self.assertRaises(http.Http404):
            self.view(self.request, str(self.addon.id))

    @mock.patch(
        'olympia.access.acl.check_unlisted_addons_viewer_or_reviewer', lambda r: True
    )
    def test_unlisted_addon_unlisted_reviewer(self):
        """Unlisted addon reviewers have access."""
        self.make_addon_unlisted(self.addon)
        assert self.view(self.request, str(self.addon.id)) == mock.sentinel.OK
        request, addon = self.func.call_args[0]
        assert addon == self.addon
