# -*- coding: utf-8 -*-
import json
import os

from datetime import datetime, timedelta

from django.conf import settings
from django.forms import ValidationError
from django.test.utils import override_settings
from django.utils import translation

import mock

from rest_framework.response import Response

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import addon_factory, reverse_ns
from olympia.api.tests.utils import APIKeyAuthTestCase
from olympia.applications.models import AppVersion
from olympia.devhub import tasks
from olympia.files.models import File, FileUpload
from olympia.signing.views import VersionView
from olympia.users.models import UserProfile
from olympia.versions.models import Version


class SigningAPITestCase(APIKeyAuthTestCase):
    fixtures = ['base/addon_3615', 'base/user_4043307']

    def setUp(self):
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.api_key = self.create_api_key(self.user, str(self.user.pk) + ':f')


class BaseUploadVersionCase(SigningAPITestCase):

    def setUp(self):
        super(BaseUploadVersionCase, self).setUp()
        self.guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        self.view = VersionView.as_view()
        create_version_patcher = mock.patch(
            'olympia.devhub.tasks.create_version_for_upload',
            tasks.create_version_for_upload.non_atomic)
        self.create_version_for_upload = create_version_patcher.start()
        self.addCleanup(create_version_patcher.stop)

        auto_sign_version_patcher = mock.patch(
            'olympia.devhub.views.auto_sign_version')
        self.auto_sign_version = auto_sign_version_patcher.start()
        self.addCleanup(auto_sign_version_patcher.stop)

    def url(self, guid, version, pk=None):
        if guid is None:
            args = [version]
        else:
            args = [guid, version]
        if pk is not None:
            args.append(pk)
        return reverse_ns('signing.version', args=args)

    def create_version(self, version):
        response = self.request('PUT', self.url(self.guid, version), version)
        assert response.status_code in [201, 202]

    def xpi_filepath(self, addon, version):
        return os.path.join(
            'src', 'olympia', 'signing', 'fixtures',
            '{addon}-{version}.xpi'.format(addon=addon, version=version))

    def request(self, method='PUT', url=None, version='3.0',
                addon='@upload-version', filename=None, channel=None):
        if filename is None:
            filename = self.xpi_filepath(addon, version)
        if url is None:
            url = self.url(addon, version)
        with open(filename) as upload:
            data = {'upload': upload}
            if method == 'POST' and version:
                data['version'] = version
            if channel:
                data['channel'] = channel

            return getattr(self.client, method.lower())(
                url, data,
                HTTP_AUTHORIZATION=self.authorization(),
                format='multipart')

    def make_admin(self, user):
        admin_group = Group.objects.create(name='Admin', rules='*:*')
        GroupUser.objects.create(group=admin_group, user=user)


class TestUploadVersion(BaseUploadVersionCase):

    def test_not_authenticated(self):
        # Use self.client.put so that we don't add the authorization header.
        response = self.client.put(self.url(self.guid, '12.5'))
        assert response.status_code == 401

    def test_addon_does_not_exist(self):
        guid = '@create-version'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request('PUT', addon=guid, version='1.0')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.guid == guid
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.RELEASE_CHANNEL_UNLISTED
        self.auto_sign_version.assert_called_with(latest_version)
        assert not addon.tags.filter(tag_text='dynamic theme').exists()

    def test_new_addon_random_slug_unlisted_channel(self):
        guid = '@create-webextension'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request('PUT', addon=guid, version='1.0')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()

        assert len(addon.slug) == 20
        assert 'create' not in addon.slug

    def test_user_does_not_own_addon(self):
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this addon.'

    def test_admin_does_not_own_addon(self):
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        self.make_admin(self.user)
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this addon.'

    def test_version_does_not_match_manifest_file(self):
        response = self.request('PUT', self.url(self.guid, '2.5'))
        assert response.status_code == 400
        assert response.data['error'] == (
            'Version does not match the manifest file.')

    def test_version_already_exists(self):
        response = self.request(
            'PUT', self.url(self.guid, '2.1.072'), version='2.1.072')
        assert response.status_code == 409
        assert response.data['error'] == 'Version already exists.'

    @mock.patch('olympia.devhub.views.Version.from_upload')
    def test_no_version_yet(self, from_upload):
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_added(self):
        assert Addon.objects.get(guid=self.guid).status == amo.STATUS_PUBLIC
        qs = Version.objects.filter(addon__guid=self.guid, version='3.0')
        assert not qs.exists()
        existing = Version.objects.filter(addon__guid=self.guid)
        assert existing.count() == 1
        assert existing[0].channel == amo.RELEASE_CHANNEL_LISTED

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        version = qs.get()
        assert version.addon.guid == self.guid
        assert version.version == '3.0'
        assert version.statuses[0][1] == amo.STATUS_AWAITING_REVIEW
        assert version.addon.status == amo.STATUS_PUBLIC
        assert version.channel == amo.RELEASE_CHANNEL_LISTED
        self.auto_sign_version.assert_called_with(version)
        assert not version.all_files[0].is_mozilla_signed_extension
        assert not version.addon.tags.filter(tag_text='dynamic theme').exists()

    def test_version_already_uploaded(self):
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 409
        assert response.data['error'] == 'Version already exists.'

    def test_version_failed_review(self):
        self.create_version('3.0')
        version = Version.objects.get(addon__guid=self.guid, version='3.0')
        version.update(reviewed=datetime.today())
        version.files.get().update(reviewed=datetime.today(),
                                   status=amo.STATUS_DISABLED)

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 409
        assert response.data['error'] == 'Version already exists.'

        # Verify that you can check the status after upload (#953).
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_added_is_experiment(self):
        self.grant_permission(self.user, 'Experiments:submit')
        guid = 'experiment@xpi'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            addon=guid, version='0.1',
            filename='src/olympia/files/fixtures/files/'
                     'telemetry_experiment.xpi')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.RELEASE_CHANNEL_UNLISTED
        self.auto_sign_version.assert_called_with(latest_version)

    def test_version_added_is_experiment_reject_no_perm(self):
        guid = 'experiment@xpi'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            addon=guid, version='0.1',
            filename='src/olympia/files/fixtures/files/'
                     'telemetry_experiment.xpi')
        assert response.status_code == 400
        assert response.data['error'] == (
            'You cannot submit this type of add-on')

    def test_mozilla_signed_allowed(self):
        guid = '@webextension-guid'
        self.user.update(email='redpanda@mozilla.com')
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            addon=guid, version='0.0.1',
            filename='src/olympia/files/fixtures/files/'
                     'webextension_signed_already.xpi')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.RELEASE_CHANNEL_UNLISTED
        self.auto_sign_version.assert_called_with(latest_version)
        assert latest_version.all_files[0].is_mozilla_signed_extension

    def test_mozilla_signed_not_allowed_not_mozilla(self):
        guid = '@webextension-guid'
        self.user.update(email='yellowpanda@notzilla.com')
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            addon=guid, version='0.0.1',
            filename='src/olympia/files/fixtures/files/'
                     'webextension_signed_already.xpi')
        assert response.status_code == 400
        assert response.data['error'] == (
            'You cannot submit a Mozilla Signed Extension')

    def test_system_addon_allowed(self):
        guid = 'systemaddon@mozilla.org'
        self.user.update(email='redpanda@mozilla.com')
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            addon=guid, version='0.0.1',
            filename='src/olympia/files/fixtures/files/'
                     'mozilla_guid.xpi')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.RELEASE_CHANNEL_UNLISTED
        self.auto_sign_version.assert_called_with(latest_version)

    def test_system_addon_not_allowed_not_mozilla(self):
        guid = 'systemaddon@mozilla.org'
        self.user.update(email='yellowpanda@notzilla.com')
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            addon=guid, version='0.1',
            filename='src/olympia/files/fixtures/files/'
                     'mozilla_guid.xpi')
        assert response.status_code == 400
        assert response.data['error'] == (
            u'You cannot submit an add-on with a guid ending "@mozilla.org" '
            u'or "@shield.mozilla.org" or "@pioneer.mozilla.org"')

    def test_system_addon_update_allowed(self):
        """Updates to system addons are allowed from anyone."""
        guid = 'systemaddon@mozilla.org'
        self.user.update(email='pinkpanda@notzilla.com')
        orig_addon = addon_factory(
            guid='systemaddon@mozilla.org',
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        AddonUser.objects.create(
            addon=orig_addon,
            user=self.user)
        response = self.request(
            'PUT',
            addon=guid, version='0.0.1',
            filename='src/olympia/files/fixtures/files/'
                     'mozilla_guid.xpi')
        assert response.status_code == 202
        addon = Addon.unfiltered.filter(guid=guid).get()
        assert addon.versions.count() == 2
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.auto_sign_version.assert_called_with(latest_version)

    def test_invalid_version_response_code(self):
        # This raises an error in parse_addon which is not covered by
        # an exception handler.
        response = self.request(
            'PUT',
            self.url(self.guid, '1.0'),
            addon='@create-webextension-invalid-version',
            version='1.0')
        assert response.status_code == 400

    def test_raises_response_code(self):
        # A check that any bare error in handle_upload will return a 400.
        with mock.patch('olympia.signing.views.handle_upload') as patch:
            patch.side_effect = ValidationError(message='some error')
            response = self.request('PUT', self.url(self.guid, '1.0'))
            assert response.status_code == 400

    def test_no_version_upload_for_admin_disabled_addon(self):
        addon = Addon.objects.get(guid=self.guid)
        addon.update(status=amo.STATUS_DISABLED)

        response = self.request(
            'PUT', self.url(self.guid, '3.0'), version='3.0')
        assert response.status_code == 400
        error_msg = 'cannot add versions to an addon that has status: %s.' % (
            amo.STATUS_CHOICES_ADDON[amo.STATUS_DISABLED])
        assert error_msg in response.data['error']

    def test_channel_ignored_for_new_addon(self):
        guid = '@create-version'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request('PUT', addon=guid, version='1.0',
                                channel='listed')
        assert response.status_code == 201
        addon = qs.get()
        assert addon.find_latest_version(channel=amo.RELEASE_CHANNEL_UNLISTED)

    def test_no_channel_selects_last_channel(self):
        addon = Addon.objects.get(guid=self.guid)
        assert addon.status == amo.STATUS_PUBLIC
        assert addon.versions.count() == 1
        assert addon.versions.all()[0].channel == amo.RELEASE_CHANNEL_LISTED

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202, response.data['error']
        assert 'processed' in response.data
        new_version = addon.versions.latest()
        assert new_version.channel == amo.RELEASE_CHANNEL_LISTED

        new_version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)

        response = self.request(
            'PUT', self.url(self.guid, '4.0-beta1'), version='4.0-beta1')
        assert response.status_code == 202, response.data['error']
        assert 'processed' in response.data
        third_version = addon.versions.latest()
        assert third_version.channel == amo.RELEASE_CHANNEL_UNLISTED

    def test_unlisted_channel_for_listed_addon(self):
        addon = Addon.objects.get(guid=self.guid)
        assert addon.status == amo.STATUS_PUBLIC
        assert addon.versions.count() == 1
        assert addon.versions.all()[0].channel == amo.RELEASE_CHANNEL_LISTED

        response = self.request('PUT', self.url(self.guid, '3.0'),
                                channel='unlisted')
        assert response.status_code == 202, response.data['error']
        assert 'processed' in response.data
        assert addon.versions.latest().channel == amo.RELEASE_CHANNEL_UNLISTED

    def test_listed_channel_for_complete_listed_addon(self):
        addon = Addon.objects.get(guid=self.guid)
        assert addon.status == amo.STATUS_PUBLIC
        assert addon.versions.count() == 1
        assert addon.has_complete_metadata()

        response = self.request('PUT', self.url(self.guid, '3.0'),
                                channel='listed')
        assert response.status_code == 202, response.data['error']
        assert 'processed' in response.data
        assert addon.versions.latest().channel == amo.RELEASE_CHANNEL_LISTED

    def test_listed_channel_fails_for_incomplete_addon(self):
        addon = Addon.objects.get(guid=self.guid)
        assert addon.status == amo.STATUS_PUBLIC
        assert addon.versions.count() == 1
        addon.current_version.update(license=None)  # Make addon incomplete.
        addon.versions.latest().update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert not addon.has_complete_metadata(
            has_listed_versions=True)

        response = self.request('PUT', self.url(self.guid, '3.0'),
                                channel='listed')
        assert response.status_code == 400
        error_msg = (
            'You cannot add a listed version to this addon via the API')
        assert error_msg in response.data['error']


class TestUploadVersionWebextension(BaseUploadVersionCase):
    def setUp(self):
        super(TestUploadVersionWebextension, self).setUp()
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='*')

        validate_patcher = mock.patch('validator.validate.validate')
        run_validator = validate_patcher.start()
        run_validator.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        self.addCleanup(validate_patcher.stop)

    def test_addon_does_not_exist_webextension(self):
        response = self.request(
            'POST',
            url=reverse_ns('signing.version'),
            addon='@create-webextension',
            version='1.0')
        assert response.status_code == 201

        guid = response.data['guid']
        addon = Addon.unfiltered.get(guid=guid)

        assert addon.guid is not None
        assert addon.guid != self.guid

        version = Version.objects.get(addon__guid=guid, version='1.0')
        assert version.files.all()[0].is_webextension is True
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.RELEASE_CHANNEL_UNLISTED
        self.auto_sign_version.assert_called_with(
            latest_version)

    def test_addon_does_not_exist_webextension_with_guid_in_url(self):
        guid = '@custom-guid-provided'
        # Override the filename self.request() picks, we want that specific
        # file but with a custom guid.
        filename = self.xpi_filepath('@create-webextension', '1.0')
        response = self.request(
            'PUT',  # PUT, not POST, since we're specifying a guid in the URL.
            filename=filename,
            addon=guid,  # Will end up in the url since we're not passing one.
            version='1.0')
        assert response.status_code == 201

        assert response.data['guid'] == '@custom-guid-provided'
        addon = Addon.unfiltered.get(guid=response.data['guid'])
        assert addon.guid == '@custom-guid-provided'

        version = Version.objects.get(addon__guid=guid, version='1.0')
        assert version.files.all()[0].is_webextension is True
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.RELEASE_CHANNEL_UNLISTED
        self.auto_sign_version.assert_called_with(
            latest_version)

    def test_addon_does_not_exist_webextension_with_invalid_guid_in_url(self):
        guid = 'custom-invalid-guid-provided'
        # Override the filename self.request() picks, we want that specific
        # file but with a custom guid.
        filename = self.xpi_filepath('@create-webextension', '1.0')
        response = self.request(
            'PUT',  # PUT, not POST, since we're specifying a guid in the URL.
            filename=filename,
            addon=guid,  # Will end up in the url since we're not passing one.
            version='1.0')
        assert response.status_code == 400
        assert response.data['error'] == u'Invalid GUID in URL'
        assert not Addon.unfiltered.filter(guid=guid).exists()

    def test_optional_id_not_allowed_for_regular_addon(self):
        response = self.request(
            'POST',
            url=reverse_ns('signing.version'),
            addon='@create-version-no-id',
            version='1.0')
        assert response.status_code == 400

    def test_webextension_reuse_guid(self):
        response = self.request(
            'POST',
            url=reverse_ns('signing.version'),
            addon='@create-webextension-with-guid',
            version='1.0')

        guid = response.data['guid']
        assert guid == '@webextension-with-guid'

        addon = Addon.unfiltered.get(guid=guid)
        assert addon.guid == '@webextension-with-guid'

    def test_webextension_reuse_guid_but_only_create(self):
        # Uploading the same version with the same id fails. People
        # have to use the regular `PUT` endpoint for that.
        response = self.request(
            'POST',
            url=reverse_ns('signing.version'),
            addon='@create-webextension-with-guid',
            version='1.0')
        assert response.status_code == 201

        response = self.request(
            'POST',
            url=reverse_ns('signing.version'),
            addon='@create-webextension-with-guid',
            version='1.0')
        assert response.status_code == 400
        assert response.data['error'] == 'Duplicate add-on ID found.'

    def test_webextension_optional_version(self):
        # Uploading the same version with the same id fails. People
        # have to use the regular `PUT` endpoint for that.
        response = self.request(
            'POST',
            url=reverse_ns('signing.version'),
            addon='@create-webextension-with-guid-and-version',
            version='99.0')
        assert response.status_code == 201
        assert (
            response.data['guid'] ==
            '@create-webextension-with-guid-and-version')
        assert response.data['version'] == '99.0'

    def test_webextension_resolve_translations(self):
        fname = (
            'src/olympia/files/fixtures/files/notify-link-clicks-i18n.xpi')

        response = self.request(
            'POST',
            url=reverse_ns('signing.version'),
            addon='@notify-link-clicks-i18n',
            version='1.0',
            filename=fname)
        assert response.status_code == 201

        addon = Addon.unfiltered.get(guid=response.data['guid'])

        # Normalized from `en` to `en-US`
        assert addon.default_locale == 'en-US'
        assert addon.name == 'Notify link clicks i18n'
        assert addon.summary == (
            'Shows a notification when the user clicks on links.')

        translation.activate('de')
        addon.reload()
        assert addon.name == 'Meine Beispielerweiterung'
        assert addon.summary == u'Benachrichtigt den Benutzer über Linkklicks'

    def test_too_long_guid_not_in_manifest_forbidden(self):
        fname = (
            'src/olympia/files/fixtures/files/webextension_no_id.xpi')

        guid = (
            'this_guid_is_longer_than_the_limit_of_64_chars_see_bug_1201176_'
            'and_should_fail@webextension-guid')

        response = self.request(
            'PUT',
            url=self.url(guid, '1.0'),
            version='1.0',
            filename=fname)
        assert response.status_code == 400
        assert response.data == {
            'error': (
                u'Please specify your Add-on GUID in the manifest if it\'s '
                u'longer than 64 characters.')
        }

        assert not Addon.unfiltered.filter(guid=guid).exists()

    def test_too_long_guid_in_manifest_allowed(self):
        fname = (
            'src/olympia/files/fixtures/files/webextension_too_long_guid.xpi')

        guid = (
            'this_guid_is_longer_than_the_limit_of_64_chars_see_bug_1201176_'
            'and_should_fail@webextension-guid')

        response = self.request(
            'PUT',
            url=self.url(guid, '1.0'),
            version='1.0',
            filename=fname)
        assert response.status_code == 201
        assert Addon.unfiltered.filter(guid=guid).exists()

    def test_dynamic_theme_tag_added(self):
        addon = Addon.objects.get(guid=self.guid)
        addon.current_version.update(version='0.9')

        def parse_addon_wrapper(*args, **kwargs):
            from olympia.files.utils import parse_addon
            parsed = parse_addon(*args, **kwargs)
            parsed['permissions'] = parsed.get('permissions', []) + ['theme']
            return parsed

        with mock.patch('olympia.devhub.tasks.parse_addon',
                        wraps=parse_addon_wrapper):
            # But unlisted should be ignored
            response = self.request(
                'PUT', self.url(self.guid, '1.0'), version='1.0',
                addon='@create-webextension', channel='unlisted')
            assert response.status_code == 202, response.data['error']
            assert not addon.tags.filter(tag_text='dynamic theme').exists()
            addon.versions.latest().delete(hard=True)

            # Only listed version get the tag
            response = self.request(
                'PUT', self.url(self.guid, '1.0'), version='1.0',
                addon='@create-webextension', channel='listed')
            assert response.status_code == 202, response.data['error']
            assert addon.tags.filter(tag_text='dynamic theme').exists()


class TestCheckVersion(BaseUploadVersionCase):

    def test_not_authenticated(self):
        # Use self.client.get so that we don't add the authorization header.
        response = self.client.get(self.url(self.guid, '12.5'))
        assert response.status_code == 401

    def test_addon_does_not_exist(self):
        response = self.get(self.url('foo', '12.5'))
        assert response.status_code == 404
        assert response.data['error'] == 'Could not find add-on with id "foo".'

    def test_user_does_not_own_addon(self):
        self.create_version('3.0')
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this addon.'

    def test_admin_can_view(self):
        self.create_version('3.0')
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.make_admin(self.user)
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_does_not_exist(self):
        response = self.get(self.url(self.guid, '2.5'))
        assert response.status_code == 404
        assert (response.data['error'] ==
                'No uploaded file for that addon and version.')

    def test_version_exists(self):
        self.create_version('3.0')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_exists_with_pk(self):
        # Mock Version.from_upload so the Version won't be created.
        with mock.patch('olympia.devhub.tasks.Version.from_upload'):
            self.create_version('3.0')
        upload = FileUpload.objects.latest()
        upload.update(created=datetime.today() - timedelta(hours=1))

        self.create_version('3.0')
        newer_upload = FileUpload.objects.latest()
        assert newer_upload != upload

        response = self.get(self.url(self.guid, '3.0', upload.uuid.hex))
        assert response.status_code == 200
        # For backwards-compatibility reasons, we return the uuid as "pk".
        assert response.data['pk'] == upload.uuid.hex
        assert 'processed' in response.data

    def test_version_exists_with_pk_not_owner(self):
        orig_user, orig_api_key = self.user, self.api_key

        # This will create a version for the add-on with guid @create-version
        # using a new user.
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.request('PUT', addon='@create-version', version='1.0')
        assert response.status_code == 201
        upload = FileUpload.objects.latest()

        # Check that the user that created the upload can access it properly.
        response = self.get(
            self.url('@create-version', '1.0', upload.uuid.hex))
        assert response.status_code == 200
        assert 'processed' in response.data

        # This will create a version for the add-on from the fixture with the
        # regular fixture user.
        self.user, self.api_key = orig_user, orig_api_key
        self.create_version('3.0')

        # Check that we can't access the FileUpload by uuid even if we pass in
        # an add-on and version that we own if we don't own the FileUpload.
        response = self.get(self.url(self.guid, '3.0', upload.uuid.hex))
        assert response.status_code == 404
        assert 'error' in response.data

    def test_version_download_url(self):
        version_string = '3.0'
        qs = File.objects.filter(version__addon__guid=self.guid,
                                 version__version=version_string)
        assert not qs.exists()
        self.create_version(version_string)
        response = self.get(self.url(self.guid, version_string))
        assert response.status_code == 200
        file_ = qs.get()
        assert response.data['files'][0]['download_url'] == absolutify(
            reverse_ns('signing.file', kwargs={'file_id': file_.id}) +
            '/delicious_bookmarks-3.0-fx.xpi?src=api')

    def test_file_hash(self):
        version_string = '3.0'
        qs = File.objects.filter(version__addon__guid=self.guid,
                                 version__version=version_string)
        assert not qs.exists()
        self.create_version(version_string)
        response = self.get(self.url(self.guid, version_string))
        assert response.status_code == 200
        file_ = qs.get()

        filename = self.xpi_filepath('@upload-version', version_string)
        assert response.data['files'][0]['hash'] == \
            file_.generate_hash(filename=filename)

    def test_has_failed_upload(self):
        addon = Addon.objects.get(guid=self.guid)
        FileUpload.objects.create(addon=addon, version='3.0')
        self.create_version('3.0')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data


class TestSignedFile(SigningAPITestCase):

    def setUp(self):
        super(TestSignedFile, self).setUp()
        self.file_ = self.create_file()

    def url(self):
        return reverse_ns('signing.file', args=[self.file_.pk])

    def create_file(self):
        addon = addon_factory(
            name='thing', version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED},
            users=[self.user])
        return addon.latest_unlisted_version.all_files[0]

    def test_can_download_once_authenticated(self):
        response = self.get(self.url())
        assert response.status_code == 200
        assert response[settings.XSENDFILE_HEADER] == (
            self.file_.file_path)

    def test_cannot_download_without_authentication(self):
        response = self.client.get(self.url())  # no auth
        assert response.status_code == 401

    def test_api_relies_on_version_downloader(self):
        with mock.patch('olympia.versions.views.download_file') as df:
            df.return_value = Response({})
            self.get(self.url())
        assert df.called is True
        assert df.call_args[0][0].user == self.user
        assert df.call_args[0][1] == str(self.file_.pk)
