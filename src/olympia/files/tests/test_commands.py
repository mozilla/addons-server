# -*- coding: utf-8 -*-
from unittest import mock

from django.conf import settings
from django.core.management import call_command

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory
from olympia.files.models import File, FileManifest
from olympia.files.tests.test_models import UploadMixin
from olympia.files.utils import parse_addon
from olympia.users.models import UserProfile
from olympia.versions.models import AppVersion, Version


class TestExtractHostPermissions(UploadMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
        }
        for version in versions:
            AppVersion.objects.get_or_create(
                application=amo.FIREFOX.id, version=version
            )
            AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version=version
            )

    def setUp(self):
        super(TestExtractHostPermissions, self).setUp()
        self.addon = Addon.objects.create(
            guid='mv3@extension', type=amo.ADDON_EXTENSION, name='xxx'
        )
        self.version = Version.objects.create(addon=self.addon)
        UserProfile.objects.create(pk=settings.TASK_USER_ID)

    def test_extract(self):
        upload = self.get_upload('webextension_mv3.xpi')
        parsed_data = parse_addon(
            upload, addon=self.addon, user=mock.Mock(groups_list=[])
        )

        # Remove the host permissions from the parsed data so they aren't
        # added.
        pdata_host_permissions = parsed_data.pop('host_permissions')
        file_ = File.from_upload(upload, self.version, parsed_data=parsed_data)
        assert file_.host_permissions == []

        call_command('extract_host_permissions')

        file_ = File.objects.get(id=file_.id)
        host_permissions = file_.host_permissions
        assert len(host_permissions) == 2
        assert host_permissions == pdata_host_permissions


class TestBackfillFileManifest(TestCase):
    def setUp(self):
        self.addon = addon_factory(file_kw={'filename': 'unicode-filenames.xpi'})
        assert not FileManifest.objects.exists()

    def test_backfill(self):
        already_have_manifest = addon_factory(file_kw={'filename': 'webextension.xpi'})
        FileManifest.objects.create(
            manifest_data='{}', file=already_have_manifest.current_version.file
        )
        addon_factory()  # should be ignored - no file on filesystem
        addon_factory(file_kw={'filename': 'badzipfile.zip'})

        call_command('process_files', task='backfill_file_manifest')

        assert self.addon.current_version.file.file_manifest.manifest_data == {
            'applications': {
                'gecko': {
                    'id': '@webextension-guid',
                },
            },
            'description': 'just a test addon with the manifest.json format',
            'manifest_version': 2,
            'name': 'My WebExtension Addon',
            'version': '0.0.1',
        }

    def test_deleted_addon(self):
        file_ = self.addon.current_version.file
        self.addon.delete()
        call_command('process_files', task='backfill_file_manifest')

        assert file_.file_manifest.manifest_data == {
            'applications': {
                'gecko': {
                    'id': '@webextension-guid',
                },
            },
            'description': 'just a test addon with the manifest.json format',
            'manifest_version': 2,
            'name': 'My WebExtension Addon',
            'version': '0.0.1',
        }
