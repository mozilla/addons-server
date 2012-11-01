# -*- coding: utf-8 -*-
from decimal import Decimal
import urllib

from django import http, test
from django.conf import settings
from django.core import mail

from mock import patch, Mock
from nose.tools import eq_
from test_utils import RequestFactory
import waffle

import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from market.models import Price
from stats.models import Contribution
from users.models import UserProfile
from paypal import views, PaypalError
from paypal.decorators import handle_paypal_error


URL_ENCODED = 'application/x-www-form-urlencoded'


class Client(test.Client):
    """Test client that uses form-urlencoded (like browsers)."""

    def post(self, url, data={}, **kw):
        if hasattr(data, 'items'):
            data = urllib.urlencode(data)
            kw['content_type'] = URL_ENCODED
        return super(Client, self).post(url, data, **kw)


# These are taken from the real IPNs paypal returned to us.
# TODO(andym): compress all these down, at this moment they are
# a bit verbose.
sample_refund = {
    'action_type': 'PAY',
    'charset': 'windows-1252',
    'cancel_url': 'http://some.url/cancel',
    'notify_version': 'UNVERSIONED',
    'pay_key': '1234',
    'payment_request_date': 'Mon Nov 21 15:23:02 PST 2011',
    'reason_code': 'Refund',
    'return_url': 'http://some.url/complete',
    'reverse_all_parallel_payments_on_error': 'false',
    'sender_email': 'some.other@gmail.com',
    'status': 'COMPLETED',
    'tracking_id': '5678',
    'transaction[0].amount': 'USD 1.00',
    'transaction[0].id': 'ABC',
    'transaction[0].id_for_sender_txn': 'DEF',
    'transaction[0].is_primary_receiver': 'false',
    'transaction[0].paymentType': 'DIGITALGOODS',
    'transaction[0].pending_reason': 'NONE',
    'transaction[0].receiver': 'some@gmail.com',
    'transaction[0].refund_account_charged': 'some@gmail.com',
    'transaction[0].refund_amount': 'USD 0.01',
    'transaction[0].refund_id': 'XYZ',
    'transaction[0].status': 'Refunded',
    'transaction[0].status_for_sender_txn': 'Refunded',
    'transaction_type': 'Adjustment',
    'verify_sign': 'xyz'
}

sample_chained_refund = {
    'action_type': 'PAY',
    'charset': 'windows-1252',
    'fees_payer': 'SECONDARYONLY',
    'log_default_shipping_address_in_transaction': 'false',
    'memo': 'Purchase of Sinuous-andy-video-test',
    'notify_version': 'UNVERSIONED',
    'pay_key': '1234',
    'payment_request_date': 'Mon Apr 02 12:51:50 PDT 2012',
    'reason_code': 'Refund',
    'reverse_all_parallel_payments_on_error': 'false',
    'sender_email': 'some-1@gmail.com',
    'status': 'COMPLETED',
    'test_ipn': '1',
    'tracking_id': '5678',
    'transaction[0].amount': 'USD 0.99',
    'transaction[0].id': 'ABC',
    'transaction[0].id_for_sender_txn': 'DEF',
    'transaction[0].is_primary_receiver': 'true',
    'transaction[0].paymentType': 'DIGITALGOODS',
    'transaction[0].pending_reason': 'NONE',
    'transaction[0].receiver': 'some-2@gmail.com',
    'transaction[0].status': 'Refunded',
    'transaction[0].status_for_sender_txn': 'Refunded',
    'transaction[1].amount': 'USD 0.30',
    'transaction[1].id': 'ABC',
    'transaction[1].id_for_sender_txn': 'ASD',
    'transaction[1].is_primary_receiver': 'false',
    'transaction[1].paymentType': 'DIGITALGOODS',
    'transaction[1].pending_reason': 'NONE',
    'transaction[1].receiver': 'some-3@gmail.com',
    'transaction[1].refund_account_charged': 'some-3@gmail.com',
    'transaction[1].refund_amount': 'USD 0.30',
    'transaction[1].refund_id': 'XYX',
    'transaction[1].status': 'Refunded',
    'transaction[1].status_for_sender_txn': 'Refunded',
    'transaction_type': 'Adjustment',
    'verify_sign': 'xyz',
}

sample_purchase = {
    'action_type': 'PAY',
    'cancel_url': 'http://some.url/cancel',
    'charset': 'windows-1252',
    'fees_payer': 'EACHRECEIVER',
    'ipn_notification_url': 'http://some.url.ipn',
    'log_default_shipping_address_in_transaction': 'false',
    'memo': 'Purchase of Sinuous',
    'notify_version': 'UNVERSIONED',
    'pay_key': '1234',
    'payment_request_date': 'Mon Nov 21 22:30:48 PST 2011',
    'return_url': 'http://some.url/return',
    'reverse_all_parallel_payments_on_error': 'false',
    'sender_email': 'some.other@gmail.com',
    'status': 'COMPLETED',
    'test_ipn': '1',
    'tracking_id': '5678',
    'transaction[0].amount': 'USD 0.01',
    'transaction[0].id': 'ABC',
    'transaction[0].id_for_sender_txn': 'DEF',
    'transaction[0].is_primary_receiver': 'false',
    'transaction[0].paymentType': 'DIGITALGOODS',
    'transaction[0].pending_reason': 'NONE',
    'transaction[0].receiver': 'some@gmail.com',
    'transaction[0].status': 'Completed',
    'transaction[0].status_for_sender_txn': 'Completed',
    'transaction_type': 'Adaptive Payment PAY',
    'verify_sign': 'zyx'
}

sample_contribution = {
    'action_type': 'PAY',
    'cancel_url': 'http://some.url/cancel',
    'charset': 'windows-1252',
    'fees_payer': 'EACHRECEIVER',
    'ipn_notification_url': 'http://some.url.ipn',
    'log_default_shipping_address_in_transaction': 'false',
    'memo': 'Contribution for cool addon',
    'notify_version': 'UNVERSIONED',
    'pay_key': '1235',
    'payment_request_date': 'Mon Nov 21 23:20:00 PST 2011',
    'return_url': 'http://some.url/return',
    'reverse_all_parallel_payments_on_error': 'false',
    'sender_email': 'some.other@gmail.com',
    'status': 'COMPLETED',
    'test_ipn': '1',
    'tracking_id': '6789',
    'transaction[0].amount': 'USD 1.00',
    'transaction[0].id': 'yy',
    'transaction[0].id_for_sender_txn': 'xx',
    'transaction[0].is_primary_receiver': 'false',
    'transaction[0].paymentType': 'DIGITALGOODS',
    'transaction[0].pending_reason': 'NONE',
    'transaction[0].receiver': 'some.other@gmail.com',
    'transaction[0].status': 'Completed',
    'transaction[0].status_for_sender_txn': 'Completed',
    'transaction_type': 'Adaptive Payment PAY',
    'verify_sign': 'ZZ'
}

sample_reversal = sample_refund.copy()
sample_reversal['transaction[0].status'] = 'reversal'


class PaypalTest(amo.tests.TestCase):

    def setUp(self):
        self.url = reverse('amo.paypal')
        self.item = 1234567890
        self.client = Client()

    def urlopener(self, status):
        m = Mock()
        m.text = status
        return m


@patch('paypal.views.client.post_ipn')
class TestPaypalSolitude(PaypalTest):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        waffle.models.Flag.objects.create(name='solitude-payments',
                                          everyone=True)
        self.addon = Addon.objects.get(pk=3615)
        self.url = reverse('amo.paypal')
        self.user = UserProfile.objects.get(pk=999)

    def test_ignore(self, post_ipn):
        post_ipn.return_value = {'status': 'IGNORED'}
        res = self.client.post(self.url, {})
        eq_(res.content, 'Ignored')

    def test_payment(self, post_ipn):
        Contribution.objects.create(uuid=sample_purchase['tracking_id'],
                                    addon=self.addon)
        post_ipn.return_value = {'action': 'PAYMENT', 'status': 'OK',
                                 'uuid': sample_purchase['tracking_id']}
        res = self.client.post(self.url, {})
        eq_(res.content, 'Success!')

    def test_refund(self, post_ipn):
        Contribution.objects.create(addon=self.addon, uuid=None,
                transaction_id=sample_purchase['tracking_id'], user=self.user)
        post_ipn.return_value = {'action': 'REFUND', 'amount': 'USD 1.00',
                'status': 'OK', 'uuid': sample_purchase['tracking_id']}
        res = self.client.post(self.url, {})
        eq_(res.content, 'Success!')

    def test_chargeback(self, post_ipn):
        Contribution.objects.create(addon=self.addon, uuid=None,
                transaction_id=sample_purchase['tracking_id'], user=self.user)
        post_ipn.return_value = {'action': 'REVERSAL', 'amount': 'USD 1.00',
                'status': 'OK', 'uuid': sample_purchase['tracking_id']}
        res = self.client.post(self.url, {})
        eq_(res.content, 'Success!')


@patch('paypal.views.requests.post')
class TestPaypal(PaypalTest):

    def test_not_verified(self, urlopen):
        urlopen.return_value = self.urlopener('xxx')
        response = self.client.post(self.url, {'foo': 'bar'})
        assert isinstance(response, http.HttpResponseForbidden)

    def test_no_payment_status(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url)
        eq_(response.status_code, 200)

    def test_mail(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        add = Addon.objects.create(enable_thankyou=True,
                                   support_email='a@a.com',
                                   type=amo.ADDON_EXTENSION)
        Contribution.objects.create(addon_id=add.pk,
                                    uuid=sample_contribution['tracking_id'])
        response = self.client.post(self.url, sample_contribution)
        eq_(response.status_code, 200)
        eq_(len(mail.outbox), 1)

    def test_get_not_allowed(self, urlopen):
        response = self.client.get(self.url)
        assert isinstance(response, http.HttpResponseNotAllowed)

    def test_mysterious_contribution(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url, sample_purchase)
        eq_(response.content, 'Transaction not found; skipping.')

    def test_query_string_order(self, urlopen):
        urlopen.return_value = self.urlopener('HEY MISTER')
        query = 'x=x&a=a&y=y'
        response = self.client.post(self.url, data=query,
                                    content_type=URL_ENCODED)
        eq_(response.status_code, 403)
        _, path = urlopen.call_args[0]
        eq_(path, 'cmd=_notify-validate&%s' % query)

    @patch.object(settings, 'IN_TEST_SUITE', False)
    def test_any_exception(self, urlopen):
        urlopen.side_effect = Exception()
        response = self.client.post(self.url)
        eq_(response.status_code, 500)
        eq_(response.content, 'Unknown error.')

    def test_no_status(self, urlopen):
        # An IPN with status_for_sender_txn: Pending, will not have a status.
        urlopen.return_value = self.urlopener('VERIFIED')

        ipn = sample_contribution.copy()
        del ipn['transaction[0].status']

        response = self.client.post(self.url, ipn)
        eq_(response.status_code, 200)
        eq_(response.content, 'Ignoring %s' % ipn['tracking_id'])

    def test_wrong_status(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')

        ipn = sample_contribution.copy()
        ipn['transaction[0].status'] = 'blah!'

        response = self.client.post(self.url, ipn)
        eq_(response.status_code, 200)
        eq_(response.content, 'Ignoring %s' % ipn['tracking_id'])

    def test_duplicate_complete(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        add = Addon.objects.create(type=amo.ADDON_EXTENSION)
        con = Contribution.objects.create(addon_id=add.pk,
                         transaction_id=sample_contribution['tracking_id'])

        for type_ in [amo.CONTRIB_VOLUNTARY, amo.CONTRIB_PURCHASE]:
            con.update(type=type_)
            response = self.client.post(self.url, sample_contribution)
            eq_(response.status_code, 200)
            eq_(response.content, 'Transaction already processed')


@patch('paypal.views.requests.post')
class TestEmbeddedPaymentsPaypal(amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615', 'market/prices']
    uuid = 'e76059abcf747f5b4e838bf47822e6b2'

    def setUp(self):
        self.url = reverse('amo.paypal')
        self.addon = Addon.objects.get(pk=3615)

    def urlopener(self, status):
        m = Mock()
        m.text = status
        return m

    def test_parse_post(self, urlopen):
        junk, transactions = views._parse(sample_refund)
        eq_(transactions['0']['status'], 'Refunded')

    def test_parse_currency(self, urlopen):
        res = views._parse_currency(sample_refund['transaction[0].amount'])
        eq_(res['amount'], Decimal('1.00'))
        eq_(res['currency'], 'USD')

    def test_parse_currency_solitude(self, urlopen):
        res = views._parse_currency({'amount': '1.00', 'currency': 'USD'})
        eq_(res['amount'], Decimal('1.00'))

    def test_success(self, urlopen):
        Contribution.objects.create(uuid=sample_purchase['tracking_id'],
                                    addon=self.addon)
        urlopen.return_value = self.urlopener('VERIFIED')

        response = self.client.post(self.url, sample_purchase)
        eq_(response.content, 'Success!')

    def test_wrong_uuid(self, urlopen):
        Contribution.objects.create(uuid=sample_purchase['tracking_id'] + 'x',
                                    addon=self.addon)
        urlopen.return_value = self.urlopener('VERIFIED')

        response = self.client.post(self.url, sample_purchase)
        eq_(response.content, 'Transaction not found; skipping.')

    def _receive_ipn(self, urlopen, data):
        """
        Create and post an IPN.
        """
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url, data)
        return response

    def _refund(self, urlopen, data=sample_refund):
        """
        Receipt of an IPN for a refund results in a Contribution
        object recording its relation to the original payment.
        """
        user = UserProfile.objects.get(pk=999)
        # The original transaction will have no uuid and
        # a transaction id that will map the tracking_id sent by paypal.
        original = Contribution.objects.create(
                        uuid=None, user=user, addon=self.addon,
                        transaction_id=data['tracking_id'],
                        price_tier=Price.objects.get(price=Decimal('.99')))

        response = self._receive_ipn(urlopen, data)
        eq_(response.content, 'Success!')
        return original

    def test_two_contributions(self, urlopen):
        self._refund(urlopen)
        eq_(Contribution.objects.count(), 2)

    def test_original_has_related(self, urlopen):
        original = self._refund(urlopen)
        refunds = Contribution.objects.filter(related=original)
        eq_(len(refunds), 1)
        eq_(refunds[0].addon, self.addon)
        eq_(refunds[0].user, original.user)
        eq_(refunds[0].type, amo.CONTRIB_REFUND)
        eq_(refunds[0].amount, Decimal('-1.00'))

    def test_refund_twice(self, urlopen):
        self._refund(urlopen)
        response = self._receive_ipn(urlopen, sample_refund)
        eq_(response.content, 'Transaction already processed')

    def test_orphaned_refund(self, urlopen):
        """
        Receipt of an IPN for a refund for a payment we haven't
        recorded results in an error.
        """
        response = self._receive_ipn(urlopen, sample_refund)
        eq_(response.content, 'Transaction not found; skipping.')
        refunds = Contribution.objects.filter(type=amo.CONTRIB_REFUND)
        eq_(len(refunds), 0)

    def test_refund_amount(self, urlopen):
        self._refund(urlopen, sample_chained_refund)
        eq_(Contribution.objects.all()[1].amount, Decimal('-0.99'))

    def test_refund_price_tier_usd(self, urlopen):
        # Store refund values before changing it.
        amount = sample_refund['transaction[0].amount']
        refund_amount = sample_refund['transaction[0].refund_amount']

        sample_refund['transaction[0].amount'] = 'USD 0.99'
        sample_refund['transaction[0].refund_amount'] = 'USD 0.99'
        self._refund(urlopen, sample_refund)
        eq_(Contribution.objects.all()[1].price_tier.id, 1)

        # Restore refund values.
        sample_refund['transaction[0].amount'] = amount
        sample_refund['transaction[0].refund_amount'] = refund_amount

    def test_refund_price_tier_non_usd(self, urlopen):
        # Store refund values before changing it.
        amount = sample_refund['transaction[0].amount']
        refund_amount = sample_refund['transaction[0].refund_amount']

        sample_refund['transaction[0].amount'] = 'EUR 5.01'
        sample_refund['transaction[0].refund_amount'] = 'EUR 5.01'
        self._refund(urlopen, sample_refund)
        eq_(Contribution.objects.all()[1].price_tier.id, 1)

        sample_refund['transaction[0].amount'] = amount
        sample_refund['transaction[0].refund_amount'] = refund_amount

    def reversal(self, urlopen):
        user = UserProfile.objects.get(pk=999)
        Contribution.objects.create(
                transaction_id=sample_reversal['tracking_id'],
                user=user, addon=self.addon)
        response = self._receive_ipn(urlopen, sample_reversal)
        eq_(response.content, 'Success!')

    def test_chargeback(self, urlopen):
        self.reversal(urlopen)
        eq_(Contribution.objects.all()[1].type, amo.CONTRIB_CHARGEBACK)

    def test_chargeback_twice(self, urlopen):
        self.reversal(urlopen)
        response = self._receive_ipn(urlopen, sample_reversal)
        eq_(response.content, 'Transaction already processed')

    def test_email(self, urlopen):
        self.reversal(urlopen)
        eq_(len(mail.outbox), 1)


class TestDecorators(amo.tests.TestCase):

    def setUp(self):
        self.func = Mock()
        self.get_request('/')

    def get_request(self, url):
        self.request = RequestFactory().get(url)

    @patch('jingo.render')
    def test_caught(self, render):
        self.func.side_effect = PaypalError
        view = handle_paypal_error(self.func)
        view(self.request)
        eq_(render.call_args[1]['status'], 500)
        eq_(render.call_args[0][1], 'site/500_paypal.html')

    def test_not_caught(self):
        self.func.side_effect = ZeroDivisionError
        view = handle_paypal_error(self.func)
        self.assertRaises(ZeroDivisionError, view, self.request)

    @patch('jingo.render')
    def test_submission(self, render):
        self.get_request('/?dest=submission')
        self.func.side_effect = PaypalError
        view = handle_paypal_error(self.func)
        addon = Addon.objects.create(type=amo.ADDON_WEBAPP)
        view(self.request, addon=addon)
        eq_(render.call_args[0][2]['submission'], True)
        eq_(render.call_args[0][2]['addon'], addon)
