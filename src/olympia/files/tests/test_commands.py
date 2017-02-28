# -*- coding: utf-8 -*-
from django.conf import settings
from django.core.management import call_command
from django.test.utils import override_settings
from django.utils import translation

import responses

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.applications.models import AppVersion
from olympia.files.models import (
    File, WebextPermission, WebextPermissionDescription)
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import parse_addon
from olympia.translations.models import Translation
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


@override_settings(AMO_LANGUAGES=('fr', 'de', 'zh-CN'))
class TestWebextUpdateDescriptions(TestCase):

    def _register_uris(self):
        responses.add(
            responses.GET, settings.WEBEXT_PERM_DESCRIPTIONS_URL,
            content_type='text/plain; charset="UTF-8"',
            body=u'\n'.join([
                u'webextPerms.description.bookmarks=Read and modify bookmarks',
                u'webextPerms.description.geolocation=Access your location',
                u'webextPerms.description.tabs=Access browser tabs']))
        localised_url = settings.WEBEXT_PERM_DESCRIPTIONS_LOCALISED_URL
        responses.add(
            responses.GET,
            localised_url.format(locale='fr'),
            content_type='text/plain; charset="UTF-8"',
            body=u'\n'.join([
                u'webextPerms.description.bookmarks=Réad n wríte le bookmarks',
                u'webextPerms.description.tabs=Accéder browser onglets']))
        responses.add(
            responses.GET,
            localised_url.format(locale='de'),
            content_type='text/plain; charset="UTF-8"',
            body=u'\n'.join([
                u'webextPerms.description.bookmarks=Eich bin bookmark',
                u'webextPerms.description.tabs=']))
        responses.add(
            responses.GET,
            localised_url.format(locale='zh-CN'),
            content_type='text/plain; charset="UTF-8"',
            body=u'\n'.join([
                u'webextPerms.description.bookmarks=讀取並修改書籤',
                u'webextPerms.description.sessions=存取瀏覽器最近關閉的分頁']))

    def _check_objects(self):
        assert WebextPermissionDescription.objects.get(
            name='bookmarks').description == u'Read and modify bookmarks'
        assert WebextPermissionDescription.objects.get(
            name='geolocation').description == u'Access your location'
        assert WebextPermissionDescription.objects.get(
            name='tabs').description == u'Access browser tabs'

    def _check_locales(self):
        with translation.override('fr'):
            assert WebextPermissionDescription.objects.no_cache().get(
                name='bookmarks').description == u'Réad n wríte le bookmarks'
            # There wasn't any French l10n for this perm; so en fallback.
            assert WebextPermissionDescription.objects.get(
                name='geolocation').description == u'Access your location'
            assert WebextPermissionDescription.objects.get(
                name='tabs').description == u'Accéder browser onglets'

        with translation.override('de'):
            assert WebextPermissionDescription.objects.no_cache().get(
                name='bookmarks').description == u'Eich bin bookmark'
            # There wasn't any German l10n for this perm; so en fallback.
            assert WebextPermissionDescription.objects.get(
                name='geolocation').description == u'Access your location'
            # There was an empty German l10n; so en fallback
            assert WebextPermissionDescription.objects.get(
                name='tabs').description == u'Access browser tabs'
        with translation.override('zh-CN'):
            assert WebextPermissionDescription.objects.no_cache().get(
                name='bookmarks').description == u'讀取並修改書籤'
            # There wasn't any Chinese l10n for this perm; so en fallback.
            assert WebextPermissionDescription.objects.get(
                name='geolocation').description == u'Access your location'
            # There wasn't any Chinese l10n; so en fallback
            assert WebextPermissionDescription.objects.get(
                name='tabs').description == u'Access browser tabs'

        # Chinese had an extra localisation, check it was ignored.
        assert not Translation.objects.filter(
            localized_string=u'存取瀏覽器最近關閉的分頁').exists()
        # Confirm that all the bookmark localisations were saved.
        bookmarks_perm = WebextPermissionDescription.objects.get(
            name='bookmarks')
        assert Translation.objects.filter(
            id=bookmarks_perm.description_id).count() == 4

    @responses.activate
    def test_add_descriptions(self):
        self._register_uris()
        assert WebextPermissionDescription.objects.count() == 0
        # Add an existing permission that won't be updated.
        WebextPermissionDescription.objects.create(
            name='oldpermission', description=u'somethunk craaazie')

        call_command('update_permissions_from_mc')
        assert WebextPermissionDescription.objects.count() == 4
        self._check_objects()
        self._check_locales()
        # Existing permission is still there.
        assert WebextPermissionDescription.objects.filter(
            name='oldpermission').exists()

    @responses.activate
    def test_clear_then_add_descriptions(self):
        self._register_uris()
        # Add an existing permission that won't be updated and will be cleared.
        WebextPermissionDescription.objects.create(
            name='oldpermission', description='somethunk craaazie')
        assert WebextPermissionDescription.objects.filter(
            name='oldpermission').exists()

        call_command('update_permissions_from_mc', clear=True)

        assert WebextPermissionDescription.objects.count() == 3
        self._check_objects()
        # Existing permission is cleared.
        assert not WebextPermissionDescription.objects.filter(
            name='oldpermission').exists()
