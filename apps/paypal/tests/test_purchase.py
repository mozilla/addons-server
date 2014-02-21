from mock import Mock, patch
from nose import SkipTest
from nose.tools import eq_

from addons.models import Addon
import amo
import amo.tests
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from stats.models import Contribution
from users.models import UserProfile


uuid = '123'

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

sample_ipn = sample_purchase.copy()
sample_ipn['tracking_id'] = uuid
