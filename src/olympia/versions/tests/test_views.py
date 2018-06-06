# -*- coding: utf-8 -*-
import os

from django.conf import settings
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.test.utils import override_settings
from django.utils.http import urlquote

import mock
import pytest

from pyquery import PyQuery

from olympia import amo
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import user_media_url
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlencode, urlparams
from olympia.files.models import File
from olympia.users.models import UserProfile
from olympia.versions import views


class TestViews(TestCase):
    def setUp(self):
        super(TestViews, self).setUp()
        self.addon = addon_factory(
            slug=u'my-addôn', file_kw={'size': 1024},
            version_kw={'version': '1.0'})
        self.addon.current_version.update(created=self.days_ago(3))
        self.url_list = reverse('addons.versions', args=[self.addon.slug])
        self.url_detail = reverse(
            'addons.versions',
            args=[self.addon.slug, self.addon.current_version.version])

    @mock.patch.object(views, 'PER_PAGE', 1)
    def test_version_detail(self):
        version = version_factory(addon=self.addon, version='2.0')
        version.update(created=self.days_ago(2))
        version = version_factory(addon=self.addon, version='2.1')
        version.update(created=self.days_ago(1))
        urls = [(v.version, reverse('addons.versions',
                                    args=[self.addon.slug, v.version]))
                for v in self.addon.versions.all()]

        version, url = urls[0]
        assert version == '2.1'
        response = self.client.get(url, follow=True)
        self.assert3xx(
            response, self.url_list + '?page=1#version-%s' % version)

        version, url = urls[1]
        assert version == '2.0'
        response = self.client.get(url, follow=True)
        self.assert3xx(
            response, self.url_list + '?page=2#version-%s' % version)

        version, url = urls[2]
        assert version == '1.0'
        response = self.client.get(url, follow=True)
        self.assert3xx(
            response, self.url_list + '?page=3#version-%s' % version)

    def test_version_detail_404(self):
        bad_pk = self.addon.current_version.pk + 42
        response = self.client.get(reverse('addons.versions',
                                           args=[self.addon.slug, bad_pk]))
        assert response.status_code == 404

        bad_pk = u'lolé'
        response = self.client.get(reverse('addons.versions',
                                           args=[self.addon.slug, bad_pk]))
        assert response.status_code == 404

    def get_content(self):
        response = self.client.get(self.url_list)
        assert response.status_code == 200
        return PyQuery(response.content)

    @pytest.mark.xfail(reason='Temporarily hidden, #5431')
    def test_version_source(self):
        self.addon.update(view_source=True)
        assert len(self.get_content()('a.source-code')) == 1

    def test_version_no_source_one(self):
        self.addon.update(view_source=False)
        assert len(self.get_content()('a.source-code')) == 0

    def test_version_addon_not_public(self):
        self.addon.update(view_source=True, status=amo.STATUS_NULL)
        response = self.client.get(self.url_list)
        assert response.status_code == 404

    def test_version_link(self):
        version = self.addon.current_version.version
        doc = self.get_content()
        link = doc('.version h3 > a').attr('href')
        assert link == self.url_detail
        assert doc('.version').attr('id') == 'version-%s' % version

    def test_version_list_button_shows_download_anyway(self):
        first_version = self.addon.current_version
        first_version.update(created=self.days_ago(1))
        first_file = first_version.files.all()[0]
        second_version = version_factory(addon=self.addon, version='2.0')
        second_file = second_version.files.all()[0]
        doc = self.get_content()
        links = doc('.download-anyway a')
        assert links
        assert links[0].attrib['href'] == second_file.get_url_path(
            'version-history', attachment=True)
        assert links[1].attrib['href'] == first_file.get_url_path(
            'version-history', attachment=True)

    def test_version_list_doesnt_show_unreviewed_versions_public_addon(self):
        version = self.addon.current_version.version
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            version='2.1')
        doc = self.get_content()
        assert len(doc('.version')) == 1
        assert doc('.version').attr('id') == 'version-%s' % version

    def test_version_list_does_show_unreviewed_versions_unreviewed_addon(self):
        version = self.addon.current_version.version
        file_ = self.addon.current_version.files.all()[0]
        file_.update(status=amo.STATUS_AWAITING_REVIEW)
        doc = self.get_content()
        assert len(doc('.version')) == 1
        assert doc('.version').attr('id') == 'version-%s' % version

    def test_version_list_for_unlisted_addon_returns_404(self):
        """Unlisted addons are not listed and have no version list."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url_list).status_code == 404

    def test_version_detail_does_not_return_unlisted_versions(self):
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url_detail)
        assert response.status_code == 404

    def test_version_list_file_size_uses_binary_prefix(self):
        response = self.client.get(self.url_list)
        assert '1.0 KiB' in response.content

    def test_version_list_no_compat_displayed_if_not_necessary(self):
        doc = self.get_content()
        compat_info = doc('.compat').text()
        assert compat_info
        assert 'Firefox 4.0.99 and later' in compat_info

        self.addon.update(type=amo.ADDON_DICT)
        doc = self.get_content()
        compat_info = doc('.compat').text()
        assert not compat_info


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

    def assert_served_internally(self, response, guarded=True):
        assert response.status_code == 200
        file_path = (self.file.guarded_file_path if guarded else
                     self.file.file_path)
        assert response[settings.XSENDFILE_HEADER] == file_path

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


class TestDownloads(TestDownloadsBase):

    def test_file_404(self):
        r = self.client.get(reverse('downloads.file', args=[234]))
        assert r.status_code == 404

    @override_settings(MEDIA_URL='http://testserver/media/')
    def test_public(self):
        assert self.addon.status == amo.STATUS_PUBLIC
        assert self.file.status == amo.STATUS_PUBLIC
        self.assert_served_by_cdn(self.client.get(self.file_url))

    def test_public_addon_unreviewed_file(self):
        self.file.status = amo.STATUS_AWAITING_REVIEW
        self.file.save()
        self.assert_served_locally(self.client.get(self.file_url))

    def test_unreviewed_addon(self):
        self.addon.status = amo.STATUS_PENDING
        self.addon.save()
        self.assert_served_locally(self.client.get(self.file_url))

    @override_settings(MEDIA_URL='http://testserver/media/')
    def test_type_attachment(self):
        self.assert_served_by_cdn(self.client.get(self.file_url))
        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_nonbrowser_app(self):
        url = self.file_url.replace('firefox', 'thunderbird')
        self.assert_served_locally(self.client.get(url), attachment=True)

    @override_settings(MEDIA_URL='http://testserver/media/')
    def test_trailing_filename(self):
        url = self.file_url + self.file.filename
        self.assert_served_by_cdn(self.client.get(url))

    def test_null_datestatuschanged(self):
        self.file.update(datestatuschanged=None)
        self.assert_served_locally(self.client.get(self.file_url))

    def test_unicode_url(self):
        self.file.update(filename=u'图像浏览器-0.5-fx.xpi')

        self.assert_served_by_cdn(self.client.get(self.file_url))


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


class TestDownloadsLatest(TestDownloadsBase):

    def setUp(self):
        super(TestDownloadsLatest, self).setUp()
        self.platform = 5

    def test_404(self):
        url = reverse('downloads.latest', args=[123])
        assert self.client.get(url).status_code == 404

    def test_type_none(self):
        r = self.client.get(self.latest_url)
        assert r.status_code == 302
        url = '%s?%s' % (self.file.filename,
                         urlencode({'filehash': self.file.hash}))
        assert r['Location'].endswith(url), r['Location']

    @override_settings(MEDIA_URL='http://testserver/media/')
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
        f = File.objects.create(platform=3, version=self.file.version,
                                filename='unst.xpi', status=self.file.status)
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 3})
        self.assert_served_locally(self.client.get(url), file_=f)


@override_settings(XSENDFILE=True)
class TestDownloadSource(TestCase):
    fixtures = ['base/addon_3615', 'base/admin']

    def setUp(self):
        super(TestDownloadSource, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        # Make sure non-ascii is ok.
        self.addon.update(slug=u'crosswarpex-확장')
        self.version = self.addon.current_version
        tdir = temp.gettempdir()
        self.source_file = temp.NamedTemporaryFile(suffix=".zip", dir=tdir)
        self.source_file.write('a' * (2 ** 21))
        self.source_file.seek(0)
        self.version.source = DjangoFile(self.source_file)
        self.version.save()
        self.filename = os.path.basename(self.version.source.path)
        self.user = UserProfile.objects.get(email="del@icio.us")
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
        filename = self.filename
        if not isinstance(filename, unicode):
            filename = filename.decode('utf8')
        assert filename in response['Content-Disposition'].decode('utf8')
        path = self.version.source.path
        if not isinstance(path, unicode):
            path = path.decode('utf8')
        assert response[settings.XSENDFILE_HEADER].decode('utf8') == path

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
        filename = self.filename
        if not isinstance(filename, unicode):
            filename = filename.decode('utf8')
        assert filename in response['Content-Disposition'].decode('utf8')
        path = self.version.source.path
        if not isinstance(path, unicode):
            path = path.decode('utf8')
        assert response[settings.XSENDFILE_HEADER].decode('utf8') == path

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

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: True)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_reviewer(self):
        """File downloading isn't allowed for reviewers."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'is_reviewer', lambda request, addon: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200
