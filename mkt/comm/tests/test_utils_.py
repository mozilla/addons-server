import os.path

from django.conf import settings

from nose.tools import eq_

import amo
from amo.tests import app_factory, TestCase, user_factory
from users.models import UserProfile

from mkt.comm.models import CommunicationThread, CommunicationThreadToken
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

        self.token = CommunicationThreadToken.objects.create(thread=t,
            user=self.profile)
        self.email_template = open(sample_email).read()

    def test_successful_save(self):
        self.grant_permission(self.profile, 'Apps:Review')
        email_text = self.email_template % self.token.uuid
        note = save_from_email_reply(email_text)
        assert note
        eq_(note.body, 'This is the body')

        # Test with an invalid token.
        self.token.update(use_count=comm.MAX_TOKEN_USE_COUNT + 1)
        email_text = self.email_template % self.token.uuid
        assert not save_from_email_reply(email_text)

    def test_with_unpermitted_token(self):
        """Test when the token's user does not have a permission on thread."""
        email_text = self.email_template % self.token.uuid
        assert not save_from_email_reply(email_text)

    def test_non_existent_token(self):
        email_text = self.email_template % (self.token.uuid + 'junk')
        assert not save_from_email_reply(email_text)

    def test_with_junk_body(self):
        email_text = 'this is junk'
        assert not save_from_email_reply(email_text)


class TestEmailParser(TestCase):

    def setUp(self):
        email_text = open(sample_email).read() % 'someuuid'
        self.parser = CommEmailParser(email_text)

    def test_uuid(self):
        eq_(self.parser.get_uuid(), 'someuuid')

    def test_body(self):
        eq_(self.parser.get_body(), 'This is the body')


class TestCreateCommNote(TestCase):

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
