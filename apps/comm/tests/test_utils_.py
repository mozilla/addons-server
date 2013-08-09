import os.path

from django.conf import settings

from nose.tools import eq_

import amo
from amo.tests import app_factory, TestCase
from comm.utils import CommEmailParser, save_from_email_reply
from comm.models import CommunicationThread, CommunicationThreadToken
from mkt.constants import comm
from mkt.site.fixtures import fixture
from users.models import UserProfile


sample_email = os.path.join(settings.ROOT, 'apps', 'comm', 'tests',
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
