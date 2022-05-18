import os

from unittest import mock

from django.conf import settings
from django.utils.encoding import smart_str
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.urls import reverse

from rest_framework import exceptions as drf_exceptions
from pyquery import PyQuery

from olympia import amo
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonRegionalRestrictions
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    APITestClientJWT,
    APITestClientSessionID,
    TestCase,
    addon_factory,
    version_factory,
)
from olympia.files.models import File
from olympia.users.models import UserProfile


def decode_http_header_value(value):
    """
    Reverse the encoding that django applies to bytestrings in
    HttpResponse._convert_to_charset(). Needed to test header values that we
    explicitly pass as bytes such as filenames for content-disposition or
    xsendfile headers.
    """
    return value.encode('latin-1').decode('utf-8')


class UpdateInfoMixin:
    def setUp(self):
        self.addon = addon_factory(
            slug='my-addôn', file_kw={'size': 1024}, version_kw={'version': '1.0'}
        )
        self.version = self.addon.current_version
        self.addon.current_version.update(created=self.days_ago(3))

    def test_version_update_info_deleted(self):
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_version_update_info_non_public(self):
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_version_update_info_addon_non_public(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_version_update_info_no_unlisted(self):
        # Add another listed version before making the first one unlisted,
        # ensuring the add-on would stay public.
        version_factory(addon=self.addon)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 404


class TestUpdateInfo(UpdateInfoMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.url_args = (self.addon.slug, self.version.version)
        self.url = reverse('addons.versions.update_info', args=self.url_args)

    def test_version_update_info(self):
        self.version.release_notes = {
            'en-US': 'Fix for an important bug',
            'fr': "Quelque chose en français.\n\nQuelque chose d'autre.",
        }
        self.version.save()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response['Cache-Control'] == 'max-age=3600'
        assert response['Content-Type'] == 'application/xhtml+xml'

        # pyquery is annoying to use with XML and namespaces. Use the HTML
        # parser, but do check that xmlns attribute is present (required by
        # Firefox for the notes to be shown properly).
        doc = PyQuery(response.content, parser='html')
        assert doc('html').attr('xmlns') == 'http://www.w3.org/1999/xhtml'
        assert doc('p').html() == 'Fix for an important bug'

        # Test update info in another language.
        with self.activate(locale='fr'):
            self.url = reverse(
                'addons.versions.update_info',
                args=self.url_args,
            )  # self.url contains lang, so we need to reverse it again.
            response = self.client.get(self.url)
            assert response.status_code == 200
            assert response['Content-Type'] == 'application/xhtml+xml'
            assert (
                b'<br/>' in response.content
            ), 'Should be using XHTML self-closing tags!'
            doc = PyQuery(response.content, parser='html')
            assert doc('html').attr('xmlns') == 'http://www.w3.org/1999/xhtml'
            assert doc('p').html() == (
                "Quelque chose en français.<br/><br/>Quelque chose d'autre."
            )

    def test_with_addon_pk(self):
        url = reverse(
            'addons.versions.update_info', args=(self.addon.pk, self.version.version)
        )
        response = self.client.get(url)
        self.assert3xx(response, self.url, 301)

    def test_addon_mismatch(self):
        another_addon = addon_factory(version_kw={'version': '42.42.42.42'})
        url = reverse(
            'addons.versions.update_info',
            args=(another_addon.slug, self.version.version),
        )
        response = self.client.get(url)
        assert response.status_code == 404

    def test_num_queries(self):
        with self.assertNumQueries(3):
            # - addon
            # - version
            # - translations for release notes
            response = self.client.get(self.url)
            assert response.status_code == 200


class TestUpdateInfoLegacyRedirect(UpdateInfoMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse(
            'addons.versions.update_info_redirect',
            args=(self.version.pk,),
        )

    def test_version_update_info_legacy_redirect(self):
        expected_legacy_url = f'/en-US/firefox/versions/updateInfo/{self.version.id}'
        assert self.url == expected_legacy_url

        expected_redirect_url = reverse(
            'addons.versions.update_info',
            args=(self.addon.slug, self.version.version),
        )

        response = self.client.get(self.url)
        assert response['Cache-Control'] == 'max-age=3600'
        self.assert3xx(response, expected_redirect_url, status_code=301)

        # It should also work without the locale+app prefix, but that does
        # a 302 to the same url with locale+app prefix added first.
        response = self.client.get(
            f'/versions/updateInfo/{self.version.id}',
        )
        self.assert3xx(response, self.url, status_code=302)

    def test_num_queries(self):
        with self.assertNumQueries(1):
            # version+addon (single query)
            response = self.client.get(self.url)
            assert response.status_code == 301


class TestDownloadsBase(TestCase):
    fixtures = ['base/addon_5299_gcal', 'base/users']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(id=5299)
        self.file = File.objects.get(id=33046)
        self.file_url = reverse('downloads.file', kwargs={'file_id': self.file.id})
        self.latest_url = reverse(
            'downloads.latest', kwargs={'addon_id': self.addon.slug}
        )

    def assert_served_internally(self, response, *, attachment=False):
        assert response.status_code == 200
        assert (
            decode_http_header_value(response[settings.XSENDFILE_HEADER])
            == self.file.file_path
        )
        assert response['Access-Control-Allow-Origin'] == '*'

        if attachment:
            assert response.has_header('Content-Disposition')
            assert response['Content-Disposition'] == 'attachment'
        else:
            assert not response.has_header('Content-Disposition')
        assert response['Cache-Control'] == 'max-age=86400'
        assert response['Access-Control-Allow-Origin'] == '*'
        return response

    def login(self, **kwargs):
        return self.client.login(**kwargs)


class TestDownloadsUnlistedVersions(TestDownloadsBase):
    def setUp(self):
        super().setUp()
        self.make_addon_unlisted(self.addon)

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_returns_404(self):
        """File downloading isn't allowed for unlisted addons."""
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404

        # Even if georestricted, the 404 will be raised anyway.
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        assert (
            self.client.get(self.file_url, HTTP_X_COUNTRY_CODE='fr').status_code == 404
        )

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.assert_served_internally(self.client.get(self.file_url))
        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

        # Even allowed to bypass georestrictions.
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        self.assert_served_internally(
            self.client.get(url, HTTP_X_COUNTRY_CODE='fr'),
            attachment=True,
        )

        # Latest shouldn't work as it's only for latest public listed version.
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: True)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_reviewer(self):
        """File downloading isn't allowed for reviewers."""
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: True)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers."""
        self.assert_served_internally(self.client.get(self.file_url))
        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

        # Even allowed to bypass georestrictions.
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        self.assert_served_internally(
            self.client.get(url, HTTP_X_COUNTRY_CODE='fr'),
            attachment=True,
        )

        # Latest shouldn't work as it's only for latest public listed version.
        assert self.client.get(self.latest_url).status_code == 404


class TestDownloadsUnlistedAddonDeleted(TestDownloadsUnlistedVersions):
    # Everything should work the same for unlisted when the addon is deleted
    # except developers can no longer access.
    def setUp(self):
        super().setUp()
        self.addon.delete()

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404

        # Even if georestricted, the 404 will be raised anyway.
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        assert (
            self.client.get(self.file_url, HTTP_X_COUNTRY_CODE='fr').status_code == 404
        )

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: True)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers."""
        self.assert_served_internally(self.client.get(self.file_url))
        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

        # Even allowed to bypass georestrictions.
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        self.assert_served_internally(
            self.client.get(url, HTTP_X_COUNTRY_CODE='fr'),
            attachment=True,
        )

        # Latest shouldn't work as it's only for latest public listed version.
        assert self.client.get(self.latest_url).status_code == 404


class TestDownloads(TestDownloadsBase):
    def test_file_404(self):
        response = self.client.get(reverse('downloads.file', kwargs={'file_id': 234}))
        assert response.status_code == 404

    def test_public(self):
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        self.assert_served_internally(self.client.get(self.file_url))

    def test_public_addon_unreviewed_file(self):
        self.file.status = amo.STATUS_AWAITING_REVIEW
        self.file.save()
        self.assert_served_internally(self.client.get(self.file_url))

    def test_unreviewed_addon(self):
        self.addon.status = amo.STATUS_NULL
        self.addon.save()
        self.assert_served_internally(self.client.get(self.file_url))

    def test_type_attachment(self):
        self.assert_served_internally(self.client.get(self.file_url))
        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_trailing_filename(self):
        url = self.file_url + self.file.pretty_filename
        self.assert_served_internally(self.client.get(url))

    def test_null_datestatuschanged(self):
        self.file.update(datestatuschanged=None)
        self.assert_served_internally(self.client.get(self.file_url))

    def test_unicode_url(self):
        self.file.file.name = f'{self.file.addon.pk}/图像浏览器-0.5.xpi'
        self.file.save()
        self.assert_served_internally(self.client.get(self.file_url))

    def test_deleted(self):
        self.addon.delete()
        assert self.client.get(self.file_url).status_code == 404

    def test_georestricted(self):
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        self.assert_served_internally(
            self.client.get(self.file_url, HTTP_X_COUNTRY_CODE='uk')
        )

        response = self.client.get(self.file_url, HTTP_X_COUNTRY_CODE='fr')
        assert response.status_code == 451
        assert response['Vary'] == 'X-Country-Code'
        assert response['Link'] == (
            '<https://www.mozilla.org/about/policy/transparency/>; rel="blocked-by"'
        )


class NonPublicFileDownloadsMixin:
    def test_admin_disabled_404(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.file_url).status_code == 404

    def test_user_disabled_404(self):
        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_anon_404(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_unprivileged_404(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.login(email='regular@mozilla.com')
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_ok_for_author(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_file_disabled_ok_for_reviewer(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.login(email='reviewer@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_file_disabled_ok_for_admin(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_ok_for_author(self):
        # Addon should be disabled or the version unlisted at this point, so
        # it should be served internally.
        assert self.login(email='g@gmail.com')
        self.assert_served_internally(
            self.client.get(self.file_url),
        )

        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_ok_for_admin(self):
        # Addon should be disabled or the version unlisted at this point, so
        # it should be served internally.
        self.login(email='admin@mozilla.com')
        self.assert_served_internally(
            self.client.get(self.file_url),
        )

        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_user_disabled_ok_for_author(self):
        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        assert self.login(email='g@gmail.com')
        self.assert_served_internally(
            self.client.get(self.file_url),
        )

        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_user_disabled_ok_for_admin(self):
        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        self.login(email='admin@mozilla.com')
        self.assert_served_internally(
            self.client.get(self.file_url),
        )

        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)


class DownloadsNonDisabledMixin:
    def test_ok_for_author(self):
        assert self.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_ok_for_admin(self):
        self.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse(
            'downloads.file',
            kwargs={'file_id': self.file.id, 'download_type': 'attachment'},
        )
        self.assert_served_internally(self.client.get(url), attachment=True)


class APILoginMixin:
    def login(self, **kwargs):
        try:
            user = UserProfile.objects.get(**kwargs)
            user.update(read_dev_agreement=self.days_ago(0))
            self.client.login_api(user)
        except UserProfile.DoesNotExist:
            return False
        return True


class TestDisabledFileDownloads(NonPublicFileDownloadsMixin, TestDownloadsBase):
    def setUp(self):
        super().setUp()
        self.addon.update(status=amo.STATUS_DISABLED)


class TestDisabledFileDownloadsSessionAPIAuth(APILoginMixin, TestDisabledFileDownloads):
    client_class = APITestClientSessionID


class TestDisabledFileDownloadsJWTAPIAuth(APILoginMixin, TestDisabledFileDownloads):
    client_class = APITestClientJWT


class TestUnlistedFileDownloads(
    DownloadsNonDisabledMixin, NonPublicFileDownloadsMixin, TestDownloadsBase
):
    def setUp(self):
        super().setUp()
        self.make_addon_unlisted(self.addon)
        self.grant_permission(
            UserProfile.objects.get(email='reviewer@mozilla.com'),
            'Addons:ReviewUnlisted',
        )


class TestUnlistedFileDownloadsSessionAPIAuth(APILoginMixin, TestUnlistedFileDownloads):
    client_class = APITestClientSessionID


class TestUnlistedFileDownloadsJWTAPIAuth(APILoginMixin, TestUnlistedFileDownloads):
    client_class = APITestClientJWT


class TestUnlistedSitePermissionFileDownloads(
    DownloadsNonDisabledMixin, NonPublicFileDownloadsMixin, TestDownloadsBase
):
    def setUp(self):
        super().setUp()
        self.addon.update(type=amo.ADDON_SITE_PERMISSION)
        self.make_addon_unlisted(self.addon)
        self.grant_permission(
            UserProfile.objects.get(email='reviewer@mozilla.com'),
            'Addons:ReviewUnlisted',
        )


class TestUnlistedSitePermissionFileDownloadsSessionAPIAuth(
    APILoginMixin, TestUnlistedSitePermissionFileDownloads
):
    client_class = APITestClientSessionID


class TestUnlistedSitePermissionFileDownloadsJWTAPIAuth(
    APILoginMixin, TestUnlistedSitePermissionFileDownloads
):
    client_class = APITestClientJWT


class TestUnlistedDisabledSitePermissionFileDownloads(
    NonPublicFileDownloadsMixin, TestDownloadsBase
):
    def setUp(self):
        super().setUp()
        self.addon.update(status=amo.STATUS_DISABLED, type=amo.ADDON_SITE_PERMISSION)
        self.make_addon_unlisted(self.addon)
        self.grant_permission(
            UserProfile.objects.get(email='reviewer@mozilla.com'),
            'Addons:ReviewUnlisted',
        )


class TestUnlistedDisabledSitePermissionFileDownloadsSessionAPIAuth(
    APILoginMixin, TestUnlistedDisabledSitePermissionFileDownloads
):
    client_class = APITestClientSessionID


class TestUnlistedDisabledSitePermissionFileDownloadsJWTAPIAuth(
    APILoginMixin, TestUnlistedDisabledSitePermissionFileDownloads
):
    client_class = APITestClientJWT


class TestUnlistedDisabledAndDeletedFileDownloads(TestDisabledFileDownloads):
    # Like TestDownloadsUnlistedAddonDeleted above, nothing should change for
    # reviewers and admins if the add-on is deleted in addition to being
    # disabled and the version unlisted. Authors should no longer have access.
    def setUp(self):
        super().setUp()
        self.addon.delete()

    def test_user_disabled_ok_for_author(self):
        self.addon.update(disabled_by_user=True)
        assert self.login(email='g@gmail.com')
        assert self.client.get(self.file_url).status_code == 404

    def test_ok_for_author(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.login(email='g@gmail.com')
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_ok_for_author(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.login(email='g@gmail.com')
        assert self.client.get(self.file_url).status_code == 404


class TestUnlistedDisabledAndDeletedFileDownloadsSessionAPIAuth(
    APILoginMixin, TestUnlistedDisabledAndDeletedFileDownloads
):
    client_class = APITestClientSessionID


class TestUnlistedDisabledAndDeletedFileDownloadsJWTAPIAuth(
    APILoginMixin, TestUnlistedDisabledAndDeletedFileDownloads
):
    client_class = APITestClientJWT


class TestUnlistedDisabledAndDeletedSitePermissionFileDownloads(
    TestUnlistedDisabledAndDeletedFileDownloads
):
    def setUp(self):
        super().setUp()
        self.addon.update(type=amo.ADDON_SITE_PERMISSION)


class TestUnlistedDisabledAndDeletedSitePermissionFileDownloadsSessionAPIAuth(
    APILoginMixin, TestUnlistedDisabledAndDeletedSitePermissionFileDownloads
):
    client_class = APITestClientSessionID


class TestUnlistedDisabledAndDeletedSitePermissionFileDownloadsJWTAPIAuth(
    APILoginMixin, TestUnlistedDisabledAndDeletedSitePermissionFileDownloads
):
    client_class = APITestClientJWT


class TestDownloadsAPIAuthFailure(APILoginMixin, TestDownloadsBase):
    def setUp(self):
        super().setUp()
        self.session_id_auth_mock = self.patch(
            'olympia.api.authentication.SessionIDAuthentication.authenticate'
        )
        self.session_id_auth_mock.return_value = None
        self.jwt_key_auth_mock = self.patch(
            'olympia.api.authentication.JWTKeyAuthentication.authenticate'
        )
        self.jwt_key_auth_mock.return_value = None

    def _test_auth_fail(self, authenticate_mock, TestClientClass):
        self.client = TestClientClass()
        authenticate_mock.side_effect = drf_exceptions.AuthenticationFailed

        assert self.login(email='g@gmail.com')

        response = self.client.get(self.file_url)
        assert response.status_code == 401
        assert response.data == {'detail' 'Incorrect authentication credentials.'}

    def test_auth_fail_session_id(self):
        self._test_auth_fail(self.session_id_auth_mock, APITestClientSessionID)
        # Once we have a failing auth the second auth class shouldn't be attempted
        self.jwt_key_auth_mock.assert_not_called()

    def test_auth_fail_jwt(self):
        self._test_auth_fail(self.jwt_key_auth_mock, APITestClientJWT)
        # SessionID auth should have been tried first and ignored
        self.session_id_auth_mock.assert_called()


class TestDownloadsLatest(TestDownloadsBase):
    def test_404(self):
        url = reverse('downloads.latest', kwargs={'addon_id': 123})
        assert self.client.get(url).status_code == 404

    def test_urls(self):
        assert (
            reverse(
                'downloads.latest',
                kwargs={'addon_id': self.addon.slug},
            )
            == '/firefox/downloads/latest/better-gcal-5299/'
        )
        assert (
            reverse(
                'downloads.latest',
                kwargs={'addon_id': self.addon.slug, 'download_type': 'attachment'},
            )
            == '/firefox/downloads/latest/better-gcal-5299/type:attachment/'
        )
        assert (
            reverse(
                'downloads.latest',
                kwargs={
                    'addon_id': self.addon.slug,
                    'download_type': 'attachment',
                    'filename': 'foo-bar.xpi',
                },
            )
            == '/firefox/downloads/latest/better-gcal-5299/type:attachment/foo-bar.xpi'
        )

    def test_no_type(self):
        response = self.client.get(self.latest_url)
        expected_redirect_url = absolutify(
            reverse(
                'downloads.file',
                kwargs={'file_id': self.file.pk, 'filename': self.file.pretty_filename},
            )
        )
        self.assert3xx(response, expected_redirect_url, 302)
        assert response['Cache-Control'] == 'max-age=3600'
        assert response['Access-Control-Allow-Origin'] == '*'

    def test_type_random(self):
        self.latest_url = reverse(
            'downloads.latest',
            kwargs={'addon_id': self.addon.slug, 'download_type': 'random'},
        )
        self.test_no_type()

    def test_type_attachment(self):
        self.latest_url = reverse(
            'downloads.latest',
            kwargs={'addon_id': self.addon.slug, 'download_type': 'attachment'},
        )
        expected_redirect_url = absolutify(
            reverse(
                'downloads.file',
                kwargs={
                    'file_id': self.file.pk,
                    'download_type': 'attachment',
                    'filename': self.file.pretty_filename,
                },
            )
        )
        response = self.client.get(self.latest_url)
        self.assert3xx(response, expected_redirect_url, 302)
        assert response['Cache-Control'] == 'max-age=3600'
        assert response['Access-Control-Allow-Origin'] == '*'

    def test_platform_and_type(self):
        # 'platform' should just be ignored nowadays.
        self.latest_url = reverse(
            'downloads.latest',
            kwargs={
                'addon_id': self.addon.slug,
                'platform': 5,
                'download_type': 'attachment',
            },
        )
        expected_redirect_url = absolutify(
            reverse(
                'downloads.file',
                kwargs={
                    'file_id': self.file.pk,
                    'download_type': 'attachment',
                    'filename': self.file.pretty_filename,
                },
            )
        )
        response = self.client.get(self.latest_url)
        self.assert3xx(response, expected_redirect_url, 302)
        assert response['Cache-Control'] == 'max-age=3600'
        assert response['Access-Control-Allow-Origin'] == '*'

    def test_type_and_filename(self):
        self.latest_url = reverse(
            'downloads.latest',
            kwargs={
                'addon_id': self.addon.slug,
                'download_type': 'attachment',
                'filename': 'lol-ignore-me.xpi',
            },
        )
        expected_redirect_url = absolutify(
            reverse(
                'downloads.file',
                kwargs={
                    'file_id': self.file.pk,
                    'download_type': 'attachment',
                    'filename': self.file.pretty_filename,
                },
            )
        )
        response = self.client.get(self.latest_url)
        self.assert3xx(response, expected_redirect_url, 302)
        assert response['Cache-Control'] == 'max-age=3600'
        assert response['Access-Control-Allow-Origin'] == '*'

    def test_filename(self):
        self.latest_url = reverse(
            'downloads.latest',
            kwargs={'addon_id': self.addon.slug, 'filename': 'lol-ignore-me.xpi'},
        )
        expected_redirect_url = absolutify(
            reverse(
                'downloads.file',
                kwargs={'file_id': self.file.pk, 'filename': self.file.pretty_filename},
            )
        )
        response = self.client.get(self.latest_url)
        self.assert3xx(response, expected_redirect_url, 302)
        assert response['Cache-Control'] == 'max-age=3600'
        assert response['Access-Control-Allow-Origin'] == '*'


class TestDownloadSource(TestCase):
    fixtures = ['base/addon_3615', 'base/admin']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(pk=3615)
        # Make sure non-ascii is ok.
        self.addon.update(slug='crosswarpex-확장')
        self.version = self.addon.current_version
        tdir = temp.gettempdir()
        self.source_file = temp.NamedTemporaryFile(suffix='.zip', dir=tdir)
        self.source_file.write(b'a' * (2**21))
        self.source_file.seek(0)
        self.version.source.save(
            os.path.basename(self.source_file.name), DjangoFile(self.source_file)
        )
        self.version.save()
        self.filename = os.path.basename(self.version.source.path)
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.group = Group.objects.create(
            name='Editors BinarySource', rules='Editors:BinarySource'
        )
        self.url = reverse('downloads.source', args=(self.version.pk,))

    def test_owner_should_be_allowed(self):
        self.client.login(email=self.user.email)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response[settings.XSENDFILE_HEADER]
        assert 'Content-Disposition' in response
        filename = smart_str(self.filename)
        content_disposition = response['Content-Disposition']
        assert filename in decode_http_header_value(content_disposition)
        expected_path = smart_str(self.version.source.path)
        xsendfile_header = decode_http_header_value(response[settings.XSENDFILE_HEADER])
        assert xsendfile_header == expected_path

    def test_anonymous_should_not_be_allowed(self):
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version(self):
        self.version.delete()
        GroupUser.objects.create(user=self.user, group=self.group)
        self.client.login(email=self.user.email)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_group_binarysource_should_be_allowed(self):
        GroupUser.objects.create(user=self.user, group=self.group)
        self.client.login(email=self.user.email)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response[settings.XSENDFILE_HEADER]
        assert 'Content-Disposition' in response
        filename = smart_str(self.filename)
        content_disposition = response['Content-Disposition']
        assert filename in decode_http_header_value(content_disposition)
        expected_path = smart_str(self.version.source.path)
        xsendfile_header = decode_http_header_value(response[settings.XSENDFILE_HEADER])
        assert xsendfile_header == expected_path

    def test_no_source_should_go_in_404(self):
        self.version.source = None
        self.version.save()
        response = self.client.get(self.url)
        assert response.status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_returns_404(self):
        """File downloading isn't allowed for unlisted addons."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: True)
    def test_download_for_addon_owner_deleted(self):
        self.addon.delete()
        assert self.client.get(self.url).status_code == 404
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: True)
    @mock.patch.object(acl, 'is_unlisted_addons_viewer_or_reviewer', lambda user: True)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_reviewer(self):
        """File downloading isn't allowed for any kind of reviewer, need
        admin."""
        assert self.client.get(self.url).status_code == 404

        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    def test_download_for_admin(self):
        """File downloading is allowed for admins."""
        self.grant_permission(self.user, 'Reviews:Admin')
        self.addon.authors.clear()
        self.client.login(email=self.user.email)
        assert self.client.get(self.url).status_code == 200

        # Even unlisted.
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200

        # Even disabled.
        self.addon.update(disabled_by_user=True)
        assert self.client.get(self.url).status_code == 200

        # Even disabled (bis).
        self.version.file.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.url).status_code == 200

        # Even disabled (ter).
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.url).status_code == 200

        # Even deleted!
        self.addon.delete()
        assert self.client.get(self.url).status_code == 200
