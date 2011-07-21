from django import test
from django.conf import settings
from django.core import mail

from nose.tools import eq_

from amo.utils import send_mail
from users.models import UserProfile, UserNotification
import users.notifications


class SendMailTest(test.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self._email_blacklist = list(getattr(settings, 'EMAIL_BLACKLIST', []))

    def tearDown(self):
        settings.EMAIL_BLACKLIST = self._email_blacklist

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

        assert success, "Email wasn't sent"
        eq_(len(mail.outbox), 1)

    def test_user_setting_unchecked(self):
        user = UserProfile.objects.all()[0]
        to = user.email
        n = users.notifications.NOTIFICATIONS_BY_SHORT['reply']
        UserNotification.objects.get_or_create(notification_id=n.id,
                user=user, enabled=False)

        # Confirm we're reading from the database
        eq_(UserNotification.objects.filter(notification_id=n.id).count(), 1)

        success = send_mail('test subject', 'test body', perm_setting='reply',
                            recipient_list=[to], fail_silently=False)

        assert success, "Email wasn't sent"
        eq_(len(mail.outbox), 0)

    def test_success(self):
        to = 'nobody@mozilla.org'
        settings.EMAIL_BLACKLIST = ()
        success = send_mail('test subject', 'test body',
                            recipient_list=[to], fail_silently=False)

        assert success
        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].subject.find('test subject') == 0
        assert mail.outbox[0].body.find('test body') == 0

