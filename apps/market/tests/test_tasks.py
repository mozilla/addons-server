from django.conf import settings
from django.core import mail
from django.core.management import call_command

import mock
from nose.tools import eq_
from waffle import Sample, Switch

import amo
import amo.tests
from addons.management.commands import process_addons
from addons.models import Addon
from market.models import PaypalCheckStatus
from market.tasks import (check_paypal, check_paypal_multiple,
                          _check_paypal_completed)
from devhub.models import ActivityLog


@mock.patch.object(settings, 'TASK_USER_ID', 999)
class TestCheckPaypal(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.addon.update(slug='test', status=amo.STATUS_PUBLIC)
        self.pks = ['3615']
        Sample.objects.create(name='paypal-disabled-limit', percent='10.0')
        Switch.objects.create(name='paypal-disable', active=1)
        self.check = mock.Mock()
        self.check.return_value = []
        process_addons.tasks['check_paypal']['pre'] = self.check

    def get_check(self, passed, errors=[]):
        _mock = mock.Mock()
        _mock.passed = passed
        _mock.errors = errors
        return mock.Mock(return_value=_mock)

    def test_pass(self):
        pks = check_paypal_multiple(self.pks)
        check_paypal(pks, self.get_check(True))
        assert len(mail.outbox) == 0, len(mail.outbox)

    def test_fail_limit(self):
        pks = check_paypal_multiple(self.pks)
        check_paypal(pks, self.get_check(False))
        assert 'error' in mail.outbox[0].subject, mail.outbox[0].subject

    def test_fail_not_limit(self):
        pks = check_paypal_multiple(self.pks, limit=0)
        check_paypal(pks, self.get_check(False))
        eq_(len(mail.outbox), 2)
        eq_(mail.outbox[0].to, [a.email for a in self.addon.authors.all()])

    def test_fail_not_limit_app(self):
        self.addon.update(type=amo.ADDON_WEBAPP)
        pks = check_paypal_multiple(self.pks, limit=0)
        check_paypal(pks, self.get_check(False))
        assert 'app' in mail.outbox[0].body

    def test_fail_not_limit_addon(self):
        pks = check_paypal_multiple(self.pks, limit=0)
        check_paypal(pks, self.get_check(False))
        assert 'add-on' in mail.outbox[0].body

    def test_fail_with_error(self):
        pks = check_paypal_multiple(self.pks, limit=0)
        _mock = self.get_check(False, errors=['This is a test.'])
        check_paypal(pks, _mock)
        assert 'This is a test' in mail.outbox[0].body

    def test_error(self):
        pks = check_paypal_multiple(self.pks, limit=0)
        _mock = self.get_check(False)
        _mock.side_effect = ValueError
        check_paypal(pks, _mock)
        eq_(PaypalCheckStatus.objects.count(), 1)

    def test_no_addon(self):
        pks = check_paypal_multiple([3516], limit=0)
        check_paypal(pks)
        eq_(PaypalCheckStatus.objects.count(), 0)

    def test_at_end(self):
        pks = check_paypal_multiple(self.pks * 2)
        check_paypal(pks[:1])
        assert not _check_paypal_completed()
        check_paypal(pks[1:2])
        assert _check_paypal_completed()

    def test_disabled(self):
        pks = check_paypal_multiple(self.pks, limit=0)
        check_paypal(pks, self.get_check(False))
        addon = Addon.objects.get(pk=self.addon.pk)
        eq_(addon.status, amo.STATUS_DISABLED)
        eq_(ActivityLog.objects.for_addons(addon)
                       .filter(action=amo.LOG.PAYPAL_FAILED.id).count(), 1)

    def test_waffle(self):
        # Ensure that turning off the waffle flag, actually does something.
        switch = Switch.objects.get(name='paypal-disable')
        switch.active = 0
        switch.save()

        pks = check_paypal_multiple(self.pks, limit=0)
        check_paypal(pks, self.get_check(False))
        addon = Addon.objects.get(pk=self.addon.pk)
        eq_(addon.status, amo.STATUS_PUBLIC)
        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].to, [settings.FLIGTAR])

    # Check that the management command gets the right add-ons.
    def test_ignore_not_premium(self):
        call_command('process_addons', task='check_paypal')
        assert not self.check.call_args[0][0]

    def test_process_premium(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        call_command('process_addons', task='check_paypal')
        assert self.addon.pk in self.check.call_args[0][0]

    def test_ignore_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        call_command('process_addons', task='check_paypal')
        assert not self.check.call_args[0][0]

    def test_ignore_deleted(self):
        self.addon.update(status=amo.STATUS_DELETED)
        call_command('process_addons', task='check_paypal')
        assert not self.check.call_args[0][0]
