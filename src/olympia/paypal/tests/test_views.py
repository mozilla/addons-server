# -*- coding: utf-8 -*-
import urllib

from django import http, test
from django.conf import settings
from django.core import mail

from mock import Mock, patch

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse
from olympia.stats.models import Contribution


URL_ENCODED = 'application/x-www-form-urlencoded'


class Client(test.Client):
    """Test client that uses form-urlencoded (like browsers)."""

    def post(self, url, data=None, **kw):
        if data is None:
            data = {}
        if hasattr(data, 'items'):
            data = urllib.urlencode(data)
            kw['content_type'] = URL_ENCODED
        return super(Client, self).post(url, data, **kw)


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


class PaypalTest(TestCase):

    def setUp(self):
        super(PaypalTest, self).setUp()
        self.url = reverse('amo.paypal')
        self.item = 1234567890
        self.client = Client()

    def urlopener(self, status):
        m = Mock()
        m.text = status
        return m


@patch('olympia.paypal.views.requests.post')
class TestPaypal(PaypalTest):
    fixtures = ['base/users']

    def test_not_verified(self, urlopen):
        urlopen.return_value = self.urlopener('xxx')
        response = self.client.post(self.url, {'foo': 'bar'})
        assert isinstance(response, http.HttpResponseForbidden)

    def test_no_payment_status(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url)
        assert response.status_code == 200

    def test_mail(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        add = Addon.objects.create(enable_thankyou=True,
                                   support_email='a@a.com',
                                   type=amo.ADDON_EXTENSION)
        Contribution.objects.create(addon_id=add.pk,
                                    uuid=sample_contribution['tracking_id'])
        response = self.client.post(self.url, sample_contribution)
        assert response.status_code == 200
        assert len(mail.outbox) == 1

    def test_get_not_allowed(self, urlopen):
        response = self.client.get(self.url)
        assert isinstance(response, http.HttpResponseNotAllowed)

    def test_mysterious_contribution(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url, sample_contribution)
        assert response.content == 'Transaction not found; skipping.'

    def test_query_string_order(self, urlopen):
        urlopen.return_value = self.urlopener('HEY MISTER')
        query = 'x=x&a=a&y=y'
        response = self.client.post(self.url, data=query,
                                    content_type=URL_ENCODED)
        assert response.status_code == 403
        _, path = urlopen.call_args[0]
        assert path == 'cmd=_notify-validate&%s' % query

    @patch.object(settings, 'IN_TEST_SUITE', False)
    def test_any_exception(self, urlopen):
        urlopen.side_effect = Exception()
        response = self.client.post(self.url)
        assert response.status_code == 500
        assert response.content == 'Unknown error.'

    def test_no_status(self, urlopen):
        # An IPN with status_for_sender_txn: Pending, will not have a status.
        urlopen.return_value = self.urlopener('VERIFIED')

        ipn = sample_contribution.copy()
        del ipn['transaction[0].status']

        response = self.client.post(self.url, ipn)
        assert response.status_code == 200
        assert response.content == 'Ignoring %s' % ipn['tracking_id']

    def test_wrong_status(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')

        ipn = sample_contribution.copy()
        ipn['transaction[0].status'] = 'blah!'

        response = self.client.post(self.url, ipn)
        assert response.status_code == 200
        assert response.content == 'Ignoring %s' % ipn['tracking_id']

    def test_duplicate_complete(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        add = Addon.objects.create(type=amo.ADDON_EXTENSION)
        Contribution.objects.create(
            addon_id=add.pk, transaction_id=sample_contribution['tracking_id'])

        response = self.client.post(self.url, sample_contribution)
        assert response.status_code == 200
        assert response.content == 'Transaction already processed'
