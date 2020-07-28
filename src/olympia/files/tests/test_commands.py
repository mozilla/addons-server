# -*- coding: utf-8 -*-
from django.conf import settings
from django.core.management import call_command

from unittest import mock

from olympia import amo
from olympia.addons.models import Addon
from olympia.applications.models import AppVersion
from olympia.files.models import File
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import parse_addon
from olympia.versions.models import Version
from olympia.users.models import UserProfile


class TestExtractOptionalPermissions(UploadTest):
    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MAX_VERSION
        }
        for version in versions:
            AppVersion.objects.create(application=amo.FIREFOX.id,
                                      version=version)
            AppVersion.objects.create(application=amo.ANDROID.id,
                                      version=version)

    def setUp(self):
        super(TestExtractOptionalPermissions, self).setUp()
        self.platform = amo.PLATFORM_ALL.id
        self.addon = Addon.objects.create(guid='guid@webext',
                                          type=amo.ADDON_EXTENSION,
                                          name='xxx')
        self.version = Version.objects.create(addon=self.addon)
        UserProfile.objects.create(pk=settings.TASK_USER_ID)

    def test_extract(self):
        upload = self.get_upload('webextension_no_id.xpi')
        parsed_data = parse_addon(upload, user=mock.Mock())

        # Remove the optional permissions from the parsed data so they aren't
        # added.
        pdata_optional_permissions = parsed_data.pop('optional_permissions')
        file_ = File.from_upload(upload, self.version, self.platform,
                                 parsed_data=parsed_data)
        assert file_.optional_permissions == []

        call_command('extract_optional_permissions')

        file_ = File.objects.get(id=file_.id)
        optional_permissions = file_.optional_permissions
        assert len(optional_permissions) == 2
        assert optional_permissions == pdata_optional_permissions
