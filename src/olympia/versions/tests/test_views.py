# -*- coding: utf-8 -*-
import os

from django.conf import settings
from django.utils.encoding import smart_text
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.utils.http import urlquote

from unittest import mock

from pyquery import PyQuery

from olympia import amo
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import user_media_url
from olympia.amo.tests import TestCase, addon_factory
from olympia.amo.urlresolvers import reverse
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


class TestViews(TestCase):
    def setUp(self):
        super(TestViews, self).setUp()
        self.addon = addon_factory(
            slug=u'my-addôn', file_kw={'size': 1024},
            version_kw={'version': '1.0'})
        self.version = self.addon.current_version
        self.addon.current_version.update(created=self.days_ago(3))

    def test_version_update_info(self):
        self.version.release_notes = {
            'en-US': u'Fix for an important bug',
            'fr': u'Quelque chose en français.\n\nQuelque chose d\'autre.'
        }
        self.version.save()

        file_ = self.version.files.all()[0]
        file_.update(platform=amo.PLATFORM_WIN.id)

        # Copy the file to create a new one attached to the same version.
        # This tests https://github.com/mozilla/addons-server/issues/8950
        file_.pk = None
        file_.platform = amo.PLATFORM_MAC.id
        file_.save()

        response = self.client.get(
            reverse('addons.versions.update_info',
                    args=(self.addon.slug, self.version.version)))
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
            response = self.client.get(
                reverse('addons.versions.update_info',
                        args=(self.addon.slug, self.version.version)))
            assert response.status_code == 200
            assert response['Content-Type'] == 'application/xhtml+xml'
            assert b'<br/>' in response.content, (
                'Should be using XHTML self-closing tags!')
            doc = PyQuery(response.content, parser='html')
            assert doc('html').attr('xmlns') == 'http://www.w3.org/1999/xhtml'
            assert doc('p').html() == (
                u"Quelque chose en français.<br/><br/>Quelque chose d'autre.")

    def test_version_update_info_legacy_redirect(self):
        response = self.client.get('/versions/updateInfo/%s' % self.version.id,
                                   follow=True)
        url = reverse('addons.versions.update_info',
                      args=(self.version.addon.slug, self.version.version))
        self.assert3xx(response, url, 302)

    def test_version_update_info_legacy_redirect_deleted(self):
        self.version.delete()
        response = self.client.get(
            '/en-US/firefox/versions/updateInfo/%s' % self.version.id)
        assert response.status_code == 404

    def test_version_update_info_no_unlisted(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(
            reverse('addons.versions.update_info',
                    args=(self.addon.slug, self.version.version)))
        assert response.status_code == 404


class TestDownloadsBase(TestCase):
    fixtures = ['base/addon_5299_gcal', 'base/users']

    def setUp(self):
        super(TestDownloadsBase, self).setUp()
        self.addon = Addon.objects.get(id=5299)
        self.file = File.objects.get(id=33046)
        self.file_url = reverse('downloads.file', args=[self.file.id])
        self.latest_url = reverse('downloads.latest', args=[self.addon.slug])

    def assert_served_by_host(self, response, host, file_=None):
        if not file_:
            file_ = self.file
        assert response.status_code == 302
        assert response.url == (
            urlparams('%s%s/%s' % (
                host, self.addon.id, urlquote(file_.filename)
            ), filehash=file_.hash))
        assert response['X-Target-Digest'] == file_.hash
        assert response['Access-Control-Allow-Origin'] == '*'

    def assert_served_internally(self, response, guarded=True):
        assert response.status_code == 200
        file_path = (self.file.guarded_file_path if guarded else
                     self.file.file_path)
        assert response[settings.XSENDFILE_HEADER] == file_path
        assert response['Access-Control-Allow-Origin'] == '*'

    def assert_served_locally(self, response, file_=None, attachment=False):
        path = user_media_url('addons')
        if attachment:
            path += '_attachments/'
        self.assert_served_by_host(response, path, file_)

    def assert_served_by_cdn(self, response, file_=None):
        assert response.url.startswith(settings.MEDIA_URL)
        assert response.url.startswith('http')
        self.assert_served_by_host(response, user_media_url('addons'), file_)


class TestDownloadsUnlistedVersions(TestDownloadsBase):

    def setUp(self):
        super(TestDownloadsUnlistedVersions, self).setUp()
        self.make_addon_unlisted(self.addon)

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_returns_404(self):
        """File downloading isn't allowed for unlisted addons."""
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.assert_served_internally(self.client.get(self.file_url), False)
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: True)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_reviewer(self):
        """File downloading isn't allowed for reviewers."""
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers."""
        self.assert_served_internally(self.client.get(self.file_url), False)
        assert self.client.get(self.latest_url).status_code == 404


class TestDownloadsUnlistedAddonDeleted(TestDownloadsUnlistedVersions):
    # Everything should work the same for unlisted when the addon is deleted
    # except developers can no longer access.
    def setUp(self):
        super().setUp()
        self.addon.delete()

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers, using guarded
        file path since the addon is deleted."""
        self.assert_served_internally(self.client.get(self.file_url), True)
        assert self.client.get(self.latest_url).status_code == 404


class TestDownloads(TestDownloadsBase):

    def test_file_404(self):
        response = self.client.get(reverse('downloads.file', args=[234]))
        assert response.status_code == 404

    def test_public(self):
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        self.assert_served_by_cdn(self.client.get(self.file_url))

    def test_public_addon_unreviewed_file(self):
        self.file.status = amo.STATUS_AWAITING_REVIEW
        self.file.save()
        self.assert_served_locally(self.client.get(self.file_url))

    def test_unreviewed_addon(self):
        self.addon.status = amo.STATUS_NULL
        self.addon.save()
        self.assert_served_locally(self.client.get(self.file_url))

    def test_type_attachment(self):
        self.assert_served_by_cdn(self.client.get(self.file_url))
        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_trailing_filename(self):
        url = self.file_url + self.file.filename
        self.assert_served_by_cdn(self.client.get(url))

    def test_null_datestatuschanged(self):
        self.file.update(datestatuschanged=None)
        self.assert_served_locally(self.client.get(self.file_url))

    def test_unicode_url(self):
        self.file.update(filename=u'图像浏览器-0.5-fx.xpi')
        self.assert_served_by_cdn(self.client.get(self.file_url))

    def test_deleted(self):
        self.addon.delete()
        assert self.client.get(self.file_url).status_code == 404


class TestDisabledFileDownloads(TestDownloadsBase):

    def test_admin_disabled_404(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.file_url).status_code == 404

    def test_user_disabled_404(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_anon_404(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_unprivileged_404(self):
        assert self.client.login(email='regular@mozilla.com')
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_ok_for_author(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_file_disabled_ok_for_reviewer(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.client.login(email='reviewer@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_file_disabled_ok_for_admin(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_admin_disabled_ok_for_author(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_admin_disabled_ok_for_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_user_disabled_ok_for_author(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_user_disabled_ok_for_admin(self):
        self.addon.update(disabled_by_user=True)
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))


class TestUnlistedDisabledFileDownloads(TestDisabledFileDownloads):

    def setUp(self):
        super(TestDisabledFileDownloads, self).setUp()
        self.make_addon_unlisted(self.addon)
        self.grant_permission(
            UserProfile.objects.get(email='reviewer@mozilla.com'),
            'Addons:ReviewUnlisted')


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

    def test_admin_disabled_ok_for_author(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='g@gmail.com')
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_ok_for_author(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='g@gmail.com')
        assert self.client.get(self.file_url).status_code == 404


class TestDownloadsLatest(TestDownloadsBase):

    def setUp(self):
        super(TestDownloadsLatest, self).setUp()
        self.platform = 5

    def test_404(self):
        url = reverse('downloads.latest', args=[123])
        assert self.client.get(url).status_code == 404

    def test_type_none(self):
        response = self.client.get(self.latest_url)
        assert response.status_code == 302
        url = '%s?%s' % (self.file.filename,
                         urlencode({'filehash': self.file.hash}))
        assert response['Location'].endswith(url), response['Location']

    def test_success(self):
        assert self.addon.current_version
        self.assert_served_by_cdn(self.client.get(self.latest_url))

    def test_platform(self):
        # We still match PLATFORM_ALL.
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 5})
        self.assert_served_by_cdn(self.client.get(url))

        # And now we match the platform in the url.
        self.file.platform = self.platform
        self.file.save()
        self.assert_served_by_cdn(self.client.get(url))

        # But we can't match platform=3.
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 3})
        assert self.client.get(url).status_code == 404

    def test_type(self):
        url = reverse('downloads.latest', kwargs={'addon_id': self.addon.slug,
                                                  'type': 'attachment'})
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_platform_and_type(self):
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 5,
                              'type': 'attachment'})
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_trailing_filename(self):
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 5,
                              'type': 'attachment'})
        url += self.file.filename
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_platform_multiple_objects(self):
        file_ = File.objects.create(
            platform=3, version=self.file.version, filename='unst.xpi',
            status=self.file.status)
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 3})
        self.assert_served_locally(self.client.get(url), file_=file_)


class TestDownloadSource(TestCase):
    fixtures = ['base/addon_3615', 'base/admin']

    def setUp(self):
        super(TestDownloadSource, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        # Make sure non-ascii is ok.
        self.addon.update(slug=u'crosswarpex-확장')
        self.version = self.addon.current_version
        tdir = temp.gettempdir()
        self.source_file = temp.NamedTemporaryFile(suffix='.zip', dir=tdir)
        self.source_file.write(b'a' * (2 ** 21))
        self.source_file.seek(0)
        self.version.source = DjangoFile(self.source_file)
        self.version.save()
        self.filename = os.path.basename(self.version.source.path)
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.group = Group.objects.create(
            name='Editors BinarySource',
            rules='Editors:BinarySource'
        )
        self.url = reverse('downloads.source', args=(self.version.pk, ))

    def test_owner_should_be_allowed(self):
        self.client.login(email=self.user.email)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response[settings.XSENDFILE_HEADER]
        assert 'Content-Disposition' in response
        filename = smart_text(self.filename)
        content_disposition = response['Content-Disposition']
        assert filename in decode_http_header_value(content_disposition)
        expected_path = smart_text(self.version.source.path)
        xsendfile_header = decode_http_header_value(
            response[settings.XSENDFILE_HEADER])
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
        filename = smart_text(self.filename)
        content_disposition = response['Content-Disposition']
        assert filename in decode_http_header_value(content_disposition)
        expected_path = smart_text(self.version.source.path)
        xsendfile_header = decode_http_header_value(
            response[settings.XSENDFILE_HEADER])
        assert xsendfile_header == expected_path

    def test_no_source_should_go_in_404(self):
        self.version.source = None
        self.version.save()
        response = self.client.get(self.url)
        assert response.status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_returns_404(self):
        """File downloading isn't allowed for unlisted addons."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: True)
    def test_download_for_addon_owner_deleted(self):
        self.addon.delete()
        assert self.client.get(self.url).status_code == 404
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: True)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
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
        self.version.files.all().update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.url).status_code == 200

        # Even disabled (ter).
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.url).status_code == 200

        # Even deleted!
        self.addon.delete()
        assert self.client.get(self.url).status_code == 200
