import json
import os
import shutil
import urlparse

from django.conf import settings
from django.core.cache import cache
from django.utils.http import http_date

from cache_nuggets.lib import Message
from mock import patch
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from files.helpers import FileViewer, DiffHelper
from files.models import File
from mkt.webapps.models import Webapp
from mkt.site.fixtures import fixture
from users.models import UserProfile

packaged_app = 'mkt/submit/tests/packaged/full-tpa.zip'
not_binary = 'manifest.webapp'
binary = 'icons/256.png'


class FilesBase(object):

    def login_as_editor(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(is_packaged=True, status=amo.WEBAPPS_UNREVIEWED_STATUS)
        self.dev = self.app.authors.all()[0]
        self.regular = UserProfile.objects.get(pk=999)
        self.version = self.app.versions.latest()
        self.file = self.version.all_files[0]

        self.versions = [self.version,
                         self.app.versions.create(
                             version='%s.1' % self.version.version)]

        self.files = [self.file,
                      File.objects.create(version=self.versions[1],
                                          filename='webapp.zip')]

        self.login_as_editor()

        for file_obj in self.files:
            src = os.path.join(settings.ROOT, packaged_app)
            try:
                os.makedirs(os.path.dirname(file_obj.file_path))
            except OSError:
                pass
            shutil.copyfile(src, file_obj.file_path)

        self.file_viewer = FileViewer(self.file, is_webapp=True)
        # Setting this to True, so we are delaying the extraction of files,
        # in the tests, the files won't be extracted.
        # Most of these tests extract as needed to.
        self.create_switch(name='delay-file-viewer')

    def tearDown(self):
        self.file_viewer.cleanup()

    def files_redirect(self, file):
        return reverse('mkt.files.redirect', args=[self.file.pk, file])

    def files_serve(self, file):
        return reverse('mkt.files.serve', args=[self.file.pk, file])

    def test_view_access_anon(self):
        self.client.logout()
        self.check_urls(403)

    def test_view_access_anon_view_unreviewed_source(self):
        self.app.update(view_source=True)
        self.file_viewer.extract()
        self.client.logout()
        self.check_urls(403)

    def test_view_access_anon_view_source(self):
        self.app.update(view_source=True, status=amo.STATUS_PUBLIC)
        self.file_viewer.extract()
        self.client.logout()
        self.check_urls(200)

    def test_view_access_editor(self):
        self.file_viewer.extract()
        self.check_urls(200)

    def test_view_access_editor_view_source(self):
        self.app.update(view_source=True)
        self.file_viewer.extract()
        self.check_urls(200)

    def test_view_access_developer(self):
        self.client.logout()
        assert self.client.login(username=self.dev.email, password='password')
        self.file_viewer.extract()
        self.check_urls(200)

    def test_view_access_reviewed(self):
        self.app.update(view_source=True)
        self.file_viewer.extract()
        self.client.logout()

        for status in amo.UNREVIEWED_STATUSES:
            self.app.update(status=status)
            self.check_urls(403)

        for status in amo.REVIEWED_STATUSES:
            self.app.update(status=status)
            self.check_urls(200)

    def test_view_access_developer_view_source(self):
        self.client.logout()
        assert self.client.login(username=self.dev.email, password='password')
        self.app.update(view_source=True)
        self.file_viewer.extract()
        self.check_urls(200)

    def test_view_access_another_developer(self):
        self.client.logout()
        assert self.client.login(username=self.regular.email,
                                 password='password')
        self.file_viewer.extract()
        self.check_urls(403)

    def test_view_access_another_developer_view_source(self):
        self.client.logout()
        assert self.client.login(username=self.regular.email,
                                 password='password')
        self.app.update(view_source=True, status=amo.STATUS_PUBLIC)
        self.file_viewer.extract()
        self.check_urls(200)

    def test_poll_extracted(self):
        self.file_viewer.extract()
        res = self.client.get(self.poll_url())
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], True)

    def test_poll_not_extracted(self):
        res = self.client.get(self.poll_url())
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], False)

    def test_poll_extracted_anon(self):
        self.client.logout()
        res = self.client.get(self.poll_url())
        eq_(res.status_code, 403)

    def test_content_headers(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url('manifest.webapp'))
        assert 'etag' in res._headers
        assert 'last-modified' in res._headers

    def test_content_headers_etag(self):
        self.file_viewer.extract()
        self.file_viewer.select('manifest.webapp')
        obj = getattr(self.file_viewer, 'left', self.file_viewer)
        etag = obj.selected.get('md5')
        res = self.client.get(self.file_url('manifest.webapp'),
                              HTTP_IF_NONE_MATCH=etag)
        eq_(res.status_code, 304)

    def test_content_headers_if_modified(self):
        self.file_viewer.extract()
        self.file_viewer.select('manifest.webapp')
        obj = getattr(self.file_viewer, 'left', self.file_viewer)
        date = http_date(obj.selected.get('modified'))
        res = self.client.get(self.file_url('manifest.webapp'),
                              HTTP_IF_MODIFIED_SINCE=date)
        eq_(res.status_code, 304)

    def test_file_header(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url(not_binary))
        eq_(res.status_code, 200)
        url = res.context['file_link']['url']
        eq_(url, reverse('reviewers.apps.review', args=[self.app.app_slug]))

    def test_file_header_anon(self):
        self.client.logout()
        self.file_viewer.extract()
        self.app.update(view_source=True, status=amo.STATUS_PUBLIC)
        res = self.client.get(self.file_url(not_binary))
        eq_(res.status_code, 200)
        url = res.context['file_link']['url']
        eq_(url, reverse('detail', args=[self.app.pk]))

    def test_content_no_file(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url())
        doc = pq(res.content)
        eq_(len(doc('#content')), 0)

    def test_no_files(self):
        res = self.client.get(self.file_url())
        eq_(res.status_code, 200)
        assert 'files' not in res.context

    @patch('waffle.switch_is_active')
    def test_no_files_switch(self, switch_is_active):
        switch_is_active.side_effect = lambda x: x != 'delay-file-viewer'
        # By setting the switch to False, we are not delaying the file
        # extraction. The files will be extracted and there will be
        # files in context.
        res = self.client.get(self.file_url())
        eq_(res.status_code, 200)
        assert 'files' in res.context

    def test_files(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url())
        eq_(res.status_code, 200)
        assert 'files' in res.context

    def test_files_anon(self):
        self.client.logout()
        res = self.client.get(self.file_url())
        eq_(res.status_code, 403)

    def test_files_file(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url(not_binary))
        eq_(res.status_code, 200)
        assert 'selected' in res.context

    def test_files_back_link(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url(not_binary))
        doc = pq(res.content)
        eq_(doc('#commands td:last').text(), 'Back to review')

    def test_files_back_link_anon(self):
        self.file_viewer.extract()
        self.client.logout()
        self.app.update(view_source=True, status=amo.STATUS_PUBLIC)
        res = self.client.get(self.file_url(not_binary))
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('#commands td:last').text(), 'Back to app')

    def test_diff_redirect(self):
        ids = self.files[0].id, self.files[1].id

        res = self.client.post(self.file_url(),
                               {'left': ids[0], 'right': ids[1]})
        eq_(res.status_code, 302)
        self.assert3xx(res, reverse('mkt.files.compare', args=ids))

    def test_browse_redirect(self):
        ids = self.files[0].id,

        res = self.client.post(self.file_url(), {'left': ids[0]})
        eq_(res.status_code, 302)
        self.assert3xx(res, reverse('mkt.files.list', args=ids))

    def test_browse_deleted_version(self):
        self.file.version.delete()
        res = self.client.post(self.file_url(), {'left': self.file.id})
        eq_(res.status_code, 404)

    def test_file_chooser(self):
        res = self.client.get(self.file_url())
        doc = pq(res.content)

        left = doc('#id_left')
        eq_(len(left), 1)

        vers = left('option')

        eq_(len(vers), 3)

        # Only one file per version on Marketplace for the time being.
        eq_(vers.eq(0).text(), '')
        f = self.versions[1].all_files[0]
        eq_(vers.eq(1).text(), '%s (%s)' % (self.versions[1].version,
                                            amo.STATUS_CHOICES_API[f.status]))
        f = self.versions[0].all_files[0]
        eq_(vers.eq(2).text(), '%s (%s)' % (self.versions[0].version,
                                            amo.STATUS_CHOICES_API[f.status]))


class TestFileViewer(FilesBase, amo.tests.WebappTestCase):
    fixtures = ['base/apps', 'base/users'] + fixture('webapp_337141')

    def poll_url(self):
        return reverse('mkt.files.poll', args=[self.file.pk])

    def file_url(self, file=None):
        args = [self.file.pk]
        if file:
            args.extend(['file', file])
        return reverse('mkt.files.list', args=args)

    def check_urls(self, status):
        for url in [self.poll_url(), self.file_url()]:
            status_code = self.client.get(url).status_code
            assert status_code == status, (
                'Request to %s returned status code %d (expected %d)' %
                    (url, status_code, status))

    def add_file(self, name, contents):
        dest = os.path.join(self.file_viewer.dest, name)
        open(dest, 'w').write(contents)

    def test_files_xss(self):
        self.file_viewer.extract()
        self.add_file('<script>alert("foo")', '')
        res = self.client.get(self.file_url())
        eq_(res.status_code, 200)
        doc = pq(res.content)
        # Note: this is text, not a DOM element, so escaped correctly.
        assert '<script>alert("' in doc('#files li a').text()

    def test_content_file(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url('manifest.webapp'))
        doc = pq(res.content)
        eq_(len(doc('#content')), 1)

    def test_content_no_file(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url())
        doc = pq(res.content)
        eq_(len(doc('#content')), 1)
        eq_(res.context['key'], 'manifest.webapp')

    def test_content_xss(self):
        self.file_viewer.extract()
        for name in ['file.txt', 'file.html', 'file.htm']:
            # If you are adding files, you need to clear out the memcache
            # file listing.
            cache.clear()
            self.add_file(name, '<script>alert("foo")</script>')
            res = self.client.get(self.file_url(name))
            doc = pq(res.content)
            # Note: this is text, not a DOM element, so escaped correctly.
            assert doc('#content').text().startswith('<script')

    def test_binary(self):
        self.file_viewer.extract()
        self.add_file('file.php', '<script>alert("foo")</script>')
        res = self.client.get(self.file_url('file.php'))
        eq_(res.status_code, 200)
        assert self.file_viewer.get_files()['file.php']['md5'] in res.content

    def test_tree_no_file(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url('doesnotexist.js'))
        eq_(res.status_code, 404)

    def test_directory(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url('doesnotexist.js'))
        eq_(res.status_code, 404)

    def test_serve_no_token(self):
        self.file_viewer.extract()
        res = self.client.get(self.files_serve(binary))
        eq_(res.status_code, 403)

    def test_serve_fake_token(self):
        self.file_viewer.extract()
        res = self.client.get(self.files_serve(binary) + '?token=aasd')
        eq_(res.status_code, 403)

    def test_serve_bad_token(self):
        self.file_viewer.extract()
        res = self.client.get(self.files_serve(binary) + '?token=a asd')
        eq_(res.status_code, 403)

    def test_serve_get_token(self):
        self.file_viewer.extract()
        res = self.client.get(self.files_redirect(binary))
        eq_(res.status_code, 302)
        url = res['Location']
        assert url.startswith(settings.STATIC_URL)
        assert urlparse.urlparse(url).query.startswith('token=')

    def test_memcache_goes_bye_bye(self):
        self.file_viewer.extract()
        res = self.client.get(self.files_redirect(binary))
        url = res['Location'][len(settings.STATIC_URL) - 1:]
        cache.clear()
        res = self.client.get(url)
        eq_(res.status_code, 403)

    def test_bounce(self):
        # Don't run this test if the server has x-sendfile turned off.
        if not settings.XSENDFILE:
            raise SkipTest()

        self.file_viewer.extract()
        res = self.client.get(self.files_redirect(binary), follow=True)
        eq_(res.status_code, 200)
        eq_(res[settings.XSENDFILE_HEADER],
            self.file_viewer.get_files().get(binary)['full'])

    @patch.object(settings, 'FILE_VIEWER_SIZE_LIMIT', 5)
    def test_file_size(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url(not_binary))
        doc = pq(res.content)
        assert doc('.error').text().startswith('File size is')

    def test_poll_failed(self):
        msg = Message('file-viewer:%s' % self.file_viewer)
        msg.save('I like cheese.')
        res = self.client.get(self.poll_url())
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['status'], False)
        eq_(data['msg'], ['I like cheese.'])

    def test_file_chooser_selection(self):
        res = self.client.get(self.file_url())
        doc = pq(res.content)

        eq_(doc('#id_left option[selected]').attr('value'),
            str(self.files[0].id))
        eq_(len(doc('#id_right option[value][selected]')), 0)


class TestDiffViewer(FilesBase, amo.tests.WebappTestCase):
    fixtures = ['base/apps', 'base/users'] + fixture('webapp_337141')

    def setUp(self):
        super(TestDiffViewer, self).setUp()
        self.file_viewer = DiffHelper(self.files[0], self.files[1],
                                      is_webapp=True)

    def poll_url(self):
        return reverse('mkt.files.compare.poll', args=[self.files[0].pk,
                                                       self.files[1].pk])

    def add_file(self, file_obj, name, contents):
        dest = os.path.join(file_obj.dest, name)
        open(dest, 'w').write(contents)

    def file_url(self, file=None):
        args = [self.files[0].pk, self.files[1].pk]
        if file:
            args.extend(['file', file])
        return reverse('mkt.files.compare', args=args)

    def check_urls(self, status):
        for url in [self.poll_url(), self.file_url()]:
            status_code = self.client.get(url).status_code
            assert status_code == status, (
                'Request to %s returned status code %d (expected %d)' %
                    (url, status_code, status))

    def test_tree_no_file(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url('doesnotexist.js'))
        eq_(res.status_code, 404)

    def test_content_file(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url(not_binary))
        doc = pq(res.content)
        eq_(len(doc('pre')), 3)

    def test_binary_serve_links(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url(binary))
        doc = pq(res.content)
        node = doc('#content-wrapper a')
        eq_(len(node), 2)
        assert node[0].text.startswith('Download 256.png')

    def test_view_both_present(self):
        self.file_viewer.extract()
        res = self.client.get(self.file_url(not_binary))
        doc = pq(res.content)
        eq_(len(doc('pre')), 3)
        eq_(len(doc('#content-wrapper p')), 4)

    def test_view_one_missing(self):
        self.file_viewer.extract()
        os.remove(os.path.join(self.file_viewer.right.dest, 'manifest.webapp'))
        res = self.client.get(self.file_url(not_binary))
        doc = pq(res.content)
        eq_(len(doc('pre')), 3)
        eq_(len(doc('#content-wrapper p')), 2)

    def test_view_left_binary(self):
        self.file_viewer.extract()
        filename = os.path.join(self.file_viewer.left.dest, 'manifest.webapp')
        open(filename, 'w').write('MZ')
        res = self.client.get(self.file_url(not_binary))
        assert 'This file is not viewable online' in res.content

    def test_view_right_binary(self):
        self.file_viewer.extract()
        filename = os.path.join(self.file_viewer.right.dest, 'manifest.webapp')
        open(filename, 'w').write('MZ')
        assert not self.file_viewer.is_diffable()
        res = self.client.get(self.file_url(not_binary))
        assert 'This file is not viewable online' in res.content

    def test_different_tree(self):
        self.file_viewer.extract()
        os.remove(os.path.join(self.file_viewer.left.dest, not_binary))
        res = self.client.get(self.file_url(not_binary))
        doc = pq(res.content)
        eq_(doc('h4:last').text(), 'Deleted files:')
        eq_(len(doc('ul.root')), 2)

    def test_file_chooser_selection(self):
        res = self.client.get(self.file_url())
        doc = pq(res.content)

        eq_(doc('#id_left option[selected]').attr('value'),
            str(self.files[0].id))
        eq_(doc('#id_right option[selected]').attr('value'),
            str(self.files[1].id))
