# -*- coding: utf-8 -*-
import copy
import json
import os

from datetime import datetime, timedelta

from django.conf import settings
from django.core import mail

import mock
import pytest

from waffle.testutils import override_switch

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.activity.models import (
    MAX_TOKEN_USE_COUNT, ActivityLog, ActivityLogToken)
from olympia.activity.utils import (
    ACTIVITY_MAIL_GROUP, ActivityEmailEncodingError, ActivityEmailParser,
    ActivityEmailTokenError, ActivityEmailUUIDError, add_email_to_activity_log,
    add_email_to_activity_log_wrapper, log_and_notify,
    notify_about_activity_log, send_activity_mail)
from olympia.addons.models import Addon, AddonReviewerFlags
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import reverse


TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sample_message_file = os.path.join(TESTS_DIR, 'emails', 'message.json')
with open(sample_message_file) as file_object:
    sample_message_content = json.loads(file_object.read())


class TestEmailParser(TestCase):
    def test_basic_email(self):
        parser = ActivityEmailParser(sample_message_content['Message'])
        assert parser.get_uuid() == '5a0b8a83d501412589cc5d562334b46b'
        assert parser.reply == (
            'This is a developer reply to an AMO.  It\'s nice.')

    def test_with_invalid_msg(self):
        with self.assertRaises(ActivityEmailEncodingError):
            ActivityEmailParser('youtube?v=dQw4w9WgXcQ')

    def test_with_empty_to(self):
        message = copy.deepcopy(sample_message_content['Message'])
        message['To'] = None
        parser = ActivityEmailParser(message)
        with self.assertRaises(ActivityEmailUUIDError):
            # It should fail, but not because of a Not Iterable TypeError,
            # instead we handle that gracefully and raise an exception that
            # we control and catch later.
            parser.get_uuid()


@override_switch('activity-email-bouncing', active=True)
class TestEmailBouncing(TestCase):
    BOUNCE_REPLY = (
        'Hello,\n\nAn email was received, apparently from you. Unfortunately '
        'we couldn\'t process it because of:\n%s\n\nPlease visit %s to leave '
        'a reply instead.\n--\nMozilla Add-ons\n%s')

    def setUp(self):
        self.bounce_reply = (
            self.BOUNCE_REPLY % ('%s', settings.SITE_URL, settings.SITE_URL))
        self.email_text = sample_message_content['Message']

    @mock.patch('olympia.activity.utils.ActivityLog.create')
    def test_no_note_logged(self, log_mock):
        # First set everything up so it's working
        addon = addon_factory()
        version = addon.find_latest_version(channel=amo.RELEASE_CHANNEL_LISTED)
        user = user_factory()
        self.grant_permission(user, '*:*')
        ActivityLogToken.objects.create(
            user=user, version=version,
            uuid='5a0b8a83d501412589cc5d562334b46b')
        # Make log_mock return false for some reason.
        log_mock.return_value = False

        # No exceptions thrown, but no log means something went wrong.
        assert not add_email_to_activity_log_wrapper(self.email_text)
        assert len(mail.outbox) == 1
        out = mail.outbox[0]
        assert out.body == (
            self.bounce_reply % 'Undefined Error.')
        assert out.subject == 'Re: This is the subject of a test message.'
        assert out.to == ['sender@example.com']

    def test_exception_because_invalid_token(self):
        # Fails because the token doesn't exist in ActivityToken.objects
        assert not add_email_to_activity_log_wrapper(self.email_text)
        assert len(mail.outbox) == 1
        out = mail.outbox[0]
        assert out.body == (
            self.bounce_reply %
            'UUID found in email address TO: header but is not a valid token '
            '(5a0b8a83d501412589cc5d562334b46b).')
        assert out.subject == 'Re: This is the subject of a test message.'
        assert out.to == ['sender@example.com']

    def test_exception_because_invalid_email(self):
        # Fails because the token doesn't exist in ActivityToken.objects
        email_text = copy.deepcopy(self.email_text)
        email_text['To'] = [{
            'EmailAddress': 'foobar@addons.mozilla.org',
            'FriendlyName': 'not a valid activity mail reply'}]
        assert not add_email_to_activity_log_wrapper(email_text)
        assert len(mail.outbox) == 1
        out = mail.outbox[0]
        assert out.body == (
            self.bounce_reply %
            'TO: address does not contain activity email uuid ('
            'foobar@addons.mozilla.org).')
        assert out.subject == 'Re: This is the subject of a test message.'
        assert out.to == ['sender@example.com']

    def test_exception_parser_because_malformed_message(self):
        assert not add_email_to_activity_log_wrapper("blah de blah")
        # No From or Reply means no bounce, alas.
        assert len(mail.outbox) == 0

    def _test_exception_in_parser_but_can_send_email(self, message):
        assert not add_email_to_activity_log_wrapper(message)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].body == (
            self.bounce_reply % 'Invalid or malformed json message object.')
        assert mail.outbox[0].subject == 'Re: your email to us'
        assert mail.outbox[0].to == ['bob@dole.org']

    def test_exception_in_parser_but_from_defined(self):
        """Unlikely scenario of an email missing a body but having a From."""
        self._test_exception_in_parser_but_can_send_email(
            {'From': {'EmailAddress': 'bob@dole.org'}})

    def test_exception_in_parser_but_reply_to_defined(self):
        """Even more unlikely scenario of an email missing a body but having a
        ReplyTo."""
        self._test_exception_in_parser_but_can_send_email(
            {'ReplyTo': {'EmailAddress': 'bob@dole.org'}})

    def test_exception_to_notifications_alias(self):
        email_text = copy.deepcopy(self.email_text)
        email_text['To'] = [{
            'EmailAddress': 'notifications@%s' % settings.INBOUND_EMAIL_DOMAIN,
            'FriendlyName': 'not a valid activity mail reply'}]
        assert not add_email_to_activity_log_wrapper(email_text)
        assert len(mail.outbox) == 1
        out = mail.outbox[0]
        assert ('This email address is not meant to receive emails '
                'directly.') in out.body
        assert out.subject == 'Re: This is the subject of a test message.'
        assert out.to == ['sender@example.com']

    @override_switch('activity-email-bouncing', active=False)
    def test_exception_but_bouncing_waffle_off(self):
        # Fails because the token doesn't exist in ActivityToken.objects
        assert not add_email_to_activity_log_wrapper(self.email_text)
        # But no bounce.
        assert len(mail.outbox) == 0


class TestAddEmailToActivityLog(TestCase):
    def setUp(self):
        self.addon = addon_factory(name='Badger', status=amo.STATUS_NOMINATED)
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        self.profile = user_factory()
        self.token = ActivityLogToken.objects.create(
            version=version, user=self.profile)
        self.token.update(uuid='5a0b8a83d501412589cc5d562334b46b')
        self.parser = ActivityEmailParser(sample_message_content['Message'])

    def test_developer_comment(self):
        self.profile.addonuser_set.create(addon=self.addon)
        note = add_email_to_activity_log(self.parser)
        assert note.log == amo.LOG.DEVELOPER_REPLY_VERSION
        self.token.refresh_from_db()
        assert self.token.use_count == 1

    def test_reviewer_comment(self):
        self.grant_permission(self.profile, 'Addons:Review')
        note = add_email_to_activity_log(self.parser)
        assert note.log == amo.LOG.REVIEWER_REPLY_VERSION
        self.token.refresh_from_db()
        assert self.token.use_count == 1

    def test_with_max_count_token(self):
        """Test with an invalid token."""
        self.token.update(use_count=MAX_TOKEN_USE_COUNT + 1)
        with self.assertRaises(ActivityEmailTokenError):
            assert not add_email_to_activity_log(self.parser)
        self.token.refresh_from_db()
        assert self.token.use_count == MAX_TOKEN_USE_COUNT + 1

    def test_with_unpermitted_token(self):
        """Test when the token user doesn't have a permission to add a note."""
        with self.assertRaises(ActivityEmailTokenError):
            assert not add_email_to_activity_log(self.parser)
        self.token.refresh_from_db()
        assert self.token.use_count == 0

    def test_non_existent_token(self):
        self.token.update(uuid='12345678901234567890123456789012')
        with self.assertRaises(ActivityEmailUUIDError):
            assert not add_email_to_activity_log(self.parser)

    def test_broken_token(self):
        parser = ActivityEmailParser(
            copy.deepcopy(sample_message_content['Message']))
        parser.email['To'][0]['EmailAddress'] = 'reviewreply+1234@foo.bar'
        with self.assertRaises(ActivityEmailUUIDError):
            assert not add_email_to_activity_log(parser)


class TestLogAndNotify(TestCase):

    def setUp(self):
        self.developer = user_factory()
        self.developer2 = user_factory()
        self.reviewer = user_factory()
        self.grant_permission(self.reviewer, 'Addons:Review',
                              'Addon Reviewers')

        self.addon = addon_factory()
        self.version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        self.addon.addonuser_set.create(user=self.developer)
        self.addon.addonuser_set.create(user=self.developer2)
        self.task_user = user_factory(id=settings.TASK_USER_ID)

    def _create(self, action, author=None):
        author = author or self.reviewer
        details = {
            'comments': u'I spy, with my líttle €ye...',
            'version': self.version.version}
        activity = ActivityLog.create(
            action, self.addon, self.version, user=author, details=details)
        activity.update(created=self.days_ago(1))
        return activity

    def _recipients(self, email_mock):
        recipients = []
        for call in email_mock.call_args_list:
            recipients += call[1]['recipient_list']
            [reply_to] = call[1]['reply_to']
            assert reply_to.startswith('reviewreply+')
            assert reply_to.endswith(settings.INBOUND_EMAIL_DOMAIN)
        return recipients

    def _check_email_info_request(self, call, url, reason_text, days_text):
        subject = call[0][0]
        body = call[0][1]
        assert subject == u'Mozilla Add-ons: Action Required for %s %s' % (
            self.addon.name, self.version.version)
        assert ('visit %s' % url) in body
        assert ('receiving this email because %s' % reason_text) in body
        if days_text is not None:
            assert 'If we do not hear from you within' in body
            assert days_text in body
            assert 'reviewing version %s of the add-on %s' % (
                self.version.version, self.addon.name) in body

    def _check_email(self, call, url, reason_text):
        subject = call[0][0]
        body = call[0][1]
        assert subject == u'Mozilla Add-ons: %s %s' % (
            self.addon.name, self.version.version)
        assert ('visit %s' % url) in body
        assert ('receiving this email because %s' % reason_text) in body
        assert 'If we do not hear from you within' not in body

    @mock.patch('olympia.activity.utils.send_mail')
    def test_reviewer_request_for_information(self, send_mail_mock):
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            pending_info_request=datetime.now() + timedelta(days=7))
        self._create(amo.LOG.REQUEST_INFORMATION, self.reviewer)
        log_and_notify(
            amo.LOG.REQUEST_INFORMATION, 'blah', self.reviewer, self.version)

        assert send_mail_mock.call_count == 2  # Both authors.
        sender = '%s <notifications@%s>' % (
            self.reviewer.name, settings.INBOUND_EMAIL_DOMAIN)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 2
        assert self.developer.email in recipients
        assert self.developer2.email in recipients
        # The reviewer who sent it doesn't get their email back.
        assert self.reviewer.email not in recipients

        self._check_email_info_request(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            'seven (7) days of this notification')
        self._check_email_info_request(
            send_mail_mock.call_args_list[1],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            'seven (7) days of this notification')

    @mock.patch('olympia.activity.utils.send_mail')
    def test_reviewer_request_for_information_close_date(self, send_mail_mock):
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            pending_info_request=datetime.now() + timedelta(days=1))
        self._create(amo.LOG.REQUEST_INFORMATION, self.reviewer)
        log_and_notify(
            amo.LOG.REQUEST_INFORMATION, 'blah', self.reviewer, self.version)

        assert send_mail_mock.call_count == 2  # Both authors.
        sender = '%s <notifications@%s>' % (
            self.reviewer.name, settings.INBOUND_EMAIL_DOMAIN)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 2
        assert self.developer.email in recipients
        assert self.developer2.email in recipients
        # The reviewer who sent it doesn't get their email back.
        assert self.reviewer.email not in recipients

        self._check_email_info_request(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            'one (1) day of this notification')
        self._check_email_info_request(
            send_mail_mock.call_args_list[1],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            'one (1) day of this notification')

    @mock.patch('olympia.activity.utils.send_mail')
    def test_reviewer_request_for_information_far_date(self, send_mail_mock):
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            pending_info_request=datetime.now() + timedelta(days=21))
        self._create(amo.LOG.REQUEST_INFORMATION, self.reviewer)
        log_and_notify(
            amo.LOG.REQUEST_INFORMATION, 'blah', self.reviewer, self.version)

        assert send_mail_mock.call_count == 2  # Both authors.
        sender = '%s <notifications@%s>' % (
            self.reviewer.name, settings.INBOUND_EMAIL_DOMAIN)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 2
        assert self.developer.email in recipients
        assert self.developer2.email in recipients
        # The reviewer who sent it doesn't get their email back.
        assert self.reviewer.email not in recipients

        self._check_email_info_request(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            '21 days of this notification')
        self._check_email_info_request(
            send_mail_mock.call_args_list[1],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            '21 days of this notification')

    def test_post_reviewer_request_for_information(self):
        GroupUser.objects.filter(user=self.reviewer).delete()
        self.grant_permission(
            self.reviewer, 'Addons:PostReview', 'Reviewers: Foo')
        self.test_reviewer_request_for_information()

    def test_content_reviewer_request_for_information(self):
        GroupUser.objects.filter(user=self.reviewer).delete()
        self.grant_permission(
            self.reviewer, 'Addons:ContentReview', 'Reviewers: Bar')
        self.test_reviewer_request_for_information()

    @mock.patch('olympia.activity.utils.send_mail')
    def test_developer_reply(self, send_mail_mock):
        # Set pending info request flag to make sure
        # it has been dropped after the reply.
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            pending_info_request=datetime.now() + timedelta(days=1))
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # One from the developer.  So the developer is on the 'thread'
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = u'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 2  # We added one above.
        assert logs[0].details['comments'] == u'Thïs is á reply'

        assert send_mail_mock.call_count == 2  # One author, one reviewer.
        sender = '%s <notifications@%s>' % (
            self.developer.name, settings.INBOUND_EMAIL_DOMAIN)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 2
        assert self.reviewer.email in recipients
        assert self.developer2.email in recipients
        # The developer who sent it doesn't get their email back.
        assert self.developer.email not in recipients

        self._check_email(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.')
        review_url = absolutify(
            reverse('reviewers.review',
                    kwargs={'addon_id': self.version.addon.pk,
                            'channel': 'listed'},
                    add_prefix=False))
        self._check_email(
            send_mail_mock.call_args_list[1],
            review_url, 'you reviewed this add-on.')

        self.addon = Addon.objects.get(pk=self.addon.pk)
        assert not self.addon.pending_info_request

    @mock.patch('olympia.activity.utils.send_mail')
    def test_reviewer_reply(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # One from the developer.
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.REVIEWER_REPLY_VERSION
        comments = u'Thîs ïs a revïewer replyîng'
        log_and_notify(action, comments, self.reviewer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1
        assert logs[0].details['comments'] == u'Thîs ïs a revïewer replyîng'

        assert send_mail_mock.call_count == 2  # Both authors.
        sender = '%s <notifications@%s>' % (
            self.reviewer.name, settings.INBOUND_EMAIL_DOMAIN)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 2
        assert self.developer.email in recipients
        assert self.developer2.email in recipients
        # The reviewer who sent it doesn't get their email back.
        assert self.reviewer.email not in recipients

        self._check_email(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.')
        self._check_email(
            send_mail_mock.call_args_list[1],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.')

    @mock.patch('olympia.activity.utils.send_mail')
    def test_log_with_no_comment(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        action = amo.LOG.APPROVAL_NOTES_CHANGED
        log_and_notify(
            action=action, comments=None, note_creator=self.developer,
            version=self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1
        assert not logs[0].details  # No details json because no comment.

        assert send_mail_mock.call_count == 2  # One author, one reviewer.
        sender = '%s <notifications@%s>' % (
            self.developer.name, settings.INBOUND_EMAIL_DOMAIN)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 2
        assert self.reviewer.email in recipients
        assert self.developer2.email in recipients

        assert u'Approval notes changed' in (
            send_mail_mock.call_args_list[0][0][1])
        assert u'Approval notes changed' in (
            send_mail_mock.call_args_list[1][0][1])

    def test_staff_cc_group_is_empty_no_failure(self):
        Group.objects.create(name=ACTIVITY_MAIL_GROUP, rules='None:None')
        log_and_notify(amo.LOG.REJECT_VERSION, u'á', self.reviewer,
                       self.version)

    @mock.patch('olympia.activity.utils.send_mail')
    def test_staff_cc_group_get_mail(self, send_mail_mock):
        self.grant_permission(self.reviewer, 'None:None', ACTIVITY_MAIL_GROUP)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = u'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1

        recipients = self._recipients(send_mail_mock)
        sender = '%s <notifications@%s>' % (
            self.developer.name, settings.INBOUND_EMAIL_DOMAIN)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        assert len(recipients) == 2
        # self.reviewers wasn't on the thread, but gets an email anyway.
        assert self.reviewer.email in recipients
        assert self.developer2.email in recipients
        review_url = absolutify(
            reverse('reviewers.review',
                    kwargs={'addon_id': self.version.addon.pk,
                            'channel': 'listed'},
                    add_prefix=False))
        self._check_email(send_mail_mock.call_args_list[1],
                          review_url,
                          'you are member of the activity email cc group.')

    @mock.patch('olympia.activity.utils.send_mail')
    def test_task_user_doesnt_get_mail(self, send_mail_mock):
        """The task user account is used to auto-sign unlisted addons, amongst
        other things, but we don't want that user account to get mail."""
        self._create(amo.LOG.APPROVE_VERSION, self.task_user)

        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = u'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1

        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 1
        assert self.developer2.email in recipients
        assert self.task_user.email not in recipients

    @mock.patch('olympia.activity.utils.send_mail')
    def test_ex_reviewer_doesnt_get_mail(self, send_mail_mock):
        """If a reviewer has now left the team don't email them."""
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # Take his joob!
        GroupUser.objects.get(group=Group.objects.get(name='Addon Reviewers'),
                              user=self.reviewer).delete()

        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = u'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1

        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 1
        assert self.developer2.email in recipients
        assert self.reviewer.email not in recipients

    @mock.patch('olympia.activity.utils.send_mail')
    def test_review_url_listed(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # One from the developer.  So the developer is on the 'thread'
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = u'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 2  # We added one above.
        assert logs[0].details['comments'] == u'Thïs is á reply'

        assert send_mail_mock.call_count == 2  # One author, one reviewer.
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 2
        assert self.reviewer.email in recipients
        assert self.developer2.email in recipients
        # The developer who sent it doesn't get their email back.
        assert self.developer.email not in recipients

        self._check_email(send_mail_mock.call_args_list[0],
                          absolutify(self.addon.get_dev_url('versions')),
                          'you are listed as an author of this add-on.')
        review_url = absolutify(
            reverse('reviewers.review', add_prefix=False,
                    kwargs={'channel': 'listed', 'addon_id': self.addon.pk}))
        self._check_email(send_mail_mock.call_args_list[1],
                          review_url, 'you reviewed this add-on.')

    @mock.patch('olympia.activity.utils.send_mail')
    def test_review_url_unlisted(self, send_mail_mock):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted',
                              'Addon Reviewers')

        # One from the reviewer.
        self._create(amo.LOG.COMMENT_VERSION, self.reviewer)
        # One from the developer.  So the developer is on the 'thread'
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = u'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 2  # We added one above.
        assert logs[0].details['comments'] == u'Thïs is á reply'

        assert send_mail_mock.call_count == 2  # One author, one reviewer.
        recipients = self._recipients(send_mail_mock)

        assert len(recipients) == 2
        assert self.reviewer.email in recipients
        assert self.developer2.email in recipients
        # The developer who sent it doesn't get their email back.
        assert self.developer.email not in recipients

        self._check_email(send_mail_mock.call_args_list[0],
                          absolutify(self.addon.get_dev_url('versions')),
                          'you are listed as an author of this add-on.')
        review_url = absolutify(
            reverse('reviewers.review', add_prefix=False,
                    kwargs={'channel': 'unlisted', 'addon_id': self.addon.pk}))
        self._check_email(send_mail_mock.call_args_list[1],
                          review_url, 'you reviewed this add-on.')

    @mock.patch('olympia.activity.utils.send_mail')
    def test_from_name_escape(self, send_mail_mock):
        self.reviewer.update(display_name='mr "quote" escape')

        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        action = amo.LOG.REVIEWER_REPLY_VERSION
        comments = u'Thîs ïs a revïewer replyîng'
        log_and_notify(action, comments, self.reviewer, self.version)

        sender = r'"mr \"quote\" escape" <notifications@%s>' % (
            settings.INBOUND_EMAIL_DOMAIN)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']

    @mock.patch('olympia.activity.utils.send_mail')
    def test_comment_entity_decode(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        action = amo.LOG.REVIEWER_REPLY_VERSION
        comments = u'This email&#39;s entities should be decoded'
        log_and_notify(action, comments, self.reviewer, self.version)

        body = send_mail_mock.call_args_list[1][0][1]
        assert "email's entities should be decoded" in body
        assert "&" not in body

    @mock.patch('olympia.activity.utils.send_mail')
    def test_notify_about_previous_activity(self, send_mail_mock):
        # Create an activity to use when notifying.
        activity = self._create(amo.LOG.REQUEST_INFORMATION, self.reviewer)
        notify_about_activity_log(self.addon, self.version, activity)
        assert ActivityLog.objects.count() == 1  # No new activity created.

        assert send_mail_mock.call_count == 2  # Both authors.
        sender = '%s <notifications@%s>' % (
            self.reviewer.name, settings.INBOUND_EMAIL_DOMAIN)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 2
        assert self.developer.email in recipients
        assert self.developer2.email in recipients
        # The reviewer who sent it doesn't get their email back.
        assert self.reviewer.email not in recipients

        self._check_email_info_request(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            days_text=None)
        self._check_email_info_request(
            send_mail_mock.call_args_list[1],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            days_text=None)


@pytest.mark.django_db
def test_send_activity_mail():
    subject = u'This ïs ã subject'
    message = u'And... this ïs a messãge!'
    addon = addon_factory()
    latest_version = addon.find_latest_version(
        channel=amo.RELEASE_CHANNEL_LISTED)
    user = user_factory()
    recipients = [user, ]
    from_email = 'bob@bob.bob'
    action = ActivityLog.create(amo.LOG.DEVELOPER_REPLY_VERSION, user=user)
    send_activity_mail(
        subject, message, latest_version, recipients, from_email, action.id)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].body == message
    assert mail.outbox[0].subject == subject
    uuid = latest_version.token.get(user=user).uuid.hex
    reference_header = '<{addon}/{version}@{site}>'.format(
        addon=latest_version.addon.id, version=latest_version.id,
        site=settings.INBOUND_EMAIL_DOMAIN)
    message_id = '<{addon}/{version}/{action}@{site}>'.format(
        addon=latest_version.addon.id, version=latest_version.id,
        action=action.id, site=settings.INBOUND_EMAIL_DOMAIN)

    assert mail.outbox[0].extra_headers['In-Reply-To'] == reference_header
    assert mail.outbox[0].extra_headers['References'] == reference_header
    assert mail.outbox[0].extra_headers['Message-ID'] == message_id

    reply_email = 'reviewreply+%s@%s' % (uuid, settings.INBOUND_EMAIL_DOMAIN)
    assert mail.outbox[0].reply_to == [reply_email]
