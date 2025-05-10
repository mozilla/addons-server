import copy
import json
import os
from datetime import datetime, timedelta
from email.utils import formataddr
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.files.base import ContentFile
from django.urls import reverse

import pytest
from waffle.testutils import override_switch

from olympia import amo
from olympia.access.models import Group
from olympia.activity.models import (
    MAX_TOKEN_USE_COUNT,
    ActivityLog,
    ActivityLogToken,
    AttachmentLog,
)
from olympia.activity.utils import (
    ACTIVITY_MAIL_GROUP,
    ADDON_REVIEWER_NAME,
    ActivityEmailEncodingError,
    ActivityEmailError,
    ActivityEmailParser,
    ActivityEmailTokenError,
    ActivityEmailUUIDError,
    add_email_to_activity_log,
    add_email_to_activity_log_wrapper,
    log_and_notify,
    notify_about_activity_log,
    send_activity_mail,
)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import SQUOTE_ESCAPED, TestCase, addon_factory, user_factory
from olympia.constants.reviewers import REVIEWER_STANDARD_REPLY_TIME
from olympia.versions.utils import get_review_due_date


TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sample_message_file = os.path.join(TESTS_DIR, 'emails', 'message.json')
with open(sample_message_file) as file_object:
    sample_message_content = json.loads(file_object.read())


class TestEmailParser(TestCase):
    def test_basic_email(self):
        parser = ActivityEmailParser(sample_message_content['Message'])
        assert parser.get_uuid() == '5a0b8a83d501412589cc5d562334b46b'
        assert parser.reply == ("This is a developer reply to an AMO.  It's nice.")

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

    def test_empty_text_body(self):
        """We receive requests that either have no `TextBody` or it's None

        https://github.com/mozilla/addons-server/issues/8848
        """
        message = copy.deepcopy(sample_message_content['Message'])
        message['TextBody'] = None

        with self.assertRaises(ActivityEmailEncodingError):
            ActivityEmailParser(message)

        message = copy.deepcopy(sample_message_content['Message'])
        message.pop('TextBody', None)

        with self.assertRaises(ActivityEmailEncodingError):
            ActivityEmailParser(message)


@override_switch('activity-email-bouncing', active=True)
class TestEmailBouncing(TestCase):
    BOUNCE_REPLY = (
        'Hello,\n\nAn email was received, apparently from you. Unfortunately '
        "we couldn't process it because of:\n%s\n\nPlease visit %s to leave "
        'a reply instead.\n--\nMozilla Add-ons\n%s\n'
    )

    def setUp(self):
        self.bounce_reply = self.BOUNCE_REPLY % (
            '%s',
            settings.SITE_URL,
            settings.SITE_URL,
        )
        self.email_text = sample_message_content['Message']

    @mock.patch('olympia.activity.utils.ActivityLog.objects.create')
    def test_no_note_logged(self, log_mock):
        # First set everything up so it's working
        addon = addon_factory()
        version = addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        user = user_factory()
        self.grant_permission(user, '*:*')
        ActivityLogToken.objects.create(
            user=user, version=version, uuid='5a0b8a83d501412589cc5d562334b46b'
        )
        # Make log_mock return false for some reason.
        log_mock.return_value = False

        # No exceptions thrown, but no log means something went wrong.
        assert not add_email_to_activity_log_wrapper(self.email_text, 0)
        assert len(mail.outbox) == 1
        out = mail.outbox[0]
        assert out.body == (self.bounce_reply % 'Undefined Error.')
        assert out.subject == 'Re: This is the subject of a test message.'
        assert out.to == ['sender@example.com']

    def test_exception_because_invalid_token(self):
        # Fails because the token doesn't exist in ActivityToken.objects
        assert not add_email_to_activity_log_wrapper(self.email_text, 0)
        assert len(mail.outbox) == 1
        out = mail.outbox[0]
        assert out.body == (
            self.bounce_reply
            % 'UUID found in email address TO: header but is not a valid token '
            '(5a0b8a83d501412589cc5d562334b46b).'
        )
        assert out.subject == 'Re: This is the subject of a test message.'
        assert out.to == ['sender@example.com']

    def test_exception_because_invalid_email(self):
        # Fails because the token doesn't exist in ActivityToken.objects
        email_text = copy.deepcopy(self.email_text)
        email_text['To'] = [
            {
                'EmailAddress': 'foobar@addons.mozilla.org',
                'FriendlyName': 'not a valid activity mail reply',
            }
        ]
        assert not add_email_to_activity_log_wrapper(email_text, 0)
        assert len(mail.outbox) == 1
        out = mail.outbox[0]
        assert out.body == (
            self.bounce_reply % 'TO: address does not contain activity email uuid ('
            'foobar@addons.mozilla.org).'
        )
        assert out.subject == 'Re: This is the subject of a test message.'
        assert out.to == ['sender@example.com']

    def test_exception_parser_because_malformed_message(self):
        assert not add_email_to_activity_log_wrapper('blah de blah', 0)
        # No From or Reply means no bounce, alas.
        assert len(mail.outbox) == 0

    def test_exception_parser_because_malformed_from(self):
        message = copy.deepcopy(self.email_text)
        message['From'] = {'EmailAddress': '@nowhere.com'}
        assert not add_email_to_activity_log_wrapper(message, 0)
        assert len(mail.outbox) == 0

    def test_exception_parser_because_malformed_from_encoding(self):
        message = copy.deepcopy(self.email_text)
        message['From'] = {'EmailAddress': 'abc@d���.com'}
        assert not add_email_to_activity_log_wrapper(message, 0)
        assert len(mail.outbox) == 0

    def _test_exception_in_parser_but_can_send_email(self, message):
        assert not add_email_to_activity_log_wrapper(message, 0)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].body == (
            self.bounce_reply % 'Invalid or malformed json message object.'
        )
        assert mail.outbox[0].subject == 'Re: your email to us'
        assert mail.outbox[0].to == ['bob@dole.org']

    def test_exception_in_parser_but_from_defined(self):
        """Unlikely scenario of an email missing a body but having a From."""
        self._test_exception_in_parser_but_can_send_email(
            {'From': {'EmailAddress': 'bob@dole.org'}}
        )

    def test_exception_in_parser_but_reply_to_defined(self):
        """Even more unlikely scenario of an email missing a body but having a
        ReplyTo."""
        self._test_exception_in_parser_but_can_send_email(
            {'ReplyTo': {'EmailAddress': 'bob@dole.org'}}
        )

    @override_switch('activity-email-bouncing', active=False)
    def test_exception_but_bouncing_waffle_off(self):
        # Fails because the token doesn't exist in ActivityToken.objects
        assert not add_email_to_activity_log_wrapper(self.email_text, 0)
        # But no bounce.
        assert len(mail.outbox) == 0

    def test_exception_but_spammy(self):
        # Fails because the token doesn't exist in ActivityToken.objects
        assert not add_email_to_activity_log_wrapper(self.email_text, 10.0)
        assert not add_email_to_activity_log_wrapper(self.email_text, 10)
        assert not add_email_to_activity_log_wrapper(self.email_text, '10')
        assert not add_email_to_activity_log_wrapper(self.email_text, 11.0)
        # But no bounce.
        assert len(mail.outbox) == 0
        # but should be bounced if below the threshaold
        assert not add_email_to_activity_log_wrapper(self.email_text, 9.9)


class TestAddEmailToActivityLog(TestCase):
    def setUp(self):
        self.addon = addon_factory(name='Badger', status=amo.STATUS_NOMINATED)
        self.version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        self.profile = user_factory()
        self.token = ActivityLogToken.objects.create(
            version=self.version, user=self.profile
        )
        self.token.update(uuid='5a0b8a83d501412589cc5d562334b46b')
        self.parser = ActivityEmailParser(sample_message_content['Message'])
        user_factory(id=settings.TASK_USER_ID)
        assert not self.version.due_date

    def test_developer_comment(self):
        self.profile.addonuser_set.create(addon=self.addon)
        note = add_email_to_activity_log(self.parser)
        assert note.log == amo.LOG.DEVELOPER_REPLY_VERSION
        self.token.refresh_from_db()
        assert self.token.use_count == 1
        assert self.version.needshumanreview_set.exists()
        self.assertCloseToNow(
            self.version.reload().due_date,
            now=get_review_due_date(default_days=REVIEWER_STANDARD_REPLY_TIME),
        )

    def test_developer_comment_existing_due_date(self):
        self.profile.addonuser_set.create(addon=self.addon)
        self.version.needshumanreview_set.create()  # To force it to have a due date
        expected_due_date = datetime.now() + timedelta(days=1)
        self.version.update(due_date=expected_due_date)
        note = add_email_to_activity_log(self.parser)
        assert note.log == amo.LOG.DEVELOPER_REPLY_VERSION
        self.token.refresh_from_db()
        assert self.token.use_count == 1
        assert self.version.needshumanreview_set.exists()
        assert self.version.reload().due_date == expected_due_date

    def test_reviewer_comment(self):
        self.grant_permission(self.profile, 'Addons:Review')
        note = add_email_to_activity_log(self.parser)
        assert note.log == amo.LOG.REVIEWER_REPLY_VERSION
        self.token.refresh_from_db()
        assert self.token.use_count == 1
        assert not self.version.needshumanreview_set.exists()
        assert not self.version.reload().due_date

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
        parser = ActivityEmailParser(copy.deepcopy(sample_message_content['Message']))
        parser.email['To'][0]['EmailAddress'] = 'reviewreply+1234@foo.bar'
        with self.assertRaises(ActivityEmailUUIDError):
            assert not add_email_to_activity_log(parser)

    def test_banned_user(self):
        self.profile.addonuser_set.create(addon=self.addon)
        self.profile.update(banned=datetime.now())
        with self.assertRaises(ActivityEmailError):
            assert not add_email_to_activity_log(self.parser)


class TestLogAndNotify(TestCase):
    def setUp(self):
        self.developer = user_factory()
        self.developer2 = user_factory()
        self.reviewer = user_factory()
        self.grant_permission(self.reviewer, 'Addons:Review', 'Addon Reviewers')

        self.addon = addon_factory()
        self.version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        self.addon.addonuser_set.create(user=self.developer)
        self.addon.addonuser_set.create(user=self.developer2)
        self.task_user = user_factory(id=settings.TASK_USER_ID)

    def _create(self, action, author=None):
        author = author or self.reviewer
        details = {
            'comments': 'I spy, with my líttle €ye...',
            'version': self.version.version,
        }
        activity = ActivityLog.objects.create(
            action, self.addon, self.version, user=author, details=details
        )
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

    def _check_email(
        self,
        call,
        url,
        reason_text,
        *,
        author,
        is_from_developer=False,
        is_to_developer=False,
        expect_attachment=False,
    ):
        subject = call[0][0]
        body = call[0][1]
        assert subject == 'Mozilla Add-ons: {} {}'.format(
            self.addon.name,
            self.version.version,
        )
        assert ('visit %s' % url) in body
        assert ('receiving this email because %s' % reason_text) in body
        assert 'If we do not hear from you within' not in body
        assert self.reviewer.name not in body
        if is_to_developer and not is_from_developer:
            assert ('%s wrote:' % ADDON_REVIEWER_NAME) in body
        else:
            assert ('%s wrote:' % author.name) in body
        if expect_attachment:
            assert 'An attachment was provided.' in body

    @mock.patch('olympia.activity.utils.send_mail')
    def test_developer_reply(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # One from the developer.  So the developer is on the 'thread'
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = 'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 2  # We added one above.
        assert logs[0].details['comments'] == 'Thïs is á reply'

        assert send_mail_mock.call_count == 1  # One author.
        sender = formataddr((self.developer.name, settings.ADDONS_EMAIL))
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 1
        assert [self.developer2.email] == recipients
        # The developer who sent it doesn't get their email back.
        assert self.developer.email not in recipients

        self._check_email(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            author=self.developer,
            is_from_developer=True,
            is_to_developer=True,
        )

    @mock.patch('olympia.activity.utils.send_mail')
    def test_reviewer_reply(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # One from the developer.
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.REVIEWER_REPLY_VERSION
        comments = 'Thîs ïs a revïewer replyîng'
        log_and_notify(action, comments, self.reviewer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1
        assert logs[0].details['comments'] == 'Thîs ïs a revïewer replyîng'

        assert send_mail_mock.call_count == 2  # Both authors.
        sender = formataddr((ADDON_REVIEWER_NAME, settings.ADDONS_EMAIL))
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 2
        assert self.developer.email in recipients
        assert self.developer2.email in recipients

        self._check_email(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            author=self.reviewer,
            is_from_developer=False,
            is_to_developer=True,
        )
        self._check_email(
            send_mail_mock.call_args_list[1],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            author=self.reviewer,
            is_from_developer=False,
            is_to_developer=True,
        )

    @mock.patch('olympia.activity.utils.send_mail')
    def test_log_with_no_comment(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        action = amo.LOG.NOTES_FOR_REVIEWERS_CHANGED
        log_and_notify(
            action=action,
            comments=None,
            note_creator=self.developer,
            version=self.version,
        )

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1
        assert not logs[0].details  # No details json because no comment.

        assert send_mail_mock.call_count == 1  # One author.
        sender = formataddr((self.developer.name, settings.ADDONS_EMAIL))
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 1
        assert [self.developer2.email] == recipients

        assert 'Notes for reviewers changed' in (send_mail_mock.call_args_list[0][0][1])

    def test_staff_cc_group_is_empty_no_failure(self):
        Group.objects.create(name=ACTIVITY_MAIL_GROUP, rules='None:None')
        log_and_notify(amo.LOG.REJECT_VERSION, 'á', self.reviewer, self.version)

    @mock.patch('olympia.activity.utils.send_mail')
    def test_staff_cc_group_get_mail(self, send_mail_mock):
        self.grant_permission(self.reviewer, 'None:None', ACTIVITY_MAIL_GROUP)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = 'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1

        recipients = self._recipients(send_mail_mock)
        sender = formataddr((self.developer.name, settings.ADDONS_EMAIL))
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']
        assert len(recipients) == 2
        # self.reviewer wasn't on the thread, but gets an email anyway.
        assert self.reviewer.email in recipients
        assert self.developer2.email in recipients
        review_url = absolutify(
            reverse(
                'reviewers.review',
                kwargs={'addon_id': self.version.addon.pk, 'channel': 'listed'},
                add_prefix=False,
            )
        )
        self._check_email(
            send_mail_mock.call_args_list[1],
            review_url,
            'you are member of the activity email cc group.',
            author=self.developer,
        )

    @mock.patch('olympia.activity.utils.send_mail')
    def test_task_user_doesnt_get_mail(self, send_mail_mock):
        """The task user account is used to auto-sign unlisted addons, amongst
        other things, but we don't want that user account to get mail."""
        self._create(amo.LOG.APPROVE_VERSION, self.task_user)

        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = 'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 1

        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 1
        assert self.developer2.email in recipients
        assert self.task_user.email not in recipients

    @mock.patch('olympia.activity.utils.send_mail')
    def test_review_url_listed(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # One from the developer.  So the developer is on the 'thread'
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = 'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 2  # We added one above.
        assert logs[0].details['comments'] == 'Thïs is á reply'

        assert send_mail_mock.call_count == 1  # One author
        recipients = self._recipients(send_mail_mock)
        assert len(recipients) == 1
        assert [self.developer2.email] == recipients
        # The developer who sent it doesn't get their email back.
        assert self.developer.email not in recipients

        self._check_email(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            author=self.developer,
        )

    @mock.patch('olympia.activity.utils.send_mail')
    def test_review_url_unlisted(self, send_mail_mock):
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted', 'Addon Reviewers')

        # One from the reviewer.
        self._create(amo.LOG.REVIEWER_PRIVATE_COMMENT, self.reviewer)
        # One from the developer.  So the developer is on the 'thread'
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = 'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        logs = ActivityLog.objects.filter(action=action.id)
        assert len(logs) == 2  # We added one above.
        assert logs[0].details['comments'] == 'Thïs is á reply'

        assert send_mail_mock.call_count == 1  # One author
        recipients = self._recipients(send_mail_mock)

        assert len(recipients) == 1
        assert [self.developer2.email] == recipients
        # The developer who sent it doesn't get their email back.
        assert self.developer.email not in recipients

        self._check_email(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            author=self.developer,
        )

    @mock.patch('olympia.activity.utils.send_mail')
    def test_from_name_escape(self, send_mail_mock):
        self.developer.update(display_name='mr "quote" escape')

        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        # One from the developer.  So the developer is on the 'thread'
        self._create(amo.LOG.DEVELOPER_REPLY_VERSION, self.developer)
        action = amo.LOG.DEVELOPER_REPLY_VERSION
        comments = 'Thïs is á reply'
        log_and_notify(action, comments, self.developer, self.version)

        sender = r'"mr \"quote\" escape" <%s>' % (settings.ADDONS_EMAIL)
        assert sender == send_mail_mock.call_args_list[0][1]['from_email']

    @mock.patch('olympia.activity.utils.send_mail')
    def test_comment_entity_decode(self, send_mail_mock):
        # One from the reviewer.
        self._create(amo.LOG.REJECT_VERSION, self.reviewer)
        action = amo.LOG.REVIEWER_REPLY_VERSION
        comments = f'This email{SQUOTE_ESCAPED}s entities should be decoded'
        log_and_notify(action, comments, self.reviewer, self.version)

        body = send_mail_mock.call_args_list[1][0][1]
        assert "email's entities should be decoded" in body
        assert '&' not in body

    @mock.patch('olympia.activity.utils.send_mail')
    def test_notify_about_previous_activity(self, send_mail_mock):
        # Create an activity to use when notifying.
        activity = self._create(amo.LOG.REVIEWER_REPLY_VERSION, self.reviewer)
        notify_about_activity_log(self.addon, self.version, activity)
        assert ActivityLog.objects.count() == 1  # No new activity created.

        assert send_mail_mock.call_count == 2  # Both authors.
        sender = formataddr((ADDON_REVIEWER_NAME, settings.ADDONS_EMAIL))
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
            'you are listed as an author of this add-on.',
            author=self.reviewer,
            is_from_developer=False,
            is_to_developer=True,
        )
        self._check_email(
            send_mail_mock.call_args_list[1],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            author=self.reviewer,
            is_from_developer=False,
            is_to_developer=True,
        )

    @mock.patch('olympia.activity.utils.send_mail')
    def test_notify_about_attachment(self, send_mail_mock):
        activity = self._create(amo.LOG.REVIEWER_REPLY_VERSION, self.reviewer)
        AttachmentLog.objects.create(
            activity_log=activity,
            file=ContentFile('Pseudo File', name='attachment.txt'),
        )
        assert AttachmentLog.objects.count() == 1
        notify_about_activity_log(self.addon, self.version, activity)
        assert ActivityLog.objects.count() == 1

        self._check_email(
            send_mail_mock.call_args_list[0],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            author=self.reviewer,
            is_from_developer=False,
            is_to_developer=True,
            expect_attachment=True,
        )
        self._check_email(
            send_mail_mock.call_args_list[1],
            absolutify(self.addon.get_dev_url('versions')),
            'you are listed as an author of this add-on.',
            author=self.reviewer,
            is_from_developer=False,
            is_to_developer=True,
            expect_attachment=True,
        )


@pytest.mark.django_db
def test_send_activity_mail():
    subject = 'This ïs ã subject'
    message = 'And... this ïs a messãge!'
    addon = addon_factory()
    latest_version = addon.find_latest_version(channel=amo.CHANNEL_LISTED)
    user = user_factory()
    recipients = [
        user,
    ]
    from_email = 'bob@bob.bob'
    action = ActivityLog.objects.create(amo.LOG.DEVELOPER_REPLY_VERSION, user=user)
    send_activity_mail(
        subject, message, latest_version, recipients, from_email, action.id
    )

    assert len(mail.outbox) == 1
    assert mail.outbox[0].body == message
    assert mail.outbox[0].subject == subject
    uuid = latest_version.token.get(user=user).uuid.hex
    reference_header = '<{addon}/{version}@{site}>'.format(
        addon=latest_version.addon.id,
        version=latest_version.id,
        site=settings.INBOUND_EMAIL_DOMAIN,
    )
    message_id = '<{addon}/{version}/{action}@{site}>'.format(
        addon=latest_version.addon.id,
        version=latest_version.id,
        action=action.id,
        site=settings.INBOUND_EMAIL_DOMAIN,
    )

    assert mail.outbox[0].extra_headers['In-Reply-To'] == reference_header
    assert mail.outbox[0].extra_headers['References'] == reference_header
    assert mail.outbox[0].extra_headers['Message-ID'] == message_id

    reply_email = f'reviewreply+{uuid}@{settings.INBOUND_EMAIL_DOMAIN}'
    assert mail.outbox[0].reply_to == [reply_email]
