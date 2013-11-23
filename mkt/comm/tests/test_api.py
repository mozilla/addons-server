import json

from django.conf import settings
from django.core import mail
from django.core.urlresolvers import reverse

import mock
from nose.tools import eq_
from test_utils import RequestFactory

from amo.tests import addon_factory, req_factory_factory, version_factory
from comm.models import (CommunicationNote, CommunicationNoteRead,
                         CommunicationThread, CommunicationThreadCC)
from users.models import UserProfile

from mkt.api.tests.test_oauth import RestOAuth
from mkt.comm.api import EmailCreationPermission, post_email, ThreadPermission
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestThreadDetail(RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519', 'user_support_staff')

    def setUp(self):
        super(TestThreadDetail, self).setUp()
        self.addon = Webapp.objects.get(pk=337141)

    def check_permissions(self):
        req = RequestFactory().get(reverse('comm-thread-detail',
                                           kwargs={'pk': self.thread.pk}))
        req.user = self.user
        req.amo_user = self.profile
        req.groups = req.amo_user.groups.all()

        return ThreadPermission().has_object_permission(
            req, 'comm-thread-detail', self.thread)

    def test_response(self):
        thread = CommunicationThread.objects.create(addon=self.addon)
        CommunicationNote.objects.create(thread=thread,
            author=self.profile, note_type=0, body='something')
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        eq_(res.status_code, 200)
        assert 'recent_notes' in res.json
        eq_(len(res.json['recent_notes']), 1)
        eq_(res.json['addon'], self.addon.id)

    def test_recent_notes_perm(self):
        staff = UserProfile.objects.get(username='support_staff')
        self.addon.addonuser_set.create(user=self.profile)

        thread = CommunicationThread.objects.create(
            addon=self.addon, read_permission_developer=True)
        CommunicationNote.objects.create(
            thread=thread, author=staff, note_type=0, body='allowed',
            read_permission_developer=True)
        no_dev_note = CommunicationNote.objects.create(
            thread=thread, author=staff, note_type=6, body='denied',
            read_permission_developer=False)

        # Test that the developer can't access no-developer note.
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        eq_(res.status_code, 200)
        eq_(len(res.json['recent_notes']), 1)
        eq_(res.json['recent_notes'][0]['body'], 'allowed')
        eq_(res.json['addon'], self.addon.id)

        # Test that the author always has permissions.
        no_dev_note.update(author=self.profile)
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        eq_(len(res.json['recent_notes']), 2)

    def test_cc(self):
        self.thread = CommunicationThread.objects.create(addon=self.addon)
        # Test with no CC.
        assert not self.check_permissions()

        # Test with CC created.
        CommunicationThreadCC.objects.create(thread=self.thread,
            user=self.profile)
        assert self.check_permissions()

    def test_addon_dev_allowed(self):
        self.thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_developer=True)
        self.addon.addonuser_set.create(user=self.profile)
        assert self.check_permissions()

    def test_addon_dev_denied(self):
        # Test when the user is a developer of a different add-on.
        self.thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_developer=True)
        addon = addon_factory()
        self.profile.addonuser_set.create(addon=addon)
        assert not self.check_permissions()

    def test_read_public(self):
        self.thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_public=True)
        assert self.check_permissions()

    def test_read_moz_contact(self):
        thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_mozilla_contact=True)
        thread.addon.mozilla_contact = self.profile.email
        thread.addon.save()
        self.thread = thread
        assert self.check_permissions()

    def test_read_reviewer(self):
        self.grant_permission(self.profile, 'Apps:Review')
        self.thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_reviewer=True)
        assert self.check_permissions()

    def test_read_senior_reviewer(self):
        self.grant_permission(self.profile, 'Apps:ReviewEscalated')
        self.thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_senior_reviewer=True)
        assert self.check_permissions()

    def test_read_staff(self):
        self.grant_permission(self.profile, 'Admin:%')
        self.thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_staff=True)
        assert self.check_permissions()

    def test_cors_allowed(self):
        thread = CommunicationThread.objects.create(addon=self.addon)
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        self.assertCORS(res, 'get', 'post', 'patch')

    def test_mark_read(self):
        thread = CommunicationThread.objects.create(addon=self.addon)
        n1 = CommunicationNote.objects.create(author=self.profile,
            thread=thread, note_type=0, body='something')
        n2 = CommunicationNote.objects.create(author=self.profile,
            thread=thread, note_type=0, body='something2')

        res = self.client.patch(reverse('comm-thread-detail',
                                        kwargs={'pk': thread.pk}),
                                data=json.dumps({'is_read': True}))
        eq_(res.status_code, 204)
        assert n1.read_by_users.filter(user=self.profile).exists()
        assert n2.read_by_users.filter(user=self.profile).exists()

    def test_review_url(self):
        thread = CommunicationThread.objects.create(addon=self.addon)
        CommunicationNote.objects.create(
            thread=thread, author=self.profile, note_type=0, body='something')
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        eq_(res.status_code, 200)
        eq_(res.json['addon_meta']['review_url'],
            reverse('reviewers.apps.review', args=[self.addon.app_slug]))

    def test_version_number(self):
        version = version_factory(addon=self.addon, version='7.12')
        thread = CommunicationThread.objects.create(
            addon=self.addon, version=version, read_permission_public=True)

        res = self.client.get(reverse('comm-thread-detail', args=[thread.pk]))
        eq_(json.loads(res.content)['version_number'], '7.12')
        eq_(json.loads(res.content)['version_is_obsolete'], False)

        version.delete()
        res = self.client.get(reverse('comm-thread-detail', args=[thread.pk]))
        eq_(json.loads(res.content)['version_number'], '7.12')
        eq_(json.loads(res.content)['version_is_obsolete'], True)

    def test_app_threads(self):
        version1 = version_factory(addon=self.addon, version='7.12')
        thread1 = CommunicationThread.objects.create(
            addon=self.addon, version=version1, read_permission_public=True)

        version2 = version_factory(addon=self.addon, version='1.16')
        thread2 = CommunicationThread.objects.create(
            addon=self.addon, version=version2, read_permission_public=True)

        for thread in (thread1, thread2):
            res = self.client.get(reverse('comm-thread-detail',
                                  args=[thread.pk]))
            eq_(res.status_code, 200)
            eq_(json.loads(res.content)['app_threads'],
                [{"id": thread2.id, "version__version": version2.version},
                 {"id": thread1.id, "version__version": version1.version}])

class TestThreadList(RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestThreadList, self).setUp()
        self.addon = Webapp.objects.get(pk=337141)
        self.list_url = reverse('comm-thread-list')

    def test_response(self):
        """Test the list response, we don't want public threads in
        the list."""
        CommunicationThread.objects.create(addon=self.addon,
            read_permission_public=True)
        thread = CommunicationThread.objects.create(addon=self.addon)
        CommunicationNote.objects.create(author=self.profile, thread=thread,
            note_type=0)
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)

    def test_addon_filter(self):
        thread = CommunicationThread.objects.create(addon=self.addon)
        CommunicationNote.objects.create(author=self.profile, thread=thread,
            note_type=0, body='something')

        res = self.client.get(self.list_url, {'app': '337141'})
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)

        # This add-on doesn't exist.
        res = self.client.get(self.list_url, {'app': '1000'})
        eq_(res.status_code, 404)

    def test_app_slug(self):
        thread = CommunicationThread.objects.create(addon=self.addon)
        CommunicationNote.objects.create(author=self.profile, thread=thread,
            note_type=0, body='something')

        res = self.client.get(self.list_url, {'app': self.addon.app_slug})
        eq_(res.status_code, 200)
        eq_(res.json['objects'][0]['addon_meta']['app_slug'],
            self.addon.app_slug)

    def test_creation(self):
        version = self.addon.current_version
        res = self.client.post(self.list_url, data=json.dumps(
            {'addon': self.addon.id, 'version': version.id}))

        eq_(res.status_code, 201)

    def test_app_threads(self):
        version1 = version_factory(addon=self.addon, version='7.12')
        thread1 = CommunicationThread.objects.create(
            addon=self.addon, version=version1, read_permission_public=True)
        CommunicationThreadCC.objects.create(user=self.profile, thread=thread1)

        version2 = version_factory(addon=self.addon, version='1.16')
        thread2 = CommunicationThread.objects.create(
            addon=self.addon, version=version2, read_permission_public=True)
        CommunicationThreadCC.objects.create(user=self.profile, thread=thread2)

        res = self.client.get(self.list_url, {'app': self.addon.app_slug})
        eq_(res.json['app_threads'],
            [{"id": thread2.id, "version__version": version2.version},
             {"id": thread1.id, "version__version": version1.version}])


class TestNote(RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519', 'user_999',
                       'user_support_staff')

    def setUp(self):
        super(TestNote, self).setUp()
        self.addon = Webapp.objects.get(pk=337141)
        self.thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_developer=True, version=self.addon.current_version)
        self.thread_url = reverse('comm-thread-detail',
                                  kwargs={'pk': self.thread.id})
        self.list_url = reverse('comm-note-list',
                                kwargs={'thread_id': self.thread.id})

        self.profile.addonuser_set.create(addon=self.addon)

    def test_response(self):
        note = CommunicationNote.objects.create(author=self.profile,
            thread=self.thread, note_type=0, body='something')
        res = self.client.get(reverse('comm-note-detail',
                                      kwargs={'thread_id': self.thread.id,
                                              'pk': note.id}))
        eq_(res.status_code, 200)
        eq_(res.json['body'], 'something')
        eq_(res.json['reply_to'], None)
        eq_(res.json['is_read'], False)

        CommunicationNoteRead.objects.create(user=self.profile, note=note)
        res = self.client.get(reverse('comm-note-detail',
                                      kwargs={'thread_id': self.thread.id,
                                              'pk': note.id}))
        eq_(res.json['is_read'], True)

    def test_show_read_filter(self):
        """Test `is_read` filter."""
        note = CommunicationNote.objects.create(
            author=self.profile, thread=self.thread, note_type=0,
            body='something')
        CommunicationNoteRead.objects.create(user=self.profile, note=note)

        # Test with `show_read=true`.
        res = self.client.get(self.list_url, {'show_read': 'truey'})
        eq_(res.json['objects'][0]['is_read'], True)

        # Test with `show_read=false`.
        CommunicationNoteRead.objects.all().delete()
        res = self.client.get(self.list_url, {'show_read': '0'})
        eq_(res.json['objects'][0]['is_read'], False)

    def test_read_perms(self):
        staff = UserProfile.objects.get(username='support_staff')
        CommunicationNote.objects.create(
            author=staff, thread=self.thread, note_type=0, body='oncetoldme',
            read_permission_developer=True)
        no_dev_note = CommunicationNote.objects.create(
            author=staff, thread=self.thread, note_type=6, body='denied',
            read_permission_developer=False)

        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)
        eq_(res.json['objects'][0]['body'], 'oncetoldme')

        # Test that the author always has permissions.
        no_dev_note.update(author=self.profile)
        res = self.client.get(self.list_url)
        eq_(len(res.json['objects']), 2)

    def test_creation(self):
        res = self.client.post(self.list_url, data=json.dumps(
            {'note_type': '0', 'body': 'something'}))
        eq_(res.status_code, 201)
        eq_(res.json['body'], 'something')

    def test_creation_denied(self):
        self.thread.read_permission_developer = False
        self.thread.save()
        res = self.client.post(self.list_url, data=json.dumps(
            {'note_type': '0', 'body': 'something'}))
        eq_(res.status_code, 403)

    def test_cors_allowed(self):
        res = self.client.get(self.list_url)
        self.assertCORS(res, 'get', 'post', 'delete', 'patch')

    def test_reply_list(self):
        note = CommunicationNote.objects.create(author=self.profile,
            thread=self.thread, note_type=0, body='something')
        note.replies.create(body='somethingelse', note_type=0,
            thread=self.thread, author=self.profile)
        res = self.client.get(reverse('comm-note-replies-list',
                                      kwargs={'thread_id': self.thread.id,
                                              'note_id': note.id}))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)
        eq_(res.json['objects'][0]['reply_to'], note.id)

    def test_reply_create(self):
        note = CommunicationNote.objects.create(author=self.profile,
            thread=self.thread, note_type=0, body='something')
        res = self.client.post(reverse('comm-note-replies-list',
                                       kwargs={'thread_id': self.thread.id,
                                               'note_id': note.id}),
                               data=json.dumps({'note_type': '0',
                                                'body': 'something'}))
        eq_(res.status_code, 201)
        eq_(note.replies.count(), 1)

    def test_note_emails(self):
        self.create_switch(name='comm-dashboard')
        note = CommunicationNote.objects.create(author=self.profile,
            thread=self.thread, note_type=0, body='something',
            read_permission_developer=True)
        res = self.client.post(reverse('comm-note-replies-list',
                                       kwargs={'thread_id': self.thread.id,
                                               'note_id': note.id}),
                               data=json.dumps({'note_type': '0',
                                                'body': 'something'}))
        eq_(res.status_code, 201)

        # Decrement authors.count() by 1 because the author of the note is
        # one of the authors of the addon.
        eq_(len(mail.outbox), self.thread.addon.authors.count() - 1)

    def test_mark_read(self):
        note = CommunicationNote.objects.create(author=self.profile,
            thread=self.thread, note_type=0, body='something')
        CommunicationNoteRead.objects.create(user=self.profile, note=note)
        res = self.client.patch(reverse('comm-note-detail',
                                        kwargs={'thread_id': self.thread.id,
                                                'pk': note.id}),
                                data=json.dumps({'is_read': True}))
        eq_(res.status_code, 204)
        assert note.read_by_users.filter(user=self.profile).exists()


@mock.patch.object(settings, 'WHITELISTED_CLIENTS_EMAIL_API',
                   ['10.10.10.10'])
@mock.patch.object(settings, 'POSTFIX_AUTH_TOKEN', 'something')
class TestEmailApi(RestOAuth):

    def get_request(self, data=None):
        req = req_factory_factory(reverse('post-email-api'), self.profile)
        req.META['REMOTE_ADDR'] = '10.10.10.10'
        req.META['HTTP_POSTFIX_AUTH_TOKEN'] = 'something'
        req.POST = dict(data) if data else dict({})
        req.method = 'POST'
        return req

    def test_allowed(self):
        assert EmailCreationPermission().has_permission(self.get_request(),
                                                        None)

    def test_ip_denied(self):
        req = self.get_request()
        req.META['REMOTE_ADDR'] = '10.10.10.1'
        assert not EmailCreationPermission().has_permission(req, None)

    def test_token_denied(self):
        req = self.get_request()
        req.META['HTTP_POSTFIX_AUTH_TOKEN'] = 'somethingwrong'
        assert not EmailCreationPermission().has_permission(req, None)

    @mock.patch('comm.tasks.consume_email.apply_async')
    def test_successful(self, _mock):
        req = self.get_request({'body': 'something'})
        res = post_email(req)
        _mock.assert_called_with(('something',))
        eq_(res.status_code, 201)

    def test_bad_request(self):
        """Test with no email body."""
        res = post_email(self.get_request())
        eq_(res.status_code, 400)
