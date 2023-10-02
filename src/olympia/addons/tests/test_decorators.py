from unittest import mock
from urllib.parse import quote

from django import http

from olympia.addons import decorators as dec
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory


class TestAddonView(TestCase):
    def setUp(self):
        super().setUp()
        self.addon = addon_factory()
        self.func = mock.Mock()
        self.func.return_value = mock.sentinel.OK
        self.func.__name__ = 'mock_function'
        self.view = dec.addon_view(self.func)
        self.request = mock.Mock()
        self.slug_path = 'http://testserver/addon/%s/reviews' % quote(
            self.addon.slug.encode('utf-8')
        )
        self.request.path = self.id_path = (
            'http://testserver/addon/%s/reviews' % self.addon.id
        )
        self.request.GET = {}

    def test_301_by_id(self):
        res = self.view(self.request, str(self.addon.id))
        self.assert3xx(res, self.slug_path, 301)

    def test_301_by_guid(self):
        self.request.path = 'http://testserver/addon/%s/reviews' % self.addon.guid
        res = self.view(self.request, str(self.addon.guid))
        self.assert3xx(res, self.slug_path, 301)

    def test_slug_replace_no_conflict(self):
        path = 'http://testserver/addon/{id}/reviews/{id}345/path'
        self.request.path = path.format(id=self.addon.id)

        res = self.view(self.request, str(self.addon.id))
        redirection = 'http://testserver/addon/{slug}/reviews/{id}345/path'.format(
            id=self.addon.id, slug=quote(self.addon.slug.encode('utf8'))
        )
        self.assert3xx(res, redirection, 301)

    def test_301_with_querystring(self):
        self.request.GET = mock.Mock()
        self.request.GET.urlencode.return_value = 'q=1'
        res = self.view(self.request, str(self.addon.id))
        self.assert3xx(res, self.slug_path + '?q=1', 301)

    def test_200_by_slug(self):
        res = self.view(self.request, self.addon.slug)
        assert res == mock.sentinel.OK

    def test_404_by_id(self):
        with self.assertRaises(http.Http404):
            self.view(self.request, str(self.addon.id * 2))

    def test_404_by_slug(self):
        with self.assertRaises(http.Http404):
            self.view(self.request, self.addon.slug + 'xx')

    def test_alternate_qs_301_by_id(self):
        def qs():
            return Addon.objects.filter(type=1)

        view = dec.addon_view_factory(qs=qs)(self.func)
        res = view(self.request, str(self.addon.id))
        self.assert3xx(res, self.slug_path, 301)

    def test_alternate_qs_200_by_slug(self):
        def qs():
            return Addon.objects.filter(type=1)

        view = dec.addon_view_factory(qs=qs)(self.func)
        res = view(self.request, self.addon.slug)
        assert res == mock.sentinel.OK

    def test_alternate_qs_404_by_id(self):
        def qs():
            return Addon.objects.filter(type=2)

        view = dec.addon_view_factory(qs=qs)(self.func)
        with self.assertRaises(http.Http404):
            view(self.request, str(self.addon.id))

    def test_alternate_qs_404_by_slug(self):
        def qs():
            return Addon.objects.filter(type=2)

        view = dec.addon_view_factory(qs=qs)(self.func)
        with self.assertRaises(http.Http404):
            view(self.request, self.addon.slug)

    def test_addon_no_slug(self):
        addon = addon_factory(slug=None)
        res = self.view(self.request, addon.slug)
        assert res == mock.sentinel.OK

    def test_slug_isdigit(self):
        addon = addon_factory()
        addon.update(slug=str(addon.id))
        r = self.view(self.request, addon.slug)
        assert r == mock.sentinel.OK
        request, addon_ = self.func.call_args[0]
        assert addon_ == addon

    @mock.patch(
        'olympia.access.acl.is_unlisted_addons_viewer_or_reviewer', lambda user: False
    )
    @mock.patch(
        'olympia.access.acl.check_addon_ownership', lambda *args, **kwargs: False
    )
    def test_no_versions_404(self):
        self.addon.current_version.delete()
        view = dec.addon_view_factory(qs=Addon.objects.all)(self.func)
        with self.assertRaises(http.Http404):
            view(self.request, self.addon.slug)

    @mock.patch(
        'olympia.access.acl.is_unlisted_addons_viewer_or_reviewer', lambda user: False
    )
    @mock.patch(
        'olympia.access.acl.check_addon_ownership', lambda *args, **kwargs: True
    )
    def test_no_versions_developer(self):
        self.addon.current_version.delete()
        res = self.view(self.request, self.addon.slug)
        assert res == mock.sentinel.OK

    def test_no_versions_include_deleted_when_checking(self):
        self.addon.current_version.delete()
        view = dec.addon_view(  # Not available on the factory
            self.func, qs=Addon.objects.all, include_deleted_when_checking_versions=True
        )
        res = view(self.request, self.addon.slug)
        assert res == mock.sentinel.OK


class TestAddonViewWithUnlisted(TestAddonView):
    def setUp(self):
        super().setUp()
        self.view = dec.addon_view_factory(qs=Addon.objects.all)(self.func)

    @mock.patch(
        'olympia.access.acl.is_unlisted_addons_viewer_or_reviewer', lambda user: False
    )
    @mock.patch(
        'olympia.access.acl.check_addon_ownership', lambda *args, **kwargs: False
    )
    def test_unlisted_addon(self):
        """Return a 404 for non authorized access."""
        self.make_addon_unlisted(self.addon)
        with self.assertRaises(http.Http404):
            self.view(self.request, self.addon.slug)

    @mock.patch(
        'olympia.access.acl.is_unlisted_addons_viewer_or_reviewer', lambda user: False
    )
    @mock.patch(
        'olympia.access.acl.check_addon_ownership', lambda *args, **kwargs: True
    )
    def test_unlisted_addon_owner(self):
        """Addon owners have access."""
        self.make_addon_unlisted(self.addon)
        assert self.view(self.request, self.addon.slug) == mock.sentinel.OK
        request, addon = self.func.call_args[0]
        assert addon == self.addon

    @mock.patch(
        'olympia.access.acl.is_unlisted_addons_viewer_or_reviewer', lambda user: True
    )
    @mock.patch(
        'olympia.access.acl.check_addon_ownership', lambda *args, **kwargs: False
    )
    def test_unlisted_addon_unlisted_admin(self):
        """Unlisted addon reviewers have access."""
        self.make_addon_unlisted(self.addon)
        assert self.view(self.request, self.addon.slug) == mock.sentinel.OK
        request, addon = self.func.call_args[0]
        assert addon == self.addon
