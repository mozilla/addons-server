# -*- coding: utf-8 -*-
import json
import mock
import os

from django.conf import settings
from django.core import mail

import pytest

from olympia import amo
from olympia.amo.helpers import absolutify
from olympia.amo.tests import addon_factory, user_factory, TestCase
from olympia.amo.urlresolvers import reverse
from olympia.activity.models import ActivityLogToken, MAX_TOKEN_USE_COUNT
from olympia.activity.utils import (
    add_email_to_activity_log, log_and_notify, send_activity_mail,
    ActivityEmailParser)
from olympia.devhub.models import ActivityLog


TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sample_message = os.path.join(TESTS_DIR, 'emails', 'message.json')


class TestEmailParser(TestCase):

    def test_basic_email(self):
        message = json.loads(open(sample_message).read())
        email_text = message['Message']
        parser = ActivityEmailParser(email_text)
        assert parser.get_uuid() == '5a0b8a83d501412589cc5d562334b46b'
        assert parser.get_body() == (
            'This is a developer reply to an AMO.  It\'s nice.')


class TestAddEmailToActivityLog(TestCase):
    def setUp(self):
        self.addon = addon_factory(name='Badger', status=amo.STATUS_NOMINATED)
        self.profile = user_factory()
        self.token = ActivityLogToken.objects.create(
            version=self.addon.current_version, user=self.profile)
        self.token.update(uuid='5a0b8a83d501412589cc5d562334b46b')
        message = json.loads(open(sample_message).read())
        self.message = message['Message']

    def test_developer_comment(self):
        self.profile.addonuser_set.create(addon=self.addon)
        note = add_email_to_activity_log(self.message)
        assert note.log == amo.LOG.DEVELOPER_REPLY_VERSION
        self.token.refresh_from_db()
        assert self.token.use_count == 1

    def test_reviewer_comment(self):
        self.grant_permission(self.profile, 'Addons:Review')
        note = add_email_to_activity_log(self.message)
        assert note.log == amo.LOG.REVIEWER_REPLY_VERSION
        self.token.refresh_from_db()
        assert self.token.use_count == 1

    def test_with_max_count_token(self):
        # Test with an invalid token.
        self.token.update(use_count=MAX_TOKEN_USE_COUNT + 1)
        assert not add_email_to_activity_log(self.message)
        self.token.refresh_from_db()
        assert self.token.use_count == MAX_TOKEN_USE_COUNT + 1

    def test_with_unpermitted_token(self):
        """Test when the token user doesn't have a permission to add a note."""
        assert not add_email_to_activity_log(self.message)
        self.token.refresh_from_db()
        assert self.token.use_count == 0

    def test_non_existent_token(self):
        self.token.update(uuid='12345678901234567890123456789012')
        assert not add_email_to_activity_log(self.message)

    def test_with_invalid_msg(self):
        assert not add_email_to_activity_log('youtube?v=dQw4w9WgXcQ')


class TestLogAndNotify(TestCase):

    def setUp(self):
        self.developer = user_factory()
        self.developer2 = user_factory()
        self.reviewer = user_factory()
        self.grant_permission(self.reviewer, 'Addons:Review',
                              'Addon Reviewers')
        self.senior_reviewer = user_factory()
        self.grant_permission(self.senior_reviewer, 'Addons:Edit',
                              'Senior Addon Reviewers')
        self.grant_permission(self.senior_reviewer, 'Addons:Review',
                              'Senior Addon Reviewers')

        self.addon = addon_factory()
        self.addon.addonuser_set.create(user=self.developer)
        self.addon.addonuser_set.create(user=self.developer2)

    def _create(self, action, author=None):
        author = author or self.reviewer
        details = {
            'comments': u'I spy, with my líttle €ye...',
            'version': self.addon.latest_version.version}
        return amo.log(action, self.addon, self.addon.latest_version,
                       user=author, details=details, created=self.days_ago(1))

    def _recipients(self, email_mock):
        recipients = []
        for call in email_mock.call_args_list:
            recipients += call[1]['recipient_list']
            [reply_to] = call[1]['reply_to']
            assert reply_to.startswith('reviewreply+')
            assert reply_to.endswith(settings.INBOUND_EMAIL_DOMAIN)
        return recipients

    def _check_email(self, call, url):
        assert call[0][0] == (
            'Mozilla Add-ons: %s Updated' % self.addon.name)
        assert ('visit %s' % url) in call[0][1]

    @mock.patch('olympia.activity.utils.send_mail')
    def test_developer_reply(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # One from the developer.  So the developer is on the 'thread'
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = u'Thïs is á reply'
        version = self.addon.latest_version
        log_and_notify(action, comments, self.developer, version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 2  # We added one above.
        assert logs[0].details['comments'] == u'Thïs is á reply'

        assert send_mail_mock.call_count == 2  # One author, one reviewer.
        recipients = self._recipients(send_mail_mock)
        assert self.reviewer.email in recipients
        assert self.developer2.email in recipients
        # The developer who sent it doesn't get their email back.
        assert self.developer.email not in recipients

        self._check_email(send_mail_mock.call_args_list[0],
                          self.addon.get_dev_url('versions'))
        review_url = absolutify(
            reverse('editors.review', args=[self.addon.pk], add_prefix=False))
        self._check_email(send_mail_mock.call_args_list[1],
                          review_url)

    @mock.patch('olympia.activity.utils.send_mail')
    def test_reviewer_reply(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # One from the developer.
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.REVIEWER_REPLY_VERSION
        comments = u'Thîs ïs a revïewer replyîng'
        version = self.addon.latest_version
        log_and_notify(action, comments, self.reviewer, version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1
        assert logs[0].details['comments'] == u'Thîs ïs a revïewer replyîng'

        assert send_mail_mock.call_count == 2  # Both authors.
        recipients = self._recipients(send_mail_mock)
        assert self.developer.email in recipients
        assert self.developer2.email in recipients
        # The reviewer who sent it doesn't get their email back.
        assert self.reviewer.email not in recipients

        self._check_email(send_mail_mock.call_args_list[0],
                          self.addon.get_dev_url('versions'))
        self._check_email(send_mail_mock.call_args_list[1],
                          self.addon.get_dev_url('versions'))


@pytest.mark.django_db
def test_send_activity_mail():
    subject = u'This ïs ã subject'
    message = u'And... this ïs a messãge!'
    addon = addon_factory()
    user = user_factory()
    recipients = [user, ]
    from_email = 'bob@bob.bob'
    send_activity_mail(subject, message, addon.latest_version, recipients,
                       from_email)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].body == message
    assert mail.outbox[0].subject == subject

    uuid = addon.latest_version.token.get(user=user).uuid.hex
    reply_email = 'reviewreply+%s@%s' % (uuid, settings.INBOUND_EMAIL_DOMAIN)
    assert mail.outbox[0].reply_to == [reply_email]
