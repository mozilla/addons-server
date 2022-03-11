import os

from django.conf import settings
from django.utils.encoding import smart_str
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.urls import reverse

from urllib.parse import quote

from unittest import mock

from pyquery import PyQuery

from olympia import amo
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonRegionalRestrictions
from olympia.amo.templatetags.jinja_helpers import user_media_url
from olympia.amo.tests import TestCase, addon_factory
from olympia.amo.utils import urlencode, urlparams
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
        assert response['Content-Type'] == 'application/xhtml+xml'

        # pyquery is annoying to use with XML and namespaces. Use the HTML
        # parser, but do check that xmlns attribute is present (required by
        # Firefox for the notes to be shown properly).
        doc = PyQuery(response.content, parser='html')
        assert doc('html').attr('xmlns') == 'http://www.w3.org/1999/xhtml'
        assert doc('p').html() == 'Fix for an important bug'

        # Test update info in another language.
        with self.activate(locale='fr'):
            self.url = self.url = reverse(
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
        self.file_url = reverse('downloads.file', args=[self.file.id])
        self.latest_url = reverse('downloads.latest', args=[self.addon.slug])

    def assert_served_by_host(self, response, host, file_=None):
        if not file_:
            file_ = self.file
        assert response.status_code == 302
        assert response.url == (
            urlparams(
                f'{host}{self.addon.id}/{quote(file_.filename)}',
                filehash=file_.hash,
            )
        )
        assert response['X-Target-Digest'] == file_.hash
        assert response['Access-Control-Allow-Origin'] == '*'

    def assert_served_internally(self, response, guarded=True, attachment=False):
        assert response.status_code == 200
        file_path = self.file.guarded_file_path if guarded else self.file.file_path
        assert response[settings.XSENDFILE_HEADER] == file_path
        assert response['Access-Control-Allow-Origin'] == '*'

        if attachment:
            assert response.has_header('Content-Disposition')
            assert response['Content-Disposition'] == 'attachment'
        else:
            assert not response.has_header('Content-Disposition')

    def assert_served_locally(self, response, file_=None, attachment=False):
        path = user_media_url('addons')
        if attachment:
            path += '_attachments/'
        self.assert_served_by_host(response, path, file_)

    def assert_served_by_redirecting_to_cdn(
        self, response, file_=None, attachment=False
    ):
        assert response.url.startswith(settings.MEDIA_URL)
        assert response.url.startswith('http')
        assert response['Vary'] == 'X-Country-Code'
        self.assert_served_locally(response, file_=file_, attachment=attachment)


class TestDownloadsUnlistedVersions(TestDownloadsBase):
    def setUp(self):
        super().setUp()
        self.make_addon_unlisted(self.addon)

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: False)
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

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.assert_served_internally(self.client.get(self.file_url), False)
        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), False, attachment=True)

        # Even allowed to bypass georestrictions.
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        self.assert_served_internally(
            self.client.get(url, HTTP_X_COUNTRY_CODE='fr'), False, attachment=True
        )

        # Latest shouldn't work as it's only for latest public listed version.
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: True)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_reviewer(self):
        """File downloading isn't allowed for reviewers."""
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers."""
        self.assert_served_internally(self.client.get(self.file_url), False)
        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), False, attachment=True)

        # Even allowed to bypass georestrictions.
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        self.assert_served_internally(
            self.client.get(url, HTTP_X_COUNTRY_CODE='fr'), False, attachment=True
        )

        # Latest shouldn't work as it's only for latest public listed version.
        assert self.client.get(self.latest_url).status_code == 404


class TestDownloadsUnlistedAddonDeleted(TestDownloadsUnlistedVersions):
    # Everything should work the same for unlisted when the addon is deleted
    # except developers can no longer access.
    def setUp(self):
        super().setUp()
        self.addon.delete()

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: False)
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

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers, using guarded
        file path since the addon is deleted."""
        self.assert_served_internally(self.client.get(self.file_url), True)
        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), True, attachment=True)

        # Even allowed to bypass georestrictions.
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        self.assert_served_internally(
            self.client.get(url, HTTP_X_COUNTRY_CODE='fr'), True, attachment=True
        )

        # Latest shouldn't work as it's only for latest public listed version.
        assert self.client.get(self.latest_url).status_code == 404


class TestDownloads(TestDownloadsBase):
    def test_file_404(self):
        response = self.client.get(reverse('downloads.file', args=[234]))
        assert response.status_code == 404

    def test_public(self):
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        self.assert_served_by_redirecting_to_cdn(self.client.get(self.file_url))

    def test_public_addon_unreviewed_file(self):
        self.file.status = amo.STATUS_AWAITING_REVIEW
        self.file.save()
        self.assert_served_by_redirecting_to_cdn(self.client.get(self.file_url))

    def test_unreviewed_addon(self):
        self.addon.status = amo.STATUS_NULL
        self.addon.save()
        self.assert_served_by_redirecting_to_cdn(self.client.get(self.file_url))

    def test_type_attachment(self):
        self.assert_served_by_redirecting_to_cdn(self.client.get(self.file_url))
        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_by_redirecting_to_cdn(self.client.get(url), attachment=True)

    def test_trailing_filename(self):
        url = self.file_url + self.file.filename
        self.assert_served_by_redirecting_to_cdn(self.client.get(url))

    def test_null_datestatuschanged(self):
        self.file.update(datestatuschanged=None)
        self.assert_served_by_redirecting_to_cdn(self.client.get(self.file_url))

    def test_unicode_url(self):
        self.file.update(filename='图像浏览器-0.5-fx.xpi')
        self.assert_served_by_redirecting_to_cdn(self.client.get(self.file_url))

    def test_deleted(self):
        self.addon.delete()
        assert self.client.get(self.file_url).status_code == 404

    def test_georestricted(self):
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['FR', 'US']
        )
        self.assert_served_by_redirecting_to_cdn(
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
        assert self.client.login(email='regular@mozilla.com')
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_ok_for_author(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_file_disabled_ok_for_reviewer(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.client.login(email='reviewer@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_file_disabled_ok_for_admin(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_ok_for_author(self):
        # Addon should be disabled or the version unlisted at this point, so
        # it should be served internally.
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_ok_for_admin(self):
        # Addon should be disabled or the version unlisted at this point, so
        # it should be served internally.
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_user_disabled_ok_for_author(self):
        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), attachment=True)

    def test_user_disabled_ok_for_admin(self):
        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(self.client.get(url), attachment=True)


class DownloadsNonGuardedMixin:
    def test_ok_for_author(self):
        # Unlisted versions of non-disabled add-ons will be served internally
        # but not from the guarded path.
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url), guarded=False)

        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(
            self.client.get(url), attachment=True, guarded=False
        )

    def test_ok_for_admin(self):
        # Unlisted versions of non-disabled add-ons will be served internally
        # but not from the guarded path.
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url), guarded=False)

        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_internally(
            self.client.get(url), attachment=True, guarded=False
        )


class TestDisabledFileDownloads(NonPublicFileDownloadsMixin, TestDownloadsBase):
    def setUp(self):
        super().setUp()
        self.addon.update(status=amo.STATUS_DISABLED)


class TestUnlistedFileDownloads(
    DownloadsNonGuardedMixin, NonPublicFileDownloadsMixin, TestDownloadsBase
):
    def setUp(self):
        super().setUp()
        self.make_addon_unlisted(self.addon)
        self.grant_permission(
            UserProfile.objects.get(email='reviewer@mozilla.com'),
            'Addons:ReviewUnlisted',
        )


class TestUnlistedSitePermissionFileDownloads(
    DownloadsNonGuardedMixin, NonPublicFileDownloadsMixin, TestDownloadsBase
):
    def setUp(self):
        super().setUp()
        self.addon.update(type=amo.ADDON_SITE_PERMISSION)
        self.make_addon_unlisted(self.addon)
        self.grant_permission(
            UserProfile.objects.get(email='reviewer@mozilla.com'),
            'Addons:ReviewUnlisted',
        )


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


class TestUnlistedDisabledAndDeletedFileDownloads(TestDisabledFileDownloads):
    # Like TestDownloadsUnlistedAddonDeleted above, nothing should change for
    # reviewers and admins if the add-on is deleted in addition to being
    # disabled and the version unlisted. Authors should no longer have access.
    def setUp(self):
        super().setUp()
        self.addon.delete()

    def test_user_disabled_ok_for_author(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.login(email='g@gmail.com')
        assert self.client.get(self.file_url).status_code == 404

    def test_ok_for_author(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='g@gmail.com')
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_ok_for_author(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='g@gmail.com')
        assert self.client.get(self.file_url).status_code == 404


class TestUnlistedDisabledAndDeletedSitePermissionFileDownloads(
    TestUnlistedDisabledAndDeletedFileDownloads
):
    def setUp(self):
        super().setUp()
        self.addon.update(type=amo.ADDON_SITE_PERMISSION)


class TestDownloadsLatest(TestDownloadsBase):
    def test_404(self):
        url = reverse('downloads.latest', args=[123])
        assert self.client.get(url).status_code == 404

    def test_type_none(self):
        response = self.client.get(self.latest_url)
        assert response.status_code == 302
        url = '{}?{}'.format(
            self.file.filename, urlencode({'filehash': self.file.hash})
        )
        assert response['Location'].endswith(url), response['Location']

    def test_success(self):
        assert self.addon.current_version
        self.assert_served_by_redirecting_to_cdn(self.client.get(self.latest_url))

    def test_type(self):
        url = reverse(
            'downloads.latest',
            kwargs={'addon_id': self.addon.slug, 'type': 'attachment'},
        )
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_platform_and_type(self):
        # 'platform' should just be ignored nowadays.
        url = reverse(
            'downloads.latest',
            kwargs={'addon_id': self.addon.slug, 'platform': 5, 'type': 'attachment'},
        )
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_trailing_filename(self):
        url = reverse(
            'downloads.latest',
            kwargs={'addon_id': self.addon.slug, 'type': 'attachment'},
        )
        url += self.file.filename
        self.assert_served_locally(self.client.get(url), attachment=True)


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

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_returns_404(self):
        """File downloading isn't allowed for unlisted addons."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership', lambda *args, **kwargs: True)
    def test_download_for_addon_owner_deleted(self):
        self.addon.delete()
        assert self.client.get(self.url).status_code == 404
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: True)
    @mock.patch.object(acl, 'check_unlisted_addons_viewer_or_reviewer', lambda x: True)
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
