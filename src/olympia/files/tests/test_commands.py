from django.core.management import call_command

from olympia import amo
from olympia.addons.models import Addon
from olympia.applications.models import AppVersion
from olympia.files.models import File, WebextPermission
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import parse_addon
from olympia.versions.models import Version


class TestWebextExtractPermissions(UploadTest):
    def setUp(self):
        super(TestWebextExtractPermissions, self).setUp()
        appver = {amo.FIREFOX: ['3.0', '3.6', '3.6.*', '4.0b6'],
                  amo.MOBILE: ['0.1', '2.0a1pre']}
        for app, versions in appver.items():
            for version in versions:
                AppVersion(application=app.id, version=version).save()
        self.platform = amo.PLATFORM_MAC.id
        self.addon = Addon.objects.create(guid='guid@jetpack',
                                          type=amo.ADDON_EXTENSION,
                                          name='xxx')
        self.version = Version.objects.create(addon=self.addon)

    def test_extract(self):
        upload = self.get_upload('webextension_no_id.xpi')
        parsed_data = parse_addon(upload)
        # Delete the permissions from the parsed data so they aren't added.
        del parsed_data['permissions']
        file_ = File.from_upload(upload, self.version, self.platform,
                                 parsed_data=parsed_data)
        assert WebextPermission.objects.count() == 0
        assert file_.webext_permissions_list == []

        call_command('extract_permissions')

        file_ = File.objects.no_cache().get(id=file_.id)
        assert WebextPermission.objects.get(file=file_)
        permissions_list = file_.webext_permissions_list
        assert len(permissions_list) == 5
        assert permissions_list == [u'http://*/*', u'https://*/*', 'bookmarks',
                                    'made up permission', 'https://google.com/'
                                    ]

    def test_force_extract(self):
        upload = self.get_upload('webextension_no_id.xpi')
        parsed_data = parse_addon(upload)
        # change the permissions so we can tell they've been re-parsed.
        parsed_data['permissions'].pop()
        file_ = File.from_upload(upload, self.version, self.platform,
                                 parsed_data=parsed_data)
        assert WebextPermission.objects.count() == 1
        assert len(file_.webext_permissions_list) == 4

        call_command('extract_permissions', force=True)

        file_ = File.objects.no_cache().get(id=file_.id)
        assert WebextPermission.objects.get(file=file_)
        assert len(file_.webext_permissions_list) == 5
