from django.core import mail
from django.conf import settings

import mock
import waffle
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from devhub.models import UserLog
import users.notifications as email
from mkt.account.tests.test_views import PurchaseBase
from paypal import PaypalError


class TestRequestSupport(PurchaseBase):

    def logged(self, status):
        return (UserLog.objects.filter(user=self.user,
                                       activity_log__action=status.id))

    def test_support_not_logged_in(self):
        self.client.logout()
        eq_(self.client.get(self.get_support_url()).status_code, 302)

    def test_support_not_mine(self):
        self.client.login(username='admin@mozilla.com', password='password')
        eq_(self.client.get(self.get_support_url()).status_code, 404)

    def test_support_page_form(self):
        eq_(self.app.support_url, None)

        # If developer did not supply a support URL, we show a contact form.
        doc = pq(self.client.get(self.get_support_url()).content)
        eq_(doc('#support-start').find('a').eq(0).attr('href'),
            self.get_support_url('author'))

    def test_refund_link(self):
        doc = pq(self.client.get(self.get_support_url()).content)
        eq_(len(doc('#support-start').find('a')), 4)

    @mock.patch('apps.stats.models.Contribution.is_refunded')
    def test_no_refund_link(self, is_refunded):
        is_refunded.return_value = True
        doc = pq(self.client.get(self.get_support_url()).content)
        eq_(len(doc('#support-start').find('a')), 3)
        assert 'refunded' in doc('#support-start').find('li').eq(3).text()

    def test_support_page_external_link(self):
        self.app.support_url = 'http://omg.org/yes'
        self.app.save()

        # If developer supplied a support URL, we show that external link.
        doc = pq(self.client.get(self.get_support_url()).content)
        eq_(doc('#support-start').find('a').eq(0).attr('href'),
            self.get_support_url('site'))

    def test_support_site(self):
        self.app.support_url = 'http://omg.org/yes'
        self.app.save()

        doc = pq(self.client.get(self.get_support_url('site')).content)
        eq_(doc('.support-url a').attr('href'), unicode(self.app.support_url))

    def test_contact(self):
        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        res = self.client.post(self.get_support_url('author'), data)
        eq_(res.status_code, 302)

    def test_contact_mails(self):
        self.app.support_email = 'a@a.com'
        self.app.save()

        data = {'text': 'Lorem ipsum dolor sit amet, <3 consectetur'}
        self.client.post(self.get_support_url('author'), data)
        eq_(len(mail.outbox), 1)

        msg = mail.outbox[0]
        eq_(msg.to, ['a@a.com'])
        eq_(msg.from_email, 'regular@mozilla.com')
        assert '<3' in msg.body  # Check no escaping.

    def test_contact_fails(self):
        res = self.client.post(self.get_support_url('author'), {'b': 'c'})
        assert 'text' in res.context['form'].errors

    def test_contact_mozilla(self):
        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        res = self.client.post(self.get_support_url('mozilla'), data)
        self.assertRedirects(res, self.get_support_url('mozilla-sent'), 302)

    def test_contact_mozilla_mails(self):
        data = {'text': 'Lorem ipsum dolor sit amet, <3 consectetur'}
        self.client.post(self.get_support_url('mozilla'), data)
        eq_(len(mail.outbox), 1)

        msg = mail.outbox[0]
        eq_(msg.to, [settings.MARKETPLACE_EMAIL])
        eq_(msg.from_email, 'regular@mozilla.com')
        assert '<3' in msg.body  # Check no escaping.
        assert 'Lorem' in msg.body

    def test_contact_mozilla_fails(self):
        res = self.client.post(self.get_support_url('mozilla'), {'b': 'c'})
        assert 'text' in res.context['form'].errors

    def test_request_inapp(self):
        self.con.update(type=amo.CONTRIB_INAPP)
        res = self.client.post(self.get_support_url('request'))
        eq_(res.status_code, 302)

    def test_refund_remove(self):
        res = self.client.post(self.get_support_url('request'), {'remove': 1})
        eq_(res.status_code, 302)

    def test_refund_remove_passes(self):
        res = self.client.post(self.get_support_url('request'))
        eq_(res.status_code, 302)

    def test_skip_fails(self):
        res = self.client.post(self.get_support_url('reason'))
        self.assertRedirects(res, self.get_support_url('request'))

    def test_request(self):
        raise SkipTest('No refunds at the moment.')
        self.client.post(self.get_support_url('request'), {'remove': 1})
        res = self.client.post(self.get_support_url('reason'),
                               {'text': 'something'})
        self.assertRedirects(res, self.get_support_url('refund-sent'), 302)
        eq_(self.logged(status=amo.LOG.REFUND_REQUESTED).count(), 1)

    def test_no_txnid_request(self):
        self.con.transaction_id = None
        self.con.save()
        self.client.post(self.get_support_url('request'), {'remove': 1})
        res = self.client.post(self.get_support_url('reason'),
                               {'text': 'something'})
        assert 'cannot be applied for yet' in res.cookies['messages'].value
        eq_(len(mail.outbox), 0)
        self.assertRedirects(res, reverse('account.purchases'), 302)

    @mock.patch('apps.stats.models.Contribution.is_refunded')
    def test_already_refunded_request(self, is_refunded):
        is_refunded.return_value = True
        self.client.post(self.get_support_url('request'), {'remove': 1})
        res = self.client.post(self.get_support_url('reason'),
                               {'text': 'something'})
        assert 'refunded' in res.cookies['messages'].value
        eq_(len(mail.outbox), 0)
        self.assertRedirects(res, reverse('account.purchases'), 302)

    @mock.patch('stats.models.Contribution.is_instant_refund')
    def test_request_mails(self, is_instant_refund):
        raise SkipTest('No refunds at the moment.')
        is_instant_refund.return_value = False
        self.app.support_email = 'a@a.com'
        self.app.save()

        reason = 'something <3'
        self.client.post(self.get_support_url('request'), {'remove': 1})
        self.client.post(self.get_support_url('reason'), {'text': reason})
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        eq_(msg.to, ['a@a.com'])
        eq_(msg.from_email, settings.NOBODY_EMAIL)
        assert '<3' in msg.body  # Check no escaping.
        assert '$1.00' in msg.body, 'Missing refund price in %s' % email.body
        assert reason in msg.body, 'Missing refund reason in %s' % email.body

    @mock.patch('stats.models.Contribution.is_instant_refund')
    def test_request_fails(self, is_instant_refund):
        is_instant_refund.return_value = False
        self.app.support_email = 'a@a.com'
        self.app.save()

        self.client.post(self.get_support_url('request'), {'remove': 1})
        res = self.client.post(self.get_support_url('reason'), {})
        eq_(res.status_code, 200)

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('stats.models.Contribution.is_instant_refund')
    @mock.patch('paypal.refund')
    def test_request_instant(self, refund, is_instant_refund, enqueue_refund):
        is_instant_refund.return_value = True
        self.client.post(self.get_support_url('request'), {'remove': 1})
        res = self.client.post(self.get_support_url('reason'), {})
        assert refund.called
        eq_(res.status_code, 302)
        # There should be one instant refund added.
        eq_(enqueue_refund.call_args_list[0][0],
            (amo.REFUND_APPROVED_INSTANT,))
        eq_(self.logged(status=amo.LOG.REFUND_INSTANT).count(), 1)

    @mock.patch('stats.models.Contribution.record_failed_refund')
    @mock.patch('stats.models.Contribution.is_instant_refund')
    @mock.patch('mkt.support.views.paypal')
    def test_request_instant_fails(self, refund, is_instant_refund, record):
        err = []
        def save_err(msg):
            e = PaypalError(msg)
            err.append(e)
            raise e
        refund.refund.side_effect = save_err
        is_instant_refund.return_value = True
        self.client.post(self.get_support_url('request'), {'remove': 1})
        res = self.client.post(self.get_support_url('reason'), {}, follow=True)
        eq_(res.status_code, 200)
        eq_(len(pq(res.content)('.notification-box')), 1)
        eq_(record.call_args[0][0], err[0])
        eq_(record.call_args[0][1].pk, self.user.pk)

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('stats.models.Contribution.is_instant_refund')
    @mock.patch('mkt.support.views.client')
    def test_request_instant_solitude(self, client, is_instant_refund,
                                      enqueue_refund):
        waffle.models.Flag.objects.create(name='solitude-payments',
                                          everyone=True)

        is_instant_refund.return_value = True
        self.client.post(self.get_support_url('request'), {'remove': 1})
        res = self.client.post(self.get_support_url('reason'), {})
        eq_(client.post_refund.call_args[1]['data']['uuid'], 'txn-1')
        eq_(res.status_code, 302)
        # There should be one instant refund added.
        eq_(enqueue_refund.call_args_list[0][0],
            (amo.REFUND_APPROVED_INSTANT,))
        eq_(self.logged(status=amo.LOG.REFUND_INSTANT).count(), 1)
