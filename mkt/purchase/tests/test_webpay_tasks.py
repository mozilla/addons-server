import uuid

from django.core import mail

from mock import patch
from nose.tools import eq_, ok_

import amo
from stats.models import Contribution

from mkt.purchase import tasks as tasks

from utils import PurchaseTest


class TestReceiptEmail(PurchaseTest):

    def setUp(self):
        super(TestReceiptEmail, self).setUp()
        self.contrib = Contribution.objects.create(addon_id=self.addon.id,
                                                   amount=self.price.price,
                                                   uuid=str(uuid.uuid4()),
                                                   type=amo.CONTRIB_PURCHASE,
                                                   user=self.user,
                                                   source_locale='en-us')

    def test_send(self):
        tasks.send_purchase_receipt(self.contrib.pk)
        eq_(len(mail.outbox), 1)

    def test_localized_send(self):
        self.contrib.user.lang = 'es'
        self.contrib.user.save()
        tasks.send_purchase_receipt(self.contrib.pk)
        assert 'Precio' in mail.outbox[0].body
        assert 'Algo Algo' in mail.outbox[0].body

    @patch('mkt.purchase.tasks.send_html_mail_jinja')
    def test_data(self, send_mail_jinja):
        with self.settings(SITE_URL='http://f.com'):
            tasks.send_purchase_receipt(self.contrib.pk)

        args = send_mail_jinja.call_args
        data = args[0][3]

        eq_(args[1]['recipient_list'], [self.user.email])
        eq_(data['app_name'], self.addon.name)
        eq_(data['developer_name'], self.addon.current_version.developer_name)
        eq_(data['price'], self.contrib.get_amount_locale('en_US'))
        ok_(data['purchases_url'].startswith('http://f.com'))
