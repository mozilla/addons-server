import datetime

from django.conf import settings
from django.core import mail

import mock
from nose.tools import eq_

import amo
from abuse.models import AbuseReport
from amo.tasks import find_abuse_escalations, find_refund_escalations
from amo.tests import app_factory
from devhub.models import AppLog
from editors.models import EscalationQueue
from market.models import AddonPurchase, Refund
from stats.models import Contribution
from users.models import UserProfile


class TestAbuseEscalationTask(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.app = app_factory(name='XXX')
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

        patcher = mock.patch.object(settings, 'TASK_USER_ID', 4043307)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_abuses_no_history(self):
        find_abuse_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

    def test_abuse_no_history(self):
        for x in range(2):
            AbuseReport.objects.create(addon=self.app)
        find_abuse_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)

    def test_abuse_already_escalated(self):
        for x in range(2):
            AbuseReport.objects.create(addon=self.app)
        find_abuse_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)
        find_abuse_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)

    def test_abuse_cleared_not_escalated(self):
        for x in range(2):
            ar = AbuseReport.objects.create(addon=self.app)
            ar.created = datetime.datetime.now() - datetime.timedelta(days=1)
            ar.save()
        find_abuse_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)

        # Simulate a reviewer clearing an escalation... remove app from queue,
        # and write a log.
        EscalationQueue.objects.filter(addon=self.app).delete()
        amo.log(amo.LOG.ESCALATION_CLEARED, self.app, self.app.current_version,
                details={'comments': 'All clear'})
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

        # Task will find it again but not add it again.
        find_abuse_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

    def test_older_abuses_cleared_then_new(self):
        for x in range(2):
            ar = AbuseReport.objects.create(addon=self.app)
            ar.created = datetime.datetime.now() - datetime.timedelta(days=1)
            ar.save()
        find_abuse_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)

        # Simulate a reviewer clearing an escalation... remove app from queue,
        # and write a log.
        EscalationQueue.objects.filter(addon=self.app).delete()
        amo.log(amo.LOG.ESCALATION_CLEARED, self.app, self.app.current_version,
                details={'comments': 'All clear'})
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

        # Task will find it again but not add it again.
        find_abuse_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

        # New abuse reports that come in should re-add to queue.
        for x in range(2):
            AbuseReport.objects.create(addon=self.app)
        find_abuse_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)

    @mock.patch('amo.tasks.find_abuse_escalations')
    def test_task_called_on_abuse_report(self, _mock):
        self.client.post(self.app.get_detail_url('abuse'),
                         {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.all()[0]
        eq_(report.message, 'spammy')
        eq_(report.addon, self.app)
        _mock.delay.assert_called_with(self.app.id)


class TestRefundsEscalationTask(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.app = app_factory(name='XXX')
        self.user1, self.user2, self.user3 = UserProfile.objects.all()[:3]

        patcher = mock.patch.object(settings, 'TASK_USER_ID', 4043307)
        patcher.start()
        self.addCleanup(patcher.stop)

        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

    def _purchase(self, user=None, created=None):
        ap1 = AddonPurchase.objects.create(user=user or self.user1,
                                           addon=self.app)
        if created:
            ap1.update(created=created)

    def _refund(self, user=None, created=None):
        contribution = Contribution.objects.create(addon=self.app,
                                                   user=user or self.user1)
        ref = Refund.objects.create(contribution=contribution)
        if created:
            ref.update(created=created)
            # Needed because these tests can run in the same second and the
            # refund detection task depends on timestamp logic for when to
            # escalate.
            applog = AppLog.objects.all().order_by('-created')[0]
            applog.update(created=created)

    def test_multiple_refunds_same_user(self):
        self._purchase(self.user1)
        self._refund(self.user1)
        self._refund(self.user1)
        eq_(Refund.recent_refund_ratio(
            self.app.id, datetime.datetime.now() - datetime.timedelta(days=1)),
            1.0)

    def test_no_refunds(self):
        find_refund_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

    def test_refunds(self):
        self._purchase(self.user1)
        self._purchase(self.user2)
        self._refund(self.user1)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)

    def test_refunds_already_escalated(self):
        self._purchase(self.user1)
        self._purchase(self.user2)
        self._refund(self.user1)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)
        # Task was run on Refund.post_save, re-run task to make sure we don't
        # escalate again.
        find_refund_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)

    def test_refunds_cleared_not_escalated(self):
        stamp = datetime.datetime.now() - datetime.timedelta(days=2)
        self._purchase(self.user1, stamp)
        self._purchase(self.user2, stamp)
        self._refund(self.user1, stamp)

        # Simulate a reviewer clearing an escalation...
        #   remove app from queue and write a log.
        EscalationQueue.objects.filter(addon=self.app).delete()
        amo.log(amo.LOG.ESCALATION_CLEARED, self.app, self.app.current_version,
                details={'comments': 'All clear'})
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)
        # Task will find it again but not add it again.
        find_refund_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

    def test_older_refund_escalations_then_new(self):
        stamp = datetime.datetime.now() - datetime.timedelta(days=2)
        self._purchase(self.user1, stamp)
        self._purchase(self.user2, stamp)

        # Triggers 33% for refund / purchase ratio.
        self._refund(self.user1, stamp)

        # Simulate a reviewer clearing an escalation...
        #   remove app from queue and write a log.
        EscalationQueue.objects.filter(addon=self.app).delete()
        amo.log(amo.LOG.ESCALATION_CLEARED, self.app, self.app.current_version,
                details={'comments': 'All ok'})
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

        # Task will find it again but not add it again.
        find_refund_escalations(self.app.id)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)

        # Issue another refund, which should trigger another escalation.
        self._purchase(self.user3)
        self._refund(self.user3)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 1)
