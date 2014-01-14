from django.core.management import call_command

from nose.tools import eq_

import amo
import amo.tests
from devhub.models import ActivityLog, ActivityLogAttachment
from users.models import UserProfile

import mkt.constants.comm as cmb
from mkt.comm.models import CommunicationNote, CommunicationThread
from mkt.site.fixtures import fixture


class TestMigrateActivityLog(amo.tests.TestCase):
    fixtures = fixture('group_editor', 'user_editor', 'user_editor_group')

    def setUp(self):
        self.app = amo.tests.app_factory(status=amo.STATUS_PENDING)
        self.version = self.app.current_version
        self.user = UserProfile.objects.get()

    def _assert(self, cmb_action):
        call_command('migrate_activity_log')
        thread = CommunicationThread.objects.get()
        note = CommunicationNote.objects.get()

        eq_(thread.addon, self.app)
        eq_(thread.version, self.version)

        eq_(note.thread, thread)
        eq_(note.author, self.user)
        eq_(note.body, 'something')
        eq_(note.note_type, cmb_action)

        eq_(note.read_permission_staff, True)
        eq_(note.read_permission_reviewer, True)
        eq_(note.read_permission_senior_reviewer, True)
        eq_(note.read_permission_mozilla_contact, True)

        return thread, note

    def test_migrate(self):
        amo.log(amo.LOG.APPROVE_VERSION, self.app, self.version,
                user=self.user, details={'comments': 'something'})
        self._assert(cmb.APPROVAL)

    def test_migrate_reject(self):
        amo.log(amo.LOG.REJECT_VERSION, self.app, self.version,
                user=self.user, details={'comments': 'something'})
        self._assert(cmb.REJECTION)

    def test_migrate_disable(self):
        amo.log(amo.LOG.APP_DISABLED, self.app, self.version,
                user=self.user, details={'comments': 'something'})
        self._assert(cmb.DISABLED)

    def test_migrate_escalation(self):
        amo.log(amo.LOG.ESCALATE_VERSION, self.app, self.version,
                user=self.user, details={'comments': 'something'})
        thread, note = self._assert(cmb.ESCALATION)
        assert not note.read_permission_developer

    def test_migrate_reviewer_comment(self):
        amo.log(amo.LOG.COMMENT_VERSION, self.app, self.version,
                user=self.user, details={'comments': 'something'})
        thread, note = self._assert(cmb.REVIEWER_COMMENT)
        assert not note.read_permission_developer

    def test_migrate_info(self):
        amo.log(amo.LOG.REQUEST_INFORMATION, self.app, self.version,
                user=self.user, details={'comments': 'something'})
        self._assert(cmb.MORE_INFO_REQUIRED)

    def test_migrate_noaction(self):
        amo.log(amo.LOG.REQUEST_VERSION, self.app, self.version,
                user=self.user, details={'comments': 'something'})
        self._assert(cmb.NO_ACTION)

    def test_get_or_create(self):
        amo.log(amo.LOG.REQUEST_VERSION, self.app, self.version,
                user=self.user, details={'comments': 'something'})
        self._assert(cmb.NO_ACTION)
        call_command('migrate_activity_log')
        call_command('migrate_activity_log')
        eq_(CommunicationNote.objects.count(), 1)

        amo.log(amo.LOG.REQUEST_VERSION, self.app, self.version,
                user=self.user, details={'comments': 'somethingNEW'})
        call_command('migrate_activity_log')
        eq_(CommunicationNote.objects.count(), 2)

        eq_(CommunicationThread.objects.count(), 1)

    def test_none(self):
        call_command('migrate_activity_log')
        assert not CommunicationThread.objects.exists()
        assert not CommunicationNote.objects.exists()

    def test_migrate_attachments(self):
        amo.log(amo.LOG.APPROVE_VERSION, self.app, self.version,
                user=self.user, details={'comments': 'something'})
        ActivityLogAttachment.objects.create(
            activity_log=ActivityLog.objects.get(), filepath='lol',
            description='desc1', mimetype='img')
        ActivityLogAttachment.objects.create(
            activity_log=ActivityLog.objects.get(), filepath='rofl',
            description='desc2', mimetype='txt')
        call_command('migrate_activity_log')

        note = CommunicationNote.objects.get()
        eq_(note.attachments.count(), 2)

        note_attach1 = note.attachments.get(filepath='lol')
        eq_(note_attach1.description, 'desc1')
        eq_(note_attach1.mimetype, 'img')
        note_attach2 = note.attachments.get(filepath='rofl')
        eq_(note_attach2.description, 'desc2')
        eq_(note_attach2.mimetype, 'txt')
