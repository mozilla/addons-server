import os.path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

import mock
from nose.tools import eq_

import amo
from amo.tests import app_factory, TestCase, user_factory
from users.models import UserProfile

from mkt.comm.forms import CommAttachmentFormSet
from mkt.comm.models import CommunicationThread, CommunicationThreadToken
from mkt.comm.tests.test_api import AttachmentManagementMixin
from mkt.comm.utils import (CommEmailParser, create_comm_note,
                            save_from_email_reply)
from mkt.constants import comm
from mkt.site.fixtures import fixture


sample_email = os.path.join(settings.ROOT, 'mkt', 'comm', 'tests',
                            'email.txt')


class TestEmailReplySaving(TestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        app = app_factory(name='Antelope', status=amo.STATUS_PENDING)
        self.profile = UserProfile.objects.get(pk=999)
        t = CommunicationThread.objects.create(addon=app,
            version=app.current_version, read_permission_reviewer=True)

        self.create_switch('comm-dashboard')
        self.token = CommunicationThreadToken.objects.create(thread=t,
            user=self.profile)
        self.token.update(uuid='5a0b8a83d501412589cc5d562334b46b')
        self.email_base64 = open(sample_email).read()
        self.grant_permission(self.profile, 'Apps:Review')

    def test_successful_save(self):
        note = save_from_email_reply(self.email_base64)
        assert note
        eq_(note.body, 'test note 5\n')

    def test_with_max_count_token(self):
        # Test with an invalid token.
        self.token.update(use_count=comm.MAX_TOKEN_USE_COUNT + 1)
        assert not save_from_email_reply(self.email_base64)

    def test_with_unpermitted_token(self):
        """Test when the token's user does not have a permission on thread."""
        self.profile.groupuser_set.filter(
            group__rules__contains='Apps:Review').delete()
        assert not save_from_email_reply(self.email_base64)

    def test_non_existent_token(self):
        self.token.update(uuid='youtube?v=wn4RP57Y7bw')
        assert not save_from_email_reply(self.email_base64)

    def test_with_invalid_msg(self):
        assert not save_from_email_reply('youtube?v=WwJjts9FzxE')


class TestEmailParser(TestCase):

    def setUp(self):
        email_text = open(sample_email).read()
        self.parser = CommEmailParser(email_text)

    def test_uuid(self):
        eq_(self.parser.get_uuid(), '5a0b8a83d501412589cc5d562334b46b')

    def test_body(self):
        eq_(self.parser.get_body(), 'test note 5\n')


class TestCreateCommNote(TestCase, AttachmentManagementMixin):

    def setUp(self):
        self.create_switch('comm-dashboard')
        self.contact = user_factory(username='contact')
        self.user = user_factory()
        self.grant_permission(self.user, '*:*')
        self.app = app_factory(mozilla_contact=self.contact.email)

    def test_create_thread(self):
        # Default permissions.
        thread, note = create_comm_note(
            self.app, self.app.current_version, self.user, 'huehue',
            note_type=comm.APPROVAL)

        # Check Thread.
        eq_(thread.addon, self.app)
        eq_(thread.version, self.app.current_version)
        expected = {
            'public': False, 'developer': True, 'reviewer': True,
            'senior_reviewer': True, 'mozilla_contact': True, 'staff': True}
        for perm, has_perm in expected.items():
            eq_(getattr(thread, 'read_permission_%s' % perm), has_perm, perm)

        # Check Note.
        eq_(note.thread, thread)
        eq_(note.author, self.user)
        eq_(note.body, 'huehue')
        eq_(note.note_type, comm.APPROVAL)

        # Check CC.
        eq_(thread.thread_cc.count(), 2)
        assert thread.thread_cc.filter(user=self.contact).exists()
        assert thread.thread_cc.filter(user=self.user).exists()

        # Check Reads.
        eq_(note.read_by_users.count(), 2)

    def test_create_note_existing_thread(self):
        # Initial note.
        thread, note = create_comm_note(
            self.app, self.app.current_version, self.user, 'huehue')

        # Second note from contact.
        thread, reply = create_comm_note(
            self.app, self.app.current_version, self.contact, 'euheuh!',
            note_type=comm.REJECTION)

        # Mark read by author.
        eq_(reply.read_by_users.count(), 1)

        # Third person joins thread.
        thread, last_word = create_comm_note(
            self.app, self.app.current_version, user_factory(), 'euheuh!',
            note_type=comm.MORE_INFO_REQUIRED)

        # More checking that joining a thread marks all old notes as read.
        eq_(thread.thread_cc.count(), 3)
        eq_(note.read_by_users.count(), 3)
        eq_(reply.read_by_users.count(), 2)
        eq_(last_word.read_by_users.count(), 1)

    @mock.patch('mkt.comm.utils.post_create_comm_note', new=mock.Mock)
    def test_custom_perms(self):
        thread, note = create_comm_note(
            self.app, self.app.current_version, self.user, 'escalatedquickly',
            note_type=comm.ESCALATION, perms={'developer': False,
                                              'staff': True})

        expected = {
            'public': False, 'developer': False, 'reviewer': True,
            'senior_reviewer': True, 'mozilla_contact': True, 'staff': True}
        for perm, has_perm in expected.items():
            eq_(getattr(thread, 'read_permission_%s' % perm), has_perm, perm)

    @mock.patch('mkt.comm.utils.post_create_comm_note', new=mock.Mock)
    def test_attachments(self):
        attach_formdata = self._attachment_management_form(num=2)
        attach_formdata.update(self._attachments(num=2))
        attach_formset = CommAttachmentFormSet(
            attach_formdata,
            {'form-0-attachment':
                SimpleUploadedFile(
                    'lol', attach_formdata['form-0-attachment'].read()),
             'form-1-attachment':
                SimpleUploadedFile(
                    'lol2', attach_formdata['form-1-attachment'].read())})

        thread, note = create_comm_note(
            self.app, self.app.current_version, self.user, 'lol',
            note_type=comm.APPROVAL, attachments=attach_formset)

        eq_(note.attachments.count(), 2)
