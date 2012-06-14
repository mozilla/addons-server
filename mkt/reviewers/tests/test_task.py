import datetime

from django.conf import settings
from django.core import mail

import mock
from nose.tools import eq_

import amo
from abuse.models import AbuseReport
from amo.tasks import find_abuse_escalations
from amo.tests import app_factory

from mkt.reviewers.models import EscalationQueue


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

        # Cron will find it again but not add it again.
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

        # Cron will find it again but not add it again.
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
