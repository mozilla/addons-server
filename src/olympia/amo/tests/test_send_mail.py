import mimetypes
import os.path

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.core.mail import EmailMessage
from django.utils import translation

import mock

from celery.exceptions import Retry

from olympia.amo.models import FakeEmail
from olympia.amo.tests import BaseTestCase
from olympia.amo.utils import send_html_mail_jinja, send_mail
from olympia.users import notifications
from olympia.users.models import UserNotification, UserProfile


TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ATTACHMENTS_DIR = os.path.join(TESTS_DIR, 'attachments')


class TestSendMail(BaseTestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestSendMail, self).setUp()
        self._email_deny = list(getattr(settings, 'EMAIL_DENY_LIST', []))

    def tearDown(self):
        translation.activate('en_US')
        settings.EMAIL_DENY_LIST = self._email_deny
        super(TestSendMail, self).tearDown()

    def test_send_string(self):
        to = 'f@f.com'
        with self.assertRaises(ValueError):
            send_mail('subj', 'body', recipient_list=to)

    def test_deny(self):
        to = 'nobody@mozilla.org'
        settings.EMAIL_DENY_LIST = (to,)
        success = send_mail('test subject', 'test body', recipient_list=[to])

        assert success
        assert len(mail.outbox) == 0

    def test_deny_flag(self):
        to = 'nobody@mozilla.org'
        settings.EMAIL_DENY_LIST = (to,)
        success = send_mail('test subject', 'test body',
                            recipient_list=[to], use_deny_list=True)
        assert success
        assert len(mail.outbox) == 0

        success = send_mail('test subject', 'test body',
                            recipient_list=[to], use_deny_list=False)
        assert success
        assert len(mail.outbox) == 1

    def test_user_setting_default(self):
        user = UserProfile.objects.all()[0]
        to = user.email

        # Confirm there's nothing in the DB and we're using the default
        assert UserNotification.objects.count() == 0

        # Make sure that this is True by default
        setting = notifications.NOTIFICATIONS_BY_SHORT['reply']
        assert setting.default_checked

        success = send_mail('test subject', 'test body', perm_setting='reply',
                            recipient_list=[to])

        assert success, "Email wasn't sent"
        assert len(mail.outbox) == 1
        # bug 676601
        assert mail.outbox[0].body.count('users/unsubscribe') == 1

    def test_user_setting_checked(self):
        user = UserProfile.objects.all()[0]
        to = user.email
        n = notifications.NOTIFICATIONS_BY_SHORT['reply']
        UserNotification.objects.get_or_create(
            notification_id=n.id, user=user, enabled=True)

        # Confirm we're reading from the database
        assert UserNotification.objects.filter(
            notification_id=n.id).count() == 1

        success = send_mail('test subject', 'test body', perm_setting='reply',
                            recipient_list=[to])

        assert "You received this email because" in mail.outbox[0].body
        assert success, "Email wasn't sent"
        assert len(mail.outbox) == 1

    def test_user_mandatory(self):
        # Make sure there's no unsubscribe link in mandatory emails.
        user = UserProfile.objects.all()[0]
        to = user.email
        n = notifications.NOTIFICATIONS_BY_SHORT['individual_contact']

        UserNotification.objects.get_or_create(
            notification_id=n.id, user=user, enabled=True)

        assert n.mandatory, "Notification isn't mandatory"

        success = send_mail('test subject', 'test body', perm_setting=n,
                            recipient_list=[to])

        assert success, "Email wasn't sent"
        body = mail.outbox[0].body
        assert "Unsubscribe:" not in body
        assert "You can't unsubscribe from" in body

    def test_user_setting_unchecked(self):
        user = UserProfile.objects.all()[0]
        to = user.email
        n = notifications.NOTIFICATIONS_BY_SHORT['reply']
        UserNotification.objects.get_or_create(
            notification_id=n.id, user=user, enabled=False)

        # Confirm we're reading from the database.
        assert UserNotification.objects.filter(
            notification_id=n.id).count() == 1

        success = send_mail('test subject', 'test body', perm_setting='reply',
                            recipient_list=[to])

        assert success, "Email wasn't sent"
        assert len(mail.outbox) == 0

    @mock.patch.object(settings, 'EMAIL_DENY_LIST', ())
    def test_success_real_mail(self):
        assert send_mail('test subject', 'test body',
                         recipient_list=['nobody@mozilla.org'])
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject.find('test subject') == 0
        assert mail.outbox[0].body.find('test body') == 0

    @mock.patch.object(settings, 'EMAIL_DENY_LIST', ())
    @mock.patch.object(settings, 'SEND_REAL_EMAIL', False)
    def test_success_fake_mail(self):
        assert send_mail('test subject', 'test body',
                         recipient_list=['nobody@mozilla.org'])
        assert len(mail.outbox) == 0
        assert FakeEmail.objects.count() == 1
        assert FakeEmail.objects.get().message.endswith('test body')

    @mock.patch.object(settings, 'EMAIL_DENY_LIST', ())
    @mock.patch.object(settings, 'SEND_REAL_EMAIL', False)
    @mock.patch.object(settings, 'EMAIL_QA_ALLOW_LIST', ('nope@mozilla.org',))
    def test_qa_allowed_list(self):
        assert send_mail('test subject', 'test body',
                         recipient_list=['nope@mozilla.org'])
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject.find('test subject') == 0
        assert mail.outbox[0].body.find('test body') == 0
        assert FakeEmail.objects.count() == 1
        assert FakeEmail.objects.get().message.endswith('test body')

    @mock.patch.object(settings, 'EMAIL_DENY_LIST', ())
    @mock.patch.object(settings, 'SEND_REAL_EMAIL', False)
    @mock.patch.object(settings, 'EMAIL_QA_ALLOW_LIST', ('nope@mozilla.org',))
    def test_qa_allowed_list_with_mixed_emails(self):
        assert send_mail('test subject', 'test body',
                         recipient_list=['nope@mozilla.org', 'b@example.fr'])
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['nope@mozilla.org']
        assert FakeEmail.objects.count() == 1

    def test_dont_localize(self):
        user = UserProfile.objects.all()[0]
        to = user.email
        translation.activate('zh_TW')
        send_mail('test subject', 'test body', perm_setting='reply',
                  recipient_list=[to])
        assert u'an add-on developer replies to' in mail.outbox[0].body

    def test_send_html_mail_jinja(self):
        emails = ['omg@org.yes']
        subject = u'Mozilla Add-ons: Thank you for your submission!'
        html_template = 'devhub/email/submission.html'
        text_template = 'devhub/email/submission.txt'
        send_html_mail_jinja(subject, html_template, text_template,
                             context={}, recipient_list=emails,
                             from_email=settings.ADDONS_EMAIL,
                             use_deny_list=False,
                             perm_setting='individual_contact')

        msg = mail.outbox[0]
        message = msg.message()

        assert msg.to == emails
        assert msg.subject == subject
        assert msg.from_email == settings.ADDONS_EMAIL

        assert message.is_multipart()
        assert message.get_content_type() == 'multipart/alternative'
        assert message.get_default_type() == 'text/plain'

        payload = message.get_payload()
        assert payload[0].get_content_type() == 'text/plain'
        assert payload[1].get_content_type() == 'text/html'

        message1 = payload[0].as_string()
        message2 = payload[1].as_string()

        assert '<a href' not in message1, 'text-only email contained HTML!'
        assert '<a href' in message2, 'HTML email did not contain HTML!'

        unsubscribe_msg = unicode(notifications.individual_contact.label)
        assert unsubscribe_msg in message1
        assert unsubscribe_msg in message2

    def test_send_attachment(self):
        path = os.path.join(ATTACHMENTS_DIR, 'bacon.txt')
        attachments = [[os.path.basename(path), storage.open(path).read(),
                        mimetypes.guess_type(path)[0]]]
        send_mail('test subject', 'test body', from_email='a@example.com',
                  recipient_list=['b@example.com'], attachments=attachments)
        assert attachments == mail.outbox[0].attachments, (
            'Attachments not included')

    def test_send_multilines_subjects(self):
        send_mail('test\nsubject', 'test body', from_email='a@example.com',
                  recipient_list=['b@example.com'])
        assert 'test subject' == mail.outbox[0].subject, 'Subject not stripped'

    def test_autoresponse_headers(self):
        send_mail('subject', 'test body', from_email='a@example.com',
                  recipient_list=['b@example.com'])

        headers = mail.outbox[0].extra_headers
        assert headers['X-Auto-Response-Suppress'] == 'RN, NRN, OOF, AutoReply'
        assert headers['Auto-Submitted'] == 'auto-generated'

    def test_reply_to(self):
        send_mail('subject', 'test body', from_email='a@example.com',
                  recipient_list=['b@example.com'], reply_to=['c@example.com'])

        headers = mail.outbox[0].extra_headers
        assert mail.outbox[0].reply_to == ['c@example.com']
        assert headers['Auto-Submitted'] == 'auto-generated'  # Still there.

    def make_backend_class(self, error_order):
        throw_error = iter(error_order)

        def make_backend(*args, **kwargs):
            if next(throw_error):
                class BrokenMessage(object):
                    def __init__(*args, **kwargs):
                        pass

                    def send(*args, **kwargs):
                        raise RuntimeError('uh oh')

                    def attach_alternative(*args, **kwargs):
                        pass
                backend = BrokenMessage()
            else:
                backend = EmailMessage(*args, **kwargs)
            return backend
        return make_backend

    @mock.patch('olympia.amo.tasks.EmailMessage')
    def test_async_will_retry_default(self, backend):
        backend.side_effect = self.make_backend_class([True, True, False])
        with self.assertRaises(Retry):
            send_mail('test subject',
                      'test body',
                      recipient_list=['somebody@mozilla.org'])

    @mock.patch('olympia.amo.tasks.EmailMessage')
    def test_async_will_retry(self, backend):
        backend.side_effect = self.make_backend_class([True, True, False])
        with self.assertRaises(Retry):
            send_mail('test subject',
                      'test body',
                      max_retries=2,
                      recipient_list=['somebody@mozilla.org'])

    @mock.patch('olympia.amo.tasks.EmailMessage')
    def test_async_will_stop_retrying(self, backend):
        backend.side_effect = self.make_backend_class([True, True])
        with self.assertRaises(RuntimeError):
            send_mail('test subject',
                      'test body',
                      max_retries=1,
                      recipient_list=['somebody@mozilla.org'])
