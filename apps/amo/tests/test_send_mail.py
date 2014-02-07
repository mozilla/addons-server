import mimetypes
import os.path

from django import test
from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.core.mail import EmailMessage
from django.template import Context as TemplateContext
from django.utils import translation

import mock
from nose.tools import eq_

from amo.models import FakeEmail
from amo.utils import send_mail, send_html_mail_jinja
from devhub.tests.test_models import ATTACHMENTS_DIR
from users.models import UserProfile, UserNotification
import users.notifications


class TestSendMail(test.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self._email_blacklist = list(getattr(settings, 'EMAIL_BLACKLIST', []))

    def tearDown(self):
        translation.activate('en_US')
        settings.EMAIL_BLACKLIST = self._email_blacklist

    def test_send_string(self):
        to = 'f@f.com'
        with self.assertRaises(ValueError):
            send_mail('subj', 'body', recipient_list=to)

    def test_blacklist(self):
        to = 'nobody@mozilla.org'
        settings.EMAIL_BLACKLIST = (to,)
        success = send_mail('test subject', 'test body',
                            recipient_list=[to], fail_silently=False)

        assert success
        eq_(len(mail.outbox), 0)

    def test_blacklist_flag(self):
        to = 'nobody@mozilla.org'
        settings.EMAIL_BLACKLIST = (to,)
        success = send_mail('test subject', 'test body',
                            recipient_list=[to], fail_silently=False,
                            use_blacklist=True)
        assert success
        eq_(len(mail.outbox), 0)

        success = send_mail('test subject', 'test body',
                            recipient_list=[to], fail_silently=False,
                            use_blacklist=False)
        assert success
        eq_(len(mail.outbox), 1)

    def test_user_setting_default(self):
        user = UserProfile.objects.all()[0]
        to = user.email

        # Confirm there's nothing in the DB and we're using the default
        eq_(UserNotification.objects.count(), 0)

        # Make sure that this is True by default
        setting = users.notifications.NOTIFICATIONS_BY_SHORT['reply']
        eq_(setting.default_checked, True)

        success = send_mail('test subject', 'test body', perm_setting='reply',
                            recipient_list=[to], fail_silently=False)

        assert success, "Email wasn't sent"
        eq_(len(mail.outbox), 1)

        eq_(mail.outbox[0].body.count('users/unsubscribe'), 1)  # bug 676601

    def test_user_setting_checked(self):
        user = UserProfile.objects.all()[0]
        to = user.email
        n = users.notifications.NOTIFICATIONS_BY_SHORT['reply']
        UserNotification.objects.get_or_create(notification_id=n.id,
                user=user, enabled=True)

        # Confirm we're reading from the database
        eq_(UserNotification.objects.filter(notification_id=n.id).count(), 1)

        success = send_mail('test subject', 'test body', perm_setting='reply',
                            recipient_list=[to], fail_silently=False)

        assert "You received this email because" in mail.outbox[0].body
        assert success, "Email wasn't sent"
        eq_(len(mail.outbox), 1)

    def test_user_mandatory(self):
        # Make sure there's no unsubscribe link in mandatory emails.
        user = UserProfile.objects.all()[0]
        to = user.email
        n = users.notifications.NOTIFICATIONS_BY_SHORT['individual_contact']

        UserNotification.objects.get_or_create(notification_id=n.id,
                user=user, enabled=True)

        assert n.mandatory, "Notification isn't mandatory"

        success = send_mail('test subject', 'test body', perm_setting=n,
                            recipient_list=[to], fail_silently=False)

        assert success, "Email wasn't sent"
        body = mail.outbox[0].body
        assert "Unsubscribe:" not in body
        assert "You can't unsubscribe from" in body

    def test_user_setting_unchecked(self):
        user = UserProfile.objects.all()[0]
        to = user.email
        n = users.notifications.NOTIFICATIONS_BY_SHORT['reply']
        UserNotification.objects.get_or_create(notification_id=n.id,
                user=user, enabled=False)

        # Confirm we're reading from the database.
        eq_(UserNotification.objects.filter(notification_id=n.id).count(), 1)

        success = send_mail('test subject', 'test body', perm_setting='reply',
                            recipient_list=[to], fail_silently=False)

        assert success, "Email wasn't sent"
        eq_(len(mail.outbox), 0)

    @mock.patch.object(settings, 'EMAIL_BLACKLIST', ())
    def test_success_real_mail(self):
        assert send_mail('test subject', 'test body',
                         recipient_list=['nobody@mozilla.org'],
                         fail_silently=False)
        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject.find('test subject'), 0)
        eq_(mail.outbox[0].body.find('test body'), 0)

    @mock.patch.object(settings, 'EMAIL_BLACKLIST', ())
    @mock.patch.object(settings, 'SEND_REAL_EMAIL', False)
    def test_success_fake_mail(self):
        assert send_mail('test subject', 'test body',
                         recipient_list=['nobody@mozilla.org'],
                         fail_silently=False)
        eq_(len(mail.outbox), 0)
        eq_(FakeEmail.objects.count(), 1)
        eq_(FakeEmail.objects.get().message.endswith('test body'), True)

    @mock.patch('amo.utils.Context')
    def test_dont_localize(self, fake_Context):
        perm_setting = []

        def ctx(d, autoescape):
            perm_setting.append(unicode(d['perm_setting']))
            return TemplateContext(d, autoescape=autoescape)
        fake_Context.side_effect = ctx
        user = UserProfile.objects.all()[0]
        to = user.email
        translation.activate('zh_TW')
        send_mail('test subject', 'test body', perm_setting='reply',
                             recipient_list=[to], fail_silently=False)
        eq_(perm_setting[0], u'an add-on developer replies to my review')

    def test_send_html_mail_jinja(self):
        emails = ['omg@org.yes']
        subject = u'Mozilla Add-ons: Thank you for your submission!'
        html_template = 'devhub/email/submission.html'
        text_template = 'devhub/email/submission.txt'
        send_html_mail_jinja(subject, html_template, text_template,
                             context={}, recipient_list=emails,
                             from_email=settings.NOBODY_EMAIL,
                             use_blacklist=False,
                             perm_setting='individual_contact',
                             headers={'Reply-To': settings.EDITORS_EMAIL})

        msg = mail.outbox[0]
        message = msg.message()

        eq_(msg.to, emails)
        eq_(msg.subject, subject)
        eq_(msg.from_email, settings.NOBODY_EMAIL)
        eq_(msg.extra_headers['Reply-To'], settings.EDITORS_EMAIL)

        eq_(message.is_multipart(), True)
        eq_(message.get_content_type(), 'multipart/alternative')
        eq_(message.get_default_type(), 'text/plain')

        payload = message.get_payload()
        eq_(payload[0].get_content_type(), 'text/plain')
        eq_(payload[1].get_content_type(), 'text/html')

        message1 = payload[0].as_string()
        message2 = payload[1].as_string()

        assert '<a href' not in message1, 'text-only email contained HTML!'
        assert '<a href' in message2, 'HTML email did not contain HTML!'

        unsubscribe_msg = unicode(users.notifications.individual_contact.label)
        assert unsubscribe_msg in message1
        assert unsubscribe_msg in message2

    def test_send_attachment(self):
        path = os.path.join(ATTACHMENTS_DIR, 'bacon.txt')
        attachments = [(os.path.basename(path), storage.open(path).read(),
                        mimetypes.guess_type(path)[0])]
        send_mail('test subject', 'test body', from_email='a@example.com',
                  recipient_list=['b@example.com'], attachments=attachments)
        eq_(attachments, mail.outbox[0].attachments, 'Attachments not included')

    def test_send_multilines_subjects(self):
        send_mail('test\nsubject', 'test body', from_email='a@example.com',
                  recipient_list=['b@example.com'])
        eq_('test subject', mail.outbox[0].subject, 'Subject not stripped')

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

    @mock.patch('amo.tasks.EmailMessage')
    def test_async_will_retry(self, backend):
        backend.side_effect = self.make_backend_class([True, True, False])
        with self.assertRaises(RuntimeError):
            send_mail('test subject',
                      'test body',
                      recipient_list=['somebody@mozilla.org'])
        assert send_mail('test subject',
                          'test body',
                          async=True,
                          recipient_list=['somebody@mozilla.org'])

    @mock.patch('amo.tasks.EmailMessage')
    def test_async_will_stop_retrying(self, backend):
        backend.side_effect = self.make_backend_class([True, True])
        with self.assertRaises(RuntimeError):
            send_mail('test subject',
                      'test body',
                      async=True,
                      max_retries=1,
                      recipient_list=['somebody@mozilla.org'])
