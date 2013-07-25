# -*- coding: utf-8 -*-
import mock
import os.path
from nose.tools import eq_

from django.conf import settings

import amo
import amo.tests
from addons.models import Addon
from files.models import Platform
from files.tests.test_models import UploadTest as BaseUploadTest
from mkt.site.fixtures import fixture
from versions.models import Version


class TestVersion(BaseUploadTest, amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'platforms_all')

    def test_developer_name(self):
        version = Version.objects.latest('id')
        version.update(_developer_name='')
        eq_(version.developer_name, version.addon.authors.all()[0].name)

        version._developer_name = u'M€lâ'
        eq_(version.developer_name, u'M€lâ')
        eq_(Version(_developer_name=u'M€lâ').developer_name, u'M€lâ')

    @mock.patch('files.utils.parse_addon')
    def test_developer_name_from_upload(self, parse_addon):
        parse_addon.return_value = {
            'version': '42.0',
            'developer_name': u'Mýself'
        }
        addon = Addon.objects.get(pk=337141)
        # Note: we need a valid FileUpload instance, but in the end we are not
        # using its contents since we are mocking parse_addon().
        path = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                                       'addons', 'mozball.webapp')
        upload = self.get_upload(abspath=path, is_webapp=True)
        platform = Platform.objects.get(pk=amo.PLATFORM_ALL.id)
        version = Version.from_upload(upload, addon, [platform])
        eq_(version.version, '42.0')
        eq_(version.developer_name, u'Mýself')

    @mock.patch('files.utils.parse_addon')
    def test_long_developer_name_from_upload(self, parse_addon):
        truncated_developer_name = u'ý' * 255
        long_developer_name = truncated_developer_name + u'àààà'
        parse_addon.return_value = {
            'version': '42.1',
            'developer_name': long_developer_name
        }
        addon = Addon.objects.get(pk=337141)
        # Note: we need a valid FileUpload instance, but in the end we are not
        # using its contents since we are mocking parse_addon().
        path = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                                       'addons', 'mozball.webapp')
        upload = self.get_upload(abspath=path, is_webapp=True)
        platform = Platform.objects.get(pk=amo.PLATFORM_ALL.id)
        version = Version.from_upload(upload, addon, [platform])
        eq_(version.version, '42.1')
        eq_(version.developer_name, truncated_developer_name)

    def test_is_privileged_hosted_app(self):
        addon = Addon.objects.get(pk=337141)
        eq_(addon.current_version.is_privileged, False)

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_is_privileged_app(self, get_manifest_json):
        get_manifest_json.return_value = {
            'type': 'privileged'
        }
        addon = Addon.objects.get(pk=337141)
        addon.update(is_packaged=True)
        eq_(addon.current_version.is_privileged, True)

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_is_privileged_non_privileged_app(self, get_manifest_json):
        get_manifest_json.return_value = {
        }
        addon = Addon.objects.get(pk=337141)
        addon.update(is_packaged=True)
        eq_(addon.current_version.is_privileged, False)

    @mock.patch('mkt.webapps.tasks.update_cached_manifests')
    @mock.patch('files.utils.parse_addon')
    def test_upload_new_version_when_incomplete(self, parse_addon, dummy):
        parse_addon.return_value = {
            'version': '1.1',
            'developer_name': 'A-Team'
        }

        addon = Addon.objects.get(pk=337141)
        addon.update(is_packaged=True)
        addon.latest_version.delete()
        eq_(addon.reload().status, amo.STATUS_NULL)

        # Note: we need a valid FileUpload instance, but in the end we are not
        # using its contents since we are mocking parse_addon().
        path = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                                       'addons', 'mozball.webapp')
        upload = self.get_upload(abspath=path, is_webapp=True)
        platform = Platform.objects.get(pk=amo.PLATFORM_ALL.id)
        Version.from_upload(upload, addon, [platform])

        eq_(addon.reload().status, amo.STATUS_PENDING)
