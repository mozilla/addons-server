from django import http
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist

import pytest
from mock import Mock, patch

import amo.tests
from access import acl
from files.decorators import allowed


class AllowedTest(amo.tests.TestCase):

    def setUp(self):
        super(AllowedTest, self).setUp()
        self.request = Mock()
        self.file = Mock()

    @patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: True)
    def test_owner_allowed(self):
        assert allowed(self.request, self.file)

    @patch.object(acl, 'check_addons_reviewer', lambda x: True)
    @patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    def test_reviewer_allowed(self):
        assert allowed(self.request, self.file)

    @patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_viewer_unallowed(self):
        with pytest.raises(PermissionDenied):
            allowed(self.request, self.file)

    def test_addon_not_found(self):
        class MockVersion:
            @property
            def addon(self):
                raise ObjectDoesNotExist
        self.file.version = MockVersion()
        with pytest.raises(http.Http404):
            allowed(self.request, self.file)

    def get_unlisted_addon_file(self):
        addon = amo.tests.addon_factory(is_listed=False)
        return addon, addon.versions.get().files.get()

    @patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_unlisted_viewer_unallowed(self):
        addon, file_ = self.get_unlisted_addon_file()
        with pytest.raises(http.Http404):
            allowed(self.request, file_)

    @patch.object(acl, 'check_addons_reviewer', lambda x: True)
    @patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_unlisted_reviewer_unallowed(self):
        addon, file_ = self.get_unlisted_addon_file()
        with pytest.raises(http.Http404):
            allowed(self.request, file_)

    @patch.object(acl, 'check_addons_reviewer', lambda x: True)
    @patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: True)
    def test_unlisted_admin_reviewer_allowed(self):
        addon, file_ = self.get_unlisted_addon_file()
        assert allowed(self.request, file_)

    @patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: True)
    def test_unlisted_owner_allowed(self):
        addon, file_ = self.get_unlisted_addon_file()
        assert allowed(self.request, file_)
