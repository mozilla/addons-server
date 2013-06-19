# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from email import utils

from django.db import connection

from nose.tools import eq_

import amo
import amo.tests
from addons.models import (Addon, CompatOverride, CompatOverrideRange,
                           IncompatibleVersions)
from applications.models import Application, AppVersion
from files.models import File
from services import update
import settings_local
from versions.models import ApplicationsVersions, Version


class TestDataValidate(amo.tests.TestCase):
    fixtures = ['base/addon_3615',
                'base/platforms',
                'base/apps',
                'base/appversion']

    def setUp(self):
        self.good_data = {
            'id': '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}',
            'version': '2.0.58',
            'reqVersion': 1,
            'appID': '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}',
            'appVersion': '3.7a1pre',
        }

    def get(self, data):
        up = update.Update(data)
        up.cursor = connection.cursor()
        return up

    def test_beta(self):
        data = self.good_data.copy()
        for good in ['1.0a', '1.0beta2', '1.0 beta2']:
            data['version'] = good
            form = self.get(data)
            assert form.is_valid()
            assert form.is_beta_version

        for bad in ['1.0', 'beta 1.0', '1.0 beta 2']:
            data['version'] = bad
            form = self.get(data)
            assert form.is_valid()
            assert not form.is_beta_version

    def test_app_os(self):
        data = self.good_data.copy()
        data['appOS'] = 'something %s penguin' % amo.PLATFORM_LINUX.api_name
        form = self.get(data)
        assert form.is_valid()
        eq_(form.data['appOS'], amo.PLATFORM_LINUX.id)

    def test_app_version_fails(self):
        data = self.good_data.copy()
        del data['appID']
        form = self.get(data)
        assert not form.is_valid()

    def test_app_version_wrong(self):
        data = self.good_data.copy()
        data['appVersion'] = '67.7'
        form = self.get(data)
        # If you pass through the wrong version that's fine
        # you will just end up with no updates because your
        # version_int will be out.
        assert form.is_valid()

    def test_app_version(self):
        data = self.good_data.copy()
        form = self.get(data)
        assert form.is_valid()
        eq_(form.data['version_int'], 3070000001000)

    def test_sql_injection(self):
        data = self.good_data.copy()
        data['id'] = "'"
        up = self.get(data)
        assert not up.is_valid()

    def test_inactive(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(disabled_by_user=True)

        up = self.get(self.good_data)
        assert not up.is_valid()

    def test_soft_deleted(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(status=amo.STATUS_DELETED)

        up = self.get(self.good_data)
        assert not up.is_valid()

    def test_no_version(self):
        data = self.good_data.copy()
        del data['version']
        up = self.get(data)
        assert up.is_valid()


class TestLookup(amo.tests.TestCase):
    fixtures = ['addons/update',
                'base/apps',
                'base/appversion',
                'base/platforms']

    def setUp(self):
        self.addon = Addon.objects.get(id=1865)
        self.platform = None
        self.version_int = 3069900200100

        self.app = Application.objects.get(id=1)
        self.version_1_0_2 = 66463
        self.version_1_1_3 = 90149
        self.version_1_2_0 = 105387
        self.version_1_2_1 = 112396
        self.version_1_2_2 = 115509

    def get(self, *args):
        data = {
            'id': self.addon.guid,
            'appID': args[2].guid,
            'appVersion': 1,  # this is going to be overridden
            'appOS': args[3].api_name if args[3] else '',
            'reqVersion': '',
        }
        # Allow version to be optional.
        if args[0]:
            data['version'] = args[0]
        up = update.Update(data)
        up.cursor = connection.cursor()
        assert up.is_valid()
        up.data['version_int'] = args[1]
        up.get_update()
        return (up.data['row'].get('version_id'),
                up.data['row'].get('file_id'))

    def change_status(self, version, status):
        version = Version.objects.get(pk=version)
        file = version.files.all()[0]
        file.status = status
        file.save()
        return version

    def change_version(self, version, name):
        Version.objects.get(pk=version).update(version=name)

    def test_low_client(self):
        """
        Version 3.0a1 of Firefox is 3000000001100 and version 1.0.2 of the
        add-on is returned.
        """
        version, file = self.get('', '3000000001100',
                                 self.app, self.platform)
        eq_(version, self.version_1_0_2)

    def test_new_client(self):
        """
        Version 3.0.12 of Firefox is 3069900200100 and version 1.2.2 of the
        add-on is returned.
        """
        version, file = self.get('', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_2)

    def test_min_client(self):
        """
        Version 3.7a5pre of Firefox is 3070000005000 and version 1.1.3 of
        the add-on is returned, because all later ones are set to minimum
        version of 3.7a5.
        """
        for version in Version.objects.filter(pk__gte=self.version_1_2_0):
            appversion = version.apps.all()[0]
            appversion.min = AppVersion.objects.get(pk=325)  # 3.7a5
            appversion.save()

        version, file = self.get('', '3070000005000',  # 3.7a5pre
                                 self.app, self.platform)
        eq_(version, self.version_1_1_3)

    def test_new_client_ordering(self):
        """
        Given the following:
        * Version 15 (1 day old), max application_version 3.6*
        * Version 12 (1 month old), max application_version 3.7a
        We want version 15, even though version 12 is for a higher version.
        This was found in https://bugzilla.mozilla.org/show_bug.cgi?id=615641.
        """
        application_version = ApplicationsVersions.objects.get(pk=77550)
        application_version.max_id = 350
        application_version.save()

        # Version 1.2.2 is now a lower max version.
        application_version = ApplicationsVersions.objects.get(pk=88490)
        application_version.max_id = 329
        application_version.save()

        version, file = self.get('', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_2)

    def test_public_not_beta(self):
        """
        If the addon status is public and you are not asking
        for a beta version, then you get a public version.
        """
        self.change_status(self.version_1_2_2, amo.STATUS_PENDING)
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_public_beta(self):
        """
        If the addon status is public, you are in beta and the file is
        beta, the you get a beta.
        """
        self.change_version(self.version_1_2_0, '1.2beta')
        self.change_status(self.version_1_2_0, amo.STATUS_BETA)
        self.change_status(self.version_1_2_1, amo.STATUS_BETA)

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_can_downgrade(self):
        """
        Check that we can downgrade, if 1.2.0 gets admin disabled
        and the oldest public version is now 1.1.3.
        """
        self.change_status(self.version_1_2_0, amo.STATUS_PENDING)

        Version.objects.filter(pk__gte=self.version_1_2_1).delete()
        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)

        eq_(version, self.version_1_1_3)

    def test_public_pending_exists(self):
        """
        If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. In this case, because the
        file is pending, we are looking for something public.
        """
        self.change_status(self.version_1_2_2, amo.STATUS_PENDING)
        self.change_status(self.version_1_2_0, amo.STATUS_PENDING)
        self.change_version(self.version_1_2_0, '1.2beta')

        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)

        eq_(version, self.version_1_2_1)

    def test_public_pending_no_file_beta(self):
        """
        If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. If there are no files,
        find a public version.
        """
        self.change_version(self.version_1_2_0, '1.2beta')
        Version.objects.get(pk=self.version_1_2_0).files.all().delete()

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        dest = Version.objects.get(pk=self.version_1_2_2)
        eq_(dest.addon.status, amo.STATUS_PUBLIC)
        eq_(dest.files.all()[0].status, amo.STATUS_PUBLIC)
        eq_(version, dest.pk)

    def test_public_pending_not_exists(self):
        """
        If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. In this case, because the
        file is pending, we are looking for a public version.
        """
        self.change_status(self.version_1_2_0, amo.STATUS_PENDING)
        self.change_version(self.version_1_2_0, '1.2beta')
        self.change_status(self.version_1_2_2, amo.STATUS_BETA)

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_not_public(self):
        """
        If the addon status is not public, then the update only
        looks for files within that one version.
        """
        self.change_status(self.version_1_2_2, amo.STATUS_NULL)
        self.addon.update(status=amo.STATUS_NULL)
        version, file = self.get('1.2.1', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_platform_does_not_exist(self):
        """If client passes a platform, find that specific platform."""
        version = Version.objects.get(pk=115509)
        for file in version.files.all():
            file.platform_id = amo.PLATFORM_LINUX.id
            file.save()

        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)
        eq_(version, self.version_1_2_1)

    def test_platform_exists(self):
        """If client passes a platform, find that specific platform."""
        version = Version.objects.get(pk=115509)
        for file in version.files.all():
            file.platform_id = amo.PLATFORM_LINUX.id
            file.save()

        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_LINUX)
        eq_(version, self.version_1_2_2)

    def test_file_for_platform(self):
        """If client passes a platform, make sure we get the right file."""
        version = Version.objects.get(pk=self.version_1_2_2)
        file_one = version.files.all()[0]
        file_one.platform_id = amo.PLATFORM_LINUX.id
        file_one.save()

        file_two = File(version=version, filename='foo', hash='bar',
                        platform_id=amo.PLATFORM_WIN.id,
                        status=amo.STATUS_PUBLIC)
        file_two.save()
        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_LINUX)
        eq_(version, self.version_1_2_2)
        eq_(file, file_one.pk)

        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_WIN)
        eq_(version, self.version_1_2_2)
        eq_(file, file_two.pk)

    def test_file_preliminary(self):
        """
        If there's a newer file in prelim. review it won't show up. This is
        a test for https://bugzilla.mozilla.org/show_bug.cgi?id=620749
        """
        version = Version.objects.get(pk=self.version_1_2_2)
        file = version.files.all()[0]
        file.status = amo.STATUS_LITE
        file.save()

        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_LINUX)
        eq_(version, self.version_1_2_1)

    def test_file_preliminary_addon(self):
        """
        If the addon is in prelim. review, show the highest file with
        public., which in this case is 1.2.1
        """
        for status in amo.LITE_STATUSES:
            self.addon.update(status=status)

            self.change_status(self.version_1_2_1, amo.STATUS_LITE)
            version, file = self.get('1.2', self.version_int,
                                     self.app, amo.PLATFORM_LINUX)
            eq_(version, self.version_1_2_1)


class TestDefaultToCompat(amo.tests.TestCase):
    """
    Test default to compatible with all the various combinations of input.
    """
    fixtures = ['base/platforms', 'addons/default-to-compat']

    def setUp(self):
        self.addon = Addon.objects.get(id=337203)
        self.platform = None
        self.app = Application.objects.get(id=1)
        self.app_version_int_3_0 = 3000000200100
        self.app_version_int_4_0 = 4000000200100
        self.app_version_int_5_0 = 5000000200100
        self.app_version_int_6_0 = 6000000200100
        self.app_version_int_7_0 = 7000000200100
        self.app_version_int_8_0 = 8000000200100
        self.ver_1_0 = 1268881
        self.ver_1_1 = 1268882
        self.ver_1_2 = 1268883
        self.ver_1_3 = 1268884

        self.expected = {
            '3.0-strict': None, '3.0-normal': None, '3.0-ignore': None,
            '4.0-strict': self.ver_1_0,
            '4.0-normal': self.ver_1_0,
            '4.0-ignore': self.ver_1_0,
            '5.0-strict': self.ver_1_2,
            '5.0-normal': self.ver_1_2,
            '5.0-ignore': self.ver_1_2,
            '6.0-strict': self.ver_1_3,
            '6.0-normal': self.ver_1_3,
            '6.0-ignore': self.ver_1_3,
            '7.0-strict': self.ver_1_3,
            '7.0-normal': self.ver_1_3,
            '7.0-ignore': self.ver_1_3,
            '8.0-strict': None,
            '8.0-normal': self.ver_1_3,
            '8.0-ignore': self.ver_1_3,
        }

    def create_override(self, **kw):
        co = CompatOverride.objects.create(
            name='test', guid=self.addon.guid, addon=self.addon
        )
        default = dict(compat=co, app=self.app, min_version='0',
                       max_version='*', min_app_version='0',
                       max_app_version='*')
        default.update(kw)
        CompatOverrideRange.objects.create(**default)

    def update_files(self, **kw):
        for version in self.addon.versions.all():
            for file in version.files.all():
                file.update(**kw)

    def get(self, **kw):
        up = update.Update({
            'reqVersion': 1,
            'id': self.addon.guid,
            'version': kw.get('item_version', '1.0'),
            'appID': self.app.guid,
            'appVersion': kw.get('app_version', '3.0'),
        })
        up.cursor = connection.cursor()
        assert up.is_valid()
        up.compat_mode = kw.get('compat_mode', 'strict')
        up.get_update()
        return up.data['row'].get('version_id')

    def check(self, expected):
        """
        Checks Firefox versions 3.0 to 8.0 in each compat mode and compares it
        to the expected version.
        """
        versions = ['3.0', '4.0', '5.0', '6.0', '7.0', '8.0']
        modes = ['strict', 'normal', 'ignore']

        for version in versions:
            for mode in modes:
                eq_(self.get(app_version=version, compat_mode=mode),
                    expected['-'.join([version, mode])],
                    'Unexpected version for "%s-%s"' % (version, mode))

    def test_baseline(self):
        # Tests simple add-on (non-binary-components, non-strict).
        self.check(self.expected)

    def test_binary_components(self):
        # Tests add-on with binary_components flag.
        self.update_files(binary_components=True)
        self.expected.update({
            '8.0-normal': None,
        })
        self.check(self.expected)

    def test_extension_compat_override(self):
        # Tests simple add-on (non-binary-components, non-strict) with a compat
        # override.
        self.create_override(min_version='1.3', max_version='1.3')
        self.expected.update({
            '6.0-normal': self.ver_1_2,
            '7.0-normal': self.ver_1_2,
            '8.0-normal': self.ver_1_2,
        })
        self.check(self.expected)

    def test_binary_component_compat_override(self):
        # Tests simple add-on (non-binary-components, non-strict) with a compat
        # override.
        self.update_files(binary_components=True)
        self.create_override(min_version='1.3', max_version='1.3')
        self.expected.update({
            '6.0-normal': self.ver_1_2,
            '7.0-normal': self.ver_1_2,
            '8.0-normal': None,
        })
        self.check(self.expected)

    def test_strict_opt_in(self):
        # Tests add-on with opt-in strict compatibility
        self.update_files(strict_compatibility=True)
        self.expected.update({
            '8.0-normal': None,
        })
        self.check(self.expected)

    def test_compat_override_max_addon_wildcard(self):
        # Tests simple add-on (non-binary-components, non-strict) with a compat
        # override that contains a max wildcard.
        self.create_override(min_version='1.2', max_version='1.3',
                             min_app_version='5.0', max_app_version='6.*')
        self.expected.update({
            '5.0-normal': self.ver_1_1,
            '6.0-normal': self.ver_1_1,
        })
        self.check(self.expected)

    def test_compat_override_max_app_wildcard(self):
        # Tests simple add-on (non-binary-components, non-strict) with a compat
        # override that contains a min/max wildcard for the app.

        self.create_override(min_version='1.2', max_version='1.3')
        self.expected.update({
            '5.0-normal': self.ver_1_1,
            '6.0-normal': self.ver_1_1,
            '7.0-normal': self.ver_1_1,
            '8.0-normal': self.ver_1_1,
        })
        self.check(self.expected)

    def test_compat_override_both_wildcards(self):
        # Tests simple add-on (non-binary-components, non-strict) with a compat
        # override that contains a wildcard for both addon version and app
        # version.

        self.create_override(min_app_version='7.0', max_app_version='*')
        self.expected.update({
            '7.0-normal': None,
            '8.0-normal': None,
        })
        self.check(self.expected)

    def test_compat_override_invalid_version(self):
        # Tests compat override range where version doesn't match our
        # versioning scheme. This results in no versions being written to the
        # incompatible_versions table.
        self.create_override(min_version='ver1', max_version='ver2')
        eq_(IncompatibleVersions.objects.all().count(), 0)

    def test_min_max_version(self):
        # Tests the minimum requirement of the app maxVersion.
        av = self.addon.current_version.apps.all()[0]
        av.min_id = 233  # Firefox 3.0.
        av.max_id = 268  # Firefox 3.5.
        av.save()
        self.expected.update({
            '3.0-strict': self.ver_1_3,
            '3.0-ignore': self.ver_1_3,
            '4.0-ignore': self.ver_1_3,
            '5.0-ignore': self.ver_1_3,
            '6.0-strict': self.ver_1_2,
            '6.0-normal': self.ver_1_2,
            '7.0-strict': self.ver_1_2,
            '7.0-normal': self.ver_1_2,
            '8.0-normal': self.ver_1_2,
        })
        self.check(self.expected)


class TestResponse(amo.tests.TestCase):
    fixtures = ['base/addon_3615',
                'base/platforms',
                'base/seamonkey']

    def setUp(self):
        self.addon_one = Addon.objects.get(pk=3615)
        self.good_data = {
            'id': '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}',
            'version': '2.0.58',
            'reqVersion': 1,
            'appID': '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}',
            'appVersion': '3.7a1pre',
        }

        self.mac = amo.PLATFORM_MAC
        self.win = amo.PLATFORM_WIN

        self.old_mirror_url = settings_local.MIRROR_URL
        self.old_local_url = settings_local.LOCAL_MIRROR_URL
        self.old_debug = settings_local.DEBUG

        settings_local.MIRROR_URL = 'http://releases.m.o/'
        settings_local.LOCAL_MIRROR_URL = 'http://addons.m.o/'
        settings_local.DEBUG = False

    def get(self, data):
        up = update.Update(data)
        up.cursor = connection.cursor()
        return up

    def tearDown(self):
        settings_local.MIRROR_URL = self.old_mirror_url
        settings_local.LOCAL_MIRROR_URL = self.old_local_url
        settings_local.DEBUG = self.old_debug

    def test_bad_guid(self):
        data = self.good_data.copy()
        data["id"] = "garbage"
        up = self.get(data)
        eq_(up.get_rdf(), up.get_bad_rdf())

    def test_no_platform(self):
        file = File.objects.get(pk=67442)
        file.platform_id = self.win.id
        file.save()

        data = self.good_data.copy()
        data["appOS"] = self.win.api_name
        up = self.get(data)
        assert up.get_rdf()
        eq_(up.data['row']['file_id'], file.pk)

        data["appOS"] = self.mac.api_name
        up = self.get(data)
        eq_(up.get_rdf(), up.get_no_updates_rdf())

    def test_different_platform(self):
        file = File.objects.get(pk=67442)
        file.platform_id = self.win.id
        file.save()
        file_pk = file.pk

        file.id = None
        file.platform_id = self.mac.id
        file.save()
        mac_file_pk = file.pk

        data = self.good_data.copy()
        data['appOS'] = self.win.api_name
        up = self.get(data)
        up.is_valid()
        up.get_update()
        eq_(up.data['row']['file_id'], file_pk)

        data['appOS'] = self.mac.api_name
        up = self.get(data)
        up.is_valid()
        up.get_update()
        eq_(up.data['row']['file_id'], mac_file_pk)

    def test_good_version(self):
        up = self.get(self.good_data)
        up.is_valid()
        up.get_update()
        assert up.data['row']['hash'].startswith('sha256:3808b13e')
        eq_(up.data['row']['min'], '2.0')
        eq_(up.data['row']['max'], '4.0')

    def test_beta_version(self):
        file = File.objects.get(pk=67442)
        file.status = amo.STATUS_BETA
        file.save()

        beta_version = '2.0.58 beta'

        version = file.version
        version.version = beta_version
        version.save()

        data = self.good_data.copy()
        up = self.get(data)
        up.is_valid()
        assert not up.get_update()

        data["version"] = beta_version
        up = self.get(data)
        up.is_valid()
        up.get_update()
        eq_(up.data['row']['file_id'], file.pk)

    def test_no_app_version(self):
        data = self.good_data.copy()
        data['appVersion'] = '1.4'
        up = self.get(data)
        up.is_valid()
        assert not up.get_update()

    def test_low_app_version(self):
        data = self.good_data.copy()
        data['appVersion'] = '2.0'
        up = self.get(data)
        up.is_valid()
        up.get_update()
        assert up.data['row']['hash'].startswith('sha256:3808b13e')
        eq_(up.data['row']['min'], '2.0')
        eq_(up.data['row']['max'], '4.0')

    def test_content_type(self):
        up = self.get(self.good_data)
        ('Content-Type', 'text/xml') in up.get_headers(1)

    def test_cache_control(self):
        up = self.get(self.good_data)
        ('Cache-Control', 'public, max-age=3600') in up.get_headers(1)

    def test_length(self):
        up = self.get(self.good_data)
        ('Cache-Length', '1') in up.get_headers(1)

    def test_expires(self):
        """Check there are these headers and that expires is 3600 later."""
        # We aren't bother going to test the actual time in expires, that
        # way lies pain with broken tests later.
        up = self.get(self.good_data)
        hdrs = dict(up.get_headers(1))
        lm = datetime(*utils.parsedate_tz(hdrs['Last-Modified'])[:7])
        exp = datetime(*utils.parsedate_tz(hdrs['Expires'])[:7])
        eq_((exp - lm).seconds, 3600)

    def test_appguid(self):
        up = self.get(self.good_data)
        rdf = up.get_rdf()
        assert rdf.find(self.good_data['appID']) > -1

    def test_url(self):
        up = self.get(self.good_data)
        up.get_rdf()
        assert settings_local.MIRROR_URL in up.data['row']['url']

    def test_url_local_recent(self):
        a_bit_ago = datetime.now() - timedelta(seconds=60)
        File.objects.get(pk=67442).update(datestatuschanged=a_bit_ago)
        up = self.get(self.good_data)
        up.get_rdf()
        assert settings_local.LOCAL_MIRROR_URL in up.data['row']['url']

    def test_url_remote_beta(self):
        file = File.objects.get(pk=67442)
        file.status = amo.STATUS_BETA
        file.save()

        beta_version = '2.0.58 beta'
        file.version.update(version=beta_version)

        data = self.good_data.copy()
        data["version"] = beta_version
        up = self.get(data)
        self.addon_one.status = amo.STATUS_PUBLIC
        self.addon_one.save()
        up.get_rdf()
        eq_(up.data['row']['file_id'], file.pk)
        assert settings_local.MIRROR_URL in up.data['row']['url']

    def test_hash(self):
        rdf = self.get(self.good_data).get_rdf()
        assert rdf.find('updateHash') > -1

        file = File.objects.get(pk=67442)
        file.hash = ''
        file.save()

        rdf = self.get(self.good_data).get_rdf()
        eq_(rdf.find('updateHash'), -1)

    def test_releasenotes(self):
        rdf = self.get(self.good_data).get_rdf()
        assert rdf.find('updateInfoURL') > -1

        version = Version.objects.get(pk=81551)
        version.update(releasenotes=None)

        rdf = self.get(self.good_data).get_rdf()
        eq_(rdf.find('updateInfoURL'), -1)

    def test_sea_monkey(self):
        data = {
            'id': 'bettergmail2@ginatrapani.org',
            'version': '1',
            'appID': '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}',
            'reqVersion': 1,
            'appVersion': '1.0',
        }
        up = self.get(data)
        rdf = up.get_rdf()
        assert up.data['row']['hash'].startswith('sha256:9d9a389')
        eq_(up.data['row']['min'], '1.0')
        eq_(up.data['row']['version'], '0.5.2')
        assert rdf.find(data['appID']) > -1

    def test_no_updates_at_all(self):
        self.addon_one.versions.all().delete()
        upd = self.get(self.good_data)
        eq_(upd.get_rdf(), upd.get_no_updates_rdf())

    def test_no_updates_my_fx(self):
        data = self.good_data.copy()
        data['appVersion'] = '5.0.1'
        upd = self.get(data)
        eq_(upd.get_rdf(), upd.get_no_updates_rdf())
