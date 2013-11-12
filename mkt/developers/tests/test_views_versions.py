import datetime
import mock
from nose.tools import eq_
import os
from pyquery import PyQuery as pq

from django.conf import settings

import amo
import amo.tests
from amo.tests import req_factory_factory
from addons.models import Addon, AddonUser
from comm.models import CommunicationNote
from devhub.models import ActivityLog, AppLog
from editors.models import EscalationQueue, EditorSubscription
from files.models import File
from users.models import UserProfile
from versions.models import Version

from mkt.developers.models import PreloadTestPlan
from mkt.developers.views import preload_submit, status
from mkt.site.fixtures import fixture
from mkt.submit.tests.test_views import BasePackagedAppTest


class TestVersion(amo.tests.TestCase):
    fixtures = fixture('group_admin', 'user_999', 'user_admin',
                       'user_admin_group', 'webapp_337141')

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url('versions')

    def get_webapp(self):
        return Addon.objects.get(id=337141)

    def test_nav_link(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('.edit-addon-nav li.selected a').attr('href'),
            self.url)

    def test_items(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#version-status').length, 1)
        eq_(doc('#version-list').length, 0)
        eq_(doc('#delete-addon').length, 1)
        eq_(doc('#modal-delete').length, 1)
        eq_(doc('#modal-disable').length, 1)
        eq_(doc('#modal-delete-version').length, 0)

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

    def test_blocked(self):
        self.webapp.update(status=amo.STATUS_BLOCKED)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#version-status .status-blocked').length, 1)
        eq_(doc('#rejection').length, 0)
        assert 'blocked by a site administrator' in doc.text()

    def test_rejected(self):
        comments = "oh no you di'nt!!"
        amo.set_user(UserProfile.objects.get(username='admin'))
        amo.log(amo.LOG.REJECT_VERSION, self.webapp,
                self.webapp.current_version, user_id=999,
                details={'comments': comments, 'reviewtype': 'pending'})
        self.webapp.update(status=amo.STATUS_REJECTED)
        (self.webapp.versions.latest()
                             .all_files[0].update(status=amo.STATUS_DISABLED))

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('#version-status')
        eq_(doc('.status-rejected').length, 1)
        eq_(doc('#rejection').length, 1)
        eq_(doc('#rejection blockquote').text(), comments)

        my_reply = 'fixed just for u, brah'
        r = self.client.post(self.url, {'notes': my_reply,
                                        'resubmit-app': ''})
        self.assertRedirects(r, self.url, 302)

        webapp = self.get_webapp()
        eq_(webapp.status, amo.STATUS_PENDING,
            'Reapplied apps should get marked as pending')
        eq_(webapp.versions.latest().all_files[0].status, amo.STATUS_PENDING,
            'Files for reapplied apps should get marked as pending')
        action = amo.LOG.WEBAPP_RESUBMIT
        assert AppLog.objects.filter(
            addon=webapp, activity_log__action=action.id).exists(), (
                "Didn't find `%s` action in logs." % action.short)

    def test_comm_thread_after_resubmission(self):
        self.create_switch('comm-dashboard')
        self.webapp.update(status=amo.STATUS_REJECTED)
        amo.set_user(UserProfile.objects.get(username='admin'))
        (self.webapp.versions.latest()
                             .all_files[0].update(status=amo.STATUS_DISABLED))
        my_reply = 'no give up'
        self.client.post(self.url, {'notes': my_reply,
                                    'resubmit-app': ''})
        notes = CommunicationNote.objects.all()
        eq_(notes.count(), 1)
        eq_(notes[0].body, my_reply)

    def test_rejected_packaged(self):
        self.webapp.update(is_packaged=True)
        comments = "oh no you di'nt!!"
        amo.set_user(UserProfile.objects.get(username='admin'))
        amo.log(amo.LOG.REJECT_VERSION, self.webapp,
                self.webapp.current_version, user_id=999,
                details={'comments': comments, 'reviewtype': 'pending'})
        self.webapp.update(status=amo.STATUS_REJECTED)
        (self.webapp.versions.latest()
                             .all_files[0].update(status=amo.STATUS_DISABLED))

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('#version-status')
        eq_(doc('.status-rejected').length, 1)
        eq_(doc('#rejection').length, 1)
        eq_(doc('#rejection blockquote').text(), comments)


@mock.patch('mkt.webapps.tasks.update_cached_manifests.delay', new=mock.Mock)
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

    def test_post_subscribers(self):
        # Same test as above, but add a suscriber. We only want to make sure
        # we are not causing a traceback because of that.
        reviewer = UserProfile.objects.create(email='foo@example.com')
        self.grant_permission(reviewer, 'Apps:Review')
        EditorSubscription.objects.create(addon=self.app, user=reviewer)
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

    def test_pending_on_new_version(self):
        # Test app rejection, then new version, updates app status to pending.
        self.app.current_version.update(version='0.9',
                                        created=self.days_ago(1))
        self.app.update(status=amo.STATUS_REJECTED)
        files = File.objects.filter(version__addon=self.app)
        files.update(status=amo.STATUS_DISABLED)
        self._post(302)
        self.app.reload()
        version = self.app.versions.latest()
        eq_(version.version, '1.0')
        eq_(version.all_files[0].status, amo.STATUS_PENDING)
        eq_(self.app.status, amo.STATUS_PENDING)

    @mock.patch('mkt.developers.views.run_validator')
    def test_prefilled_features(self, run_validator_):
        run_validator_.return_value = '{"feature_profile": ["apps", "audio"]}'

        self.app.current_version.update(version='0.9',
                                        created=self.days_ago(1))

        # All features should be disabled.
        features = self.app.current_version.features.to_dict()
        eq_(any(features.values()), False)

        self._post(302)

        # In this new version we should be prechecked new ones.
        features = self.app.versions.latest().features.to_dict()
        for key, feature in features.iteritems():
            eq_(feature, key in ('has_apps', 'has_audio'))

    def test_blocklist_on_new_version(self):
        # Test app blocked, then new version, doesn't update app status, and
        # app shows up in escalation queue.
        self.app.current_version.update(version='0.9',
                                        created=self.days_ago(1))
        self.app.update(status=amo.STATUS_BLOCKED)
        files = File.objects.filter(version__addon=self.app)
        files.update(status=amo.STATUS_DISABLED)
        self._post(302)
        version = self.app.versions.latest()
        eq_(version.version, '1.0')
        eq_(version.all_files[0].status, amo.STATUS_PENDING)
        self.app.update_status()
        eq_(self.app.status, amo.STATUS_BLOCKED)
        assert EscalationQueue.objects.filter(addon=self.app).exists(), (
            'App not in escalation queue')

    def test_new_version_when_incomplete(self):
        self.app.current_version.update(version='0.9',
                                        created=self.days_ago(1))
        self.app.update(status=amo.STATUS_NULL)
        files = File.objects.filter(version__addon=self.app)
        files.update(status=amo.STATUS_DISABLED)
        self._post(302)
        self.app.reload()
        version = self.app.versions.latest()
        eq_(version.version, '1.0')
        eq_(version.all_files[0].status, amo.STATUS_PENDING)
        eq_(self.app.status, amo.STATUS_PENDING)


class TestVersionPackaged(amo.tests.WebappTestCase):
    fixtures = fixture('user_999', 'webapp_337141')

    def setUp(self):
        super(TestVersionPackaged, self).setUp()
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        self.app.update(is_packaged=True)
        self.app = self.get_app()
        self.url = self.app.get_dev_url('versions')
        self.delete_url = self.app.get_dev_url('versions.delete')

    def test_items_packaged(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#version-status').length, 1)
        eq_(doc('#version-list').length, 1)
        eq_(doc('#delete-addon').length, 1)
        eq_(doc('#modal-delete').length, 1)
        eq_(doc('#modal-disable').length, 1)
        eq_(doc('#modal-delete-version').length, 1)

    def test_version_list_packaged(self):
        self.app.update(is_packaged=True)
        amo.tests.version_factory(addon=self.app, version='2.0',
                                  file_kw=dict(status=amo.STATUS_PENDING))
        self.app = self.get_app()
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#version-status').length, 1)
        eq_(doc('#version-list tbody tr').length, 2)
        # 1 pending and 1 public.
        eq_(doc('#version-list span.status-pending').length, 1)
        eq_(doc('#version-list span.status-public').length, 1)
        # Check version strings and order of versions.
        eq_(map(lambda x: x.text, doc('#version-list h4 a')),
            ['2.0', '1.0'])
        # There should be 2 delete buttons.
        eq_(doc('#version-list a.delete-version.button').length, 2)
        # Check download url.
        eq_(doc('#version-list a.download').eq(0).attr('href'),
            self.app.versions.all()[0].all_files[0].get_url_path(''))
        eq_(doc('#version-list a.download').eq(1).attr('href'),
            self.app.versions.all()[1].all_files[0].get_url_path(''))

    def test_delete_version(self):
        version = self.app.versions.latest()
        version.update(version='<script>alert("xss")</script>')

        res = self.client.get(self.url)
        assert not '<script>alert(' in res.content
        assert '&lt;script&gt;alert(' in res.content
        # Now do the POST to delete.
        res = self.client.post(self.delete_url, dict(version_id=version.pk),
                               follow=True)
        assert not Version.objects.filter(pk=version.pk).exists()
        eq_(ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id)
                               .count(), 1)
        # Since this was the last version, the app status should be incomplete.
        eq_(self.get_app().status, amo.STATUS_NULL)
        # Check xss in success flash message.
        assert not '<script>alert(' in res.content
        assert '&lt;script&gt;alert(' in res.content

        # Test that the soft deletion works pretty well.
        eq_(self.app.versions.count(), 0)
        # We can't use `.reload()` :(
        version = Version.with_deleted.filter(addon=self.app)
        eq_(version.count(), 1)
        # Test that the status of the "deleted" version is STATUS_DELETED.
        eq_(str(version[0].status[0]),
            str(amo.STATUS_CHOICES[amo.STATUS_DELETED]))

    def test_anonymous_delete_redirects(self):
        self.client.logout()
        version = self.app.versions.latest()
        res = self.client.post(self.delete_url, dict(version_id=version.pk))
        self.assertLoginRedirects(res, self.delete_url)

    def test_non_author_no_delete_for_you(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        version = self.app.versions.latest()
        res = self.client.post(self.delete_url, dict(version_id=version.pk))
        eq_(res.status_code, 403)

    @mock.patch.object(Version, 'delete')
    def test_roles_and_delete(self, mock_version):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon_user = AddonUser.objects.create(user=user, addon=self.app)
        allowed = [amo.AUTHOR_ROLE_OWNER, amo.AUTHOR_ROLE_DEV]
        for role in [r[0] for r in amo.AUTHOR_CHOICES]:
            self.client.logout()
            addon_user.role = role
            addon_user.save()
            assert self.client.login(username='regular@mozilla.com',
                                     password='password')
            version = self.app.versions.latest()
            res = self.client.post(self.delete_url,
                                   dict(version_id=version.pk))
            if role in allowed:
                self.assert3xx(res, self.url)
                assert mock_version.called, ('Unexpected: `Version.delete` '
                                             'should have been called.')
                mock_version.reset_mock()
            else:
                eq_(res.status_code, 403)

    def test_cannot_delete_blocked(self):
        v = self.app.versions.latest()
        f = v.all_files[0]
        f.update(status=amo.STATUS_BLOCKED)
        res = self.client.post(self.delete_url, dict(version_id=v.pk))
        eq_(res.status_code, 403)

    def test_dev_cannot_blocklist(self):
        url = self.app.get_dev_url('blocklist')
        res = self.client.post(url)
        eq_(res.status_code, 403)

    @mock.patch('lib.crypto.packaged.os.unlink', new=mock.Mock)
    def test_admin_can_blocklist(self):
        self.grant_permission(UserProfile.objects.get(username='regularuser'),
                              'Apps:Configure')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        v_count = self.app.versions.count()
        url = self.app.get_dev_url('blocklist')
        res = self.client.post(url)
        self.assert3xx(res, self.app.get_dev_url('versions'))
        app = self.app.reload()
        eq_(app.versions.count(), v_count + 1)
        eq_(app.status, amo.STATUS_BLOCKED)
        eq_(app.versions.latest().files.latest().status, amo.STATUS_BLOCKED)


class TestPreloadSubmit(amo.tests.TestCase):
    fixtures = fixture('group_admin', 'user_admin', 'user_admin_group',
                       'webapp_337141')

    def setUp(self):
        self.create_switch('preload-apps')
        self.user = UserProfile.objects.get(username='admin')
        self.login(self.user)

        self.webapp = Addon.objects.get(id=337141)
        self.url = self.webapp.get_dev_url('versions')
        self.home_url = self.webapp.get_dev_url('preload_home')
        self.submit_url = self.webapp.get_dev_url('preload_submit')

        path = os.path.dirname(os.path.abspath(__file__))
        self.test_pdf = path + '/files/test.pdf'
        self.test_xls = path + '/files/test.xls'

    def _submit_pdf(self):
        f = open(self.test_pdf, 'r')
        req = req_factory_factory(self.submit_url, user=self.user, post=True,
                                  data={'agree': True, 'test_plan': f})
        return preload_submit(req, self.webapp.slug)

    def test_get_200(self):
        eq_(self.client.get(self.home_url).status_code, 200)
        eq_(self.client.get(self.submit_url).status_code, 200)

    @mock.patch('mkt.developers.views.save_test_plan')
    @mock.patch('mkt.developers.views.messages')
    def test_preload_on_status_page(self, noop1, noop2):
        req = req_factory_factory(self.url, user=self.user)
        r = status(req, self.webapp.slug)
        doc = pq(r.content)
        eq_(doc('#preload .listing-footer a').attr('href'),
            self.webapp.get_dev_url('preload_home'))
        assert doc('#preload .not-submitted')

        self._submit_pdf()

        req = req_factory_factory(self.url, user=self.user)
        r = status(req, self.webapp.slug)
        doc = pq(r.content)
        eq_(doc('#preload .listing-footer a').attr('href'),
            self.webapp.get_dev_url('preload_submit'))
        assert doc('#preload .submitted')

    def _assert_submit(self, endswith, content_type, save_mock):
        test_plan = PreloadTestPlan.objects.get()
        eq_(test_plan.addon, self.webapp)
        assert test_plan.filename.startswith('test_plan_')
        assert test_plan.filename.endswith(endswith)
        self.assertCloseToNow(test_plan.last_submission)

        eq_(save_mock.call_args[0][0].content_type, content_type)
        assert save_mock.call_args[0][1].startswith('test_plan')
        eq_(save_mock.call_args[0][2], self.webapp)

    @mock.patch('mkt.developers.views.save_test_plan')
    @mock.patch('mkt.developers.views.messages')
    def test_submit_pdf(self, noop, save_mock):
        r = self._submit_pdf()
        self.assert3xx(r, self.url)
        self._assert_submit('pdf', 'application/pdf', save_mock)

    @mock.patch('mkt.developers.views.save_test_plan')
    @mock.patch('mkt.developers.views.messages')
    def test_submit_xls(self, noop, save_mock):
        f = open(self.test_xls, 'r')
        req = req_factory_factory(self.submit_url, user=self.user, post=True,
                                  data={'agree': True, 'test_plan': f})
        r = preload_submit(req, self.webapp.slug)
        self.assert3xx(r, self.url)
        self._assert_submit('xls', 'application/vnd.ms-excel', save_mock)

    @mock.patch('mkt.developers.views.save_test_plan')
    @mock.patch('mkt.developers.views.messages')
    def test_submit_bad_file(self, noop, save_mock):
        f = open(os.path.abspath(__file__), 'r')
        req = req_factory_factory(self.submit_url, user=self.user, post=True,
                                  data={'agree': True, 'test_plan': f})
        r = preload_submit(req, self.webapp.slug)
        eq_(r.status_code, 200)
        eq_(PreloadTestPlan.objects.count(), 0)
        assert not save_mock.called

        assert ('Invalid file type.' in
                pq(r.content)('.test_plan .errorlist').text())

    @mock.patch('mkt.developers.views.save_test_plan')
    @mock.patch('mkt.developers.views.messages')
    def test_submit_no_file(self, noop, save_mock):
        req = req_factory_factory(self.submit_url, user=self.user, post=True,
                                  data={'agree': True})
        r = preload_submit(req, self.webapp.slug)
        eq_(r.status_code, 200)
        eq_(PreloadTestPlan.objects.count(), 0)
        assert not save_mock.called

        assert 'required' in pq(r.content)('.test_plan .errorlist').text()

    @mock.patch('mkt.developers.views.save_test_plan')
    @mock.patch('mkt.developers.views.messages')
    def test_submit_no_agree(self, noop, save_mock):
        f = open(self.test_xls, 'r')
        req = req_factory_factory(self.submit_url, user=self.user, post=True,
                                  data={'test_plan': f})
        r = preload_submit(req, self.webapp.slug)
        eq_(r.status_code, 200)
        eq_(PreloadTestPlan.objects.count(), 0)
        assert not save_mock.called

        assert 'required' in pq(r.content)('.agree .errorlist').text()

    @mock.patch('mkt.developers.views.save_test_plan')
    @mock.patch('mkt.developers.views.messages')
    def test_submit_multiple_status(self, noop, save_mock):
        f = open(self.test_xls, 'r')
        req = req_factory_factory(self.submit_url, user=self.user, post=True,
                                  data={'test_plan': f, 'agree': True})
        preload_submit(req, self.webapp.slug)
        self._submit_pdf()

        eq_(PreloadTestPlan.objects.count(), 2)
        xls = PreloadTestPlan.objects.get(filename__contains='xls')
        pdf = PreloadTestPlan.objects.get(filename__contains='pdf')
        eq_(xls.status, amo.STATUS_DISABLED)
        eq_(pdf.status, amo.STATUS_PUBLIC)

        # Check the link points to most recent one.
        req = req_factory_factory(self.url, user=self.user)
        r = status(req, self.webapp.slug)
        doc = pq(r.content)
        eq_(doc('.test-plan-download').attr('href'),
            pdf.preload_test_plan_url)

    @mock.patch.object(settings, 'PREINSTALL_TEST_PLAN_LATEST',
                       datetime.datetime.now() + datetime.timedelta(days=1))
    @mock.patch('mkt.developers.views.save_test_plan')
    @mock.patch('mkt.developers.views.messages')
    def test_outdated(self, noop, save_mock):
        self._submit_pdf()

        req = req_factory_factory(self.url, user=self.user)
        r = status(req, self.webapp.slug)
        doc = pq(r.content)
        assert doc('.outdated')
