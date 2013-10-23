from datetime import datetime

from nose.tools import eq_

from addons.models import Addon
import amo.tests
from comm.models import (CommunicationNote, CommunicationThread,
                         CommunicationThreadCC, CommunicationThreadToken,
                         user_has_perm_note, user_has_perm_thread)
from users.models import UserProfile

from mkt.constants import comm as const


class PermissionTestMixin(object):
    fixtures = ['base/addon_3615', 'base/user_999']

    def setUp(self):
        self.addon = Addon.objects.get()
        self.user = UserProfile.objects.get(username='regularuser')

        self.thread = CommunicationThread.objects.create(addon=self.addon)
        self.author = UserProfile.objects.create(email='lol', username='lol')
        self.note = CommunicationNote.objects.create(
            thread=self.thread, author=self.author, note_type=0, body='xyz')
        self.obj = None


    def _eq_obj_perm(self, val):
        if self.type == 'note':
            eq_(user_has_perm_note(self.obj, self.user), val)
        else:
            eq_(user_has_perm_thread(self.obj, self.user), val)

    def test_no_perm(self):
        self._eq_obj_perm(False)

    def test_has_perm_public(self):
        self.obj.update(read_permission_public=True)
        self._eq_obj_perm(True)

    def test_has_perm_dev(self):
        self.obj.update(read_permission_developer=True)
        self.addon.addonuser_set.create(user=self.user)
        self._eq_obj_perm(True)

    def test_has_perm_rev(self):
        self.obj.update(read_permission_reviewer=True)
        self.grant_permission(self.user, 'Apps:Review')
        self._eq_obj_perm(True)

    def test_has_perm_senior_rev(self):
        self.obj.update(read_permission_senior_reviewer=True)
        self.grant_permission(self.user, 'Apps:ReviewEscalated')
        self._eq_obj_perm(True)

    def test_has_perm_moz_contact(self):
        self.obj.update(read_permission_mozilla_contact=True)
        self.addon.update(
            mozilla_contact=','.join([self.user.email, 'lol@lol.com']))
        self._eq_obj_perm(True)

    def test_has_perm_staff(self):
        self.obj.update(read_permission_staff=True)
        self.grant_permission(self.user, 'Admin:*')
        self._eq_obj_perm(True)


class TestCommunicationNote(PermissionTestMixin, amo.tests.TestCase):

    def setUp(self):
        super(TestCommunicationNote, self).setUp()
        self.type = 'note'
        self.obj = self.note

    def test_has_perm_author(self):
        self.obj.update(author=self.user)
        self._eq_obj_perm(True)

    def test_manager(self):
        eq_(CommunicationNote.objects.count(), 1)
        eq_(CommunicationNote.objects.with_perms(self.user,
                                                 self.thread).count(), 0)

        self.note.update(author=self.user)
        eq_(CommunicationNote.objects.count(), 1)
        eq_(CommunicationNote.objects.with_perms(self.user,
                                                 self.thread).count(), 1)


class TestCommunicationThread(PermissionTestMixin, amo.tests.TestCase):

    def setUp(self):
        super(TestCommunicationThread, self).setUp()
        self.type = 'thread'
        self.obj = self.thread

    def test_has_perm_posted(self):
        self.note.update(author=self.user)
        self._eq_obj_perm(True)

    def test_has_perm_cc(self):
        CommunicationThreadCC.objects.create(user=self.user, thread=self.obj)
        self._eq_obj_perm(True)


class TestThreadTokenModel(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def setUp(self):
        addon = Addon.objects.get(pk=3615)
        self.thread = CommunicationThread(addon=addon)
        user = UserProfile.objects.all()[0]
        self.token = CommunicationThreadToken(thread=self.thread, user=user)
        self.token.modified = datetime.now()
        self.token.use_count = 0

    def test_live_thread_token_is_valid(self):
        """
        Test `is_valid()` when the token is fresh (not expired).
        """
        assert self.token.is_valid()

    def test_expired_thread_token_is_valid(self):
        """
        Test `is_valid()` when the token has expired.
        """
        self.token.modified = self.days_ago(const.THREAD_TOKEN_EXPIRY + 1)
        assert not self.token.is_valid()

    def test_unused_token_is_valid(self):
        """
        Test `is_valid()` when the token is unused.
        """
        assert self.token.is_valid()

    def test_max_used_thread_token_is_valid(self):
        """
        Test `is_valid()` when the token has been fully used.
        """
        self.token.use_count = const.MAX_TOKEN_USE_COUNT
        assert not self.token.is_valid()

    def test_reset_uuid(self):
        """
        Test `reset_uuid()` generates a differ uuid.
        """
        self.thread.save()
        self.token.thread = self.thread
        self.token.save()
        uuid = self.token.uuid
        assert uuid

        self.token.reset_uuid()
        assert self.token.uuid
        assert uuid != self.token.uuid
