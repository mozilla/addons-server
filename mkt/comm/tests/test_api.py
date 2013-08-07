import json

from django.conf import settings
from django.core.urlresolvers import reverse

import mock
from nose.tools import eq_
from test_utils import RequestFactory

from amo.tests import addon_factory
from comm.models import (CommunicationNote, CommunicationThread,
                         CommunicationThreadCC, CommunicationNoteRead)
from mkt.api.tests.test_oauth import RestOAuth
from mkt.comm.api import ThreadPermission, EmailCreationPermission, post_email
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestThreadDetail(RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

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

    def test_creation(self):
        version = self.addon.current_version
        res = self.client.post(self.list_url, data=json.dumps(
            {'addon': self.addon.id, 'version': version.id}))

        eq_(res.status_code, 201)


class TestNote(RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519', 'user_999')

    def setUp(self):
        super(TestNote, self).setUp()
        addon = Webapp.objects.get(pk=337141)
        self.thread = CommunicationThread.objects.create(addon=addon,
            read_permission_developer=True, version=addon.current_version)
        self.thread_url = reverse('comm-thread-detail',
                                  kwargs={'pk': self.thread.id})
        self.list_url = reverse('comm-note-list',
                                kwargs={'thread_id': self.thread.id})

        self.profile.addonuser_set.create(addon=addon)

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
        note = CommunicationNote.objects.create(author=self.profile,
            thread=self.thread, note_type=0, body='something')
        CommunicationNoteRead.objects.create(user=self.profile, note=note)

        # Test with `show_read=true`.
        res = self.client.get(self.list_url, {'show_read': 'truey'})
        eq_(res.json['objects'][0]['is_read'], True)

        # Test with `show_read=false`.
        CommunicationNoteRead.objects.all().delete()
        res = self.client.get(self.list_url, {'show_read': '0'})
        eq_(res.json['objects'][0]['is_read'], False)

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


class TestEmailApi(RestOAuth):

    def setUp(self):
        super(TestEmailApi, self).setUp()
        self.mock_request = RequestFactory().get(reverse('post-email-api'))
        patcher = mock.patch.object(settings, 'WHITELISTED_CLIENTS_EMAIL_API',
                                    ['10.10.10.10'])
        patcher.start()

    def get_request(self, data):
        req = self.mock_request
        req.META['REMOTE_ADDR'] = '10.10.10.10'
        req.POST = dict(data)
        req.method = 'POST'
        req.user = self.user
        req.amo_user = self.profile
        req.groups = req.amo_user.groups.all()
        return req

    def test_allowed(self):
        self.mock_request.META['REMOTE_ADDR'] = '10.10.10.10'
        assert EmailCreationPermission().has_permission(self.mock_request,
                                                        None)

    def test_denied(self):
        self.mock_request.META['REMOTE_ADDR'] = '10.10.10.1'
        assert not EmailCreationPermission().has_permission(self.mock_request,
                                                            None)

    @mock.patch('comm.tasks.consume_email.apply_async')
    def test_response(self, _mock):
        res = post_email(self.get_request({'body': 'something'}))
        _mock.assert_called_with(('something',))
        eq_(res.status_code, 201)

    def test_bad_request(self):
        """Test with no email body."""
        res = post_email(self.get_request({}))
        eq_(res.status_code, 400)
