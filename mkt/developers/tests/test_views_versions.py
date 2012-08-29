from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from addons.models import Addon, AddonUser
from users.models import UserProfile

from mkt.submit.tests.test_views import BasePackagedAppTest


class TestAppStatus(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url('versions')

    def get_webapp(self):
        return Addon.objects.get(id=337141)

    def test_nav_link(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('#edit-addon-nav li.selected a').attr('href'),
            self.url)

    def test_items(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#version-status').length, 1)
        eq_(doc('#version-list').length, 0)
        eq_(doc('#delete-addon').length, 0)
        eq_(doc('#modal-delete').length, 0)
        eq_(doc('#modal-disable').length, 1)

    def test_soft_delete_items(self):
        self.create_switch(name='soft_delete')
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#version-status').length, 1)
        eq_(doc('#version-list').length, 0)
        eq_(doc('#delete-addon').length, 1)
        eq_(doc('#modal-delete').length, 1)
        eq_(doc('#modal-disable').length, 1)

    def test_delete_link(self):
        # Hard "Delete App" link should be visible for only incomplete apps.
        self.webapp.update(status=amo.STATUS_NULL)
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#delete-addon').length, 1)
        eq_(doc('#modal-delete').length, 1)

    def test_pending(self):
        self.webapp.update(status=amo.STATUS_PENDING)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#version-status .status-pending').length, 1)
        eq_(doc('#rejection').length, 0)

    def test_public(self):
        eq_(self.webapp.status, amo.STATUS_PUBLIC)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#version-status .status-public').length, 1)
        eq_(doc('#rejection').length, 0)

    def test_rejected(self):
        comments = "oh no you di'nt!!"
        amo.set_user(UserProfile.objects.get(username='editor'))
        amo.log(amo.LOG.REJECT_VERSION, self.webapp,
                self.webapp.current_version, user_id=999,
                details={'comments': comments, 'reviewtype': 'pending'})
        self.webapp.update(status=amo.STATUS_REJECTED)

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('#version-status')
        eq_(doc('.status-rejected').length, 1)
        eq_(doc('#rejection').length, 1)
        eq_(doc('#rejection blockquote').text(), comments)

        my_reply = 'fixed just for u, brah'
        r = self.client.post(self.url, {'release_notes': my_reply,
                                        'resubmit-app': ''})
        self.assertRedirects(r, self.url, 302)

        webapp = self.get_webapp()
        eq_(webapp.status, amo.STATUS_PENDING,
            'Reapplied apps should get marked as pending')
        eq_(unicode(webapp.versions.all()[0].releasenotes), my_reply)

    def test_items_packaged(self):
        self.webapp.update(is_packaged=True)
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#version-status').length, 1)
        eq_(doc('#version-list').length, 1)
        eq_(doc('#delete-addon').length, 0)
        eq_(doc('#modal-delete').length, 0)
        eq_(doc('#modal-disable').length, 1)

    def test_version_list_packaged(self):
        self.webapp.update(is_packaged=True)
        amo.tests.version_factory(addon=self.webapp, version='2.0',
                                  file_kw=dict(status=amo.STATUS_PENDING))
        self.webapp = self.get_webapp()
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#version-status').length, 1)
        eq_(doc('#version-list li').length, 2)
        # 1 pending and 1 public.
        eq_(doc('#version-list span.status-pending').length, 1)
        eq_(doc('#version-list span.status-public').length, 1)
        # Check version strings and order of versions.
        eq_(map(lambda x: x.text, doc('#version-list h4 a')),
            ['Version 2.0', 'Version 1.0'])
        # Check download url.
        eq_(doc('#version-list a.button.download').eq(0).attr('href'),
            self.webapp.versions.all()[0].all_files[0].get_url_path('devhub'))
        eq_(doc('#version-list a.button.download').eq(1).attr('href'),
            self.webapp.versions.all()[1].all_files[0].get_url_path('devhub'))


class TestAddVersion(BasePackagedAppTest):

    def setUp(self):
        super(TestAddVersion, self).setUp()
        self.app = amo.tests.app_factory(is_packaged=True,
                                         version_kw=dict(version='1.0'))
        self.url = self.app.get_dev_url('versions')
        self.user = UserProfile.objects.get(username='regularuser')
        AddonUser.objects.create(user=self.user, addon=self.app)

    def _post(self, expected_status=200):
        res = self.client.post(self.url, {'upload': self.upload.pk,
                                          'upload-version': ''})
        eq_(res.status_code, expected_status)
        return res

    def test_post(self):
        self.app.current_version.update(version='0.9',
                                        created=self.days_ago(1))
        self._post(302)
        version = self.app.versions.latest()
        eq_(version.version, '1.0')
        eq_(version.all_files[0].status, amo.STATUS_PENDING)

    def test_unique_version(self):
        res = self._post(200)
        self.assertFormError(res, 'upload_form', 'upload',
                             'Version 1.0 already exists')


class TestEditVersion(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.app = amo.tests.app_factory(is_packaged=True,
                                         version_kw=dict(version='1.0'))
        version = self.app.current_version
        self.url = self.app.get_dev_url('versions.edit', [version.pk])
        self.user = UserProfile.objects.get(username='regularuser')
        AddonUser.objects.create(user=self.user, addon=self.app)
        self.client.login(username='regular@mozilla.com',
                          password='password')
        eq_(self.client.get(self.url).status_code, 200)

    def test_post(self):
        rn = u'Release Notes'
        an = u'Approval Notes'
        res = self.client.post(self.url, {'releasenotes': rn,
                                          'approvalnotes': an})
        eq_(res.status_code, 302)
        ver = self.app.versions.latest()
        eq_(ver.releasenotes, rn)
        eq_(ver.approvalnotes, an)
