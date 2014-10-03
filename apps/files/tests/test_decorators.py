from django import http
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist

from mock import Mock, patch

import amo.tests
from access import acl
from files.decorators import allowed


class AllowedTest(amo.tests.TestCase):

    def setUp(self):
        self.request = Mock()
        self.file = Mock()

    @patch.object(acl, 'check_addons_reviewer', lambda x: True)
    def test_reviewer_allowed(self):
        self.assertTrue(allowed(self.request, self.file))

    @patch.object(acl, 'check_addons_reviewer', lambda x: False)
    def test_reviewer_unallowed(self):
        self.assertRaises(PermissionDenied, allowed, self.request, self.file)

    @patch.object(acl, 'check_addons_reviewer', lambda x: False)
    def test_addon_not_found(self):
        class MockVersion():
            @property
            def addon(self):
                raise ObjectDoesNotExist
        self.file.version = MockVersion()
        self.assertRaises(http.Http404, allowed, self.request, self.file)
