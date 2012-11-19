from django import test
from django.conf import settings
from django.core import mail
from django.template import Context as TemplateContext
from django.utils import translation

import mock
from nose.tools import eq_

from amo.models import FakeEmail
from amo.utils import send_mail
from users.models import UserProfile, UserNotification
import users.notifications


class TestSendMail(test.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self._email_blacklist = list(getattr(settings, 'EMAIL_BLACKLIST', []))

    def tearDown(self):
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
