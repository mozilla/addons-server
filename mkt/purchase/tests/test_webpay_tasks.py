import uuid

from django.core import mail

import fudge
from fudge.inspector import arg
from mock import patch
from nose.tools import eq_, ok_
from requests.exceptions import Timeout

import amo
from stats.models import Contribution

from mkt.inapp_pay.models import InappConfig
from mkt.purchase import webpay_tasks as tasks

from utils import PurchaseTest


class TestNotify(PurchaseTest):

    def setUp(self):
        super(TestNotify, self).setUp()
        uuid_ = '<returned from prepare-pay>'
        self.contrib = Contribution.objects.create(addon_id=self.addon.id,
                                                   amount=self.price.price,
                                                   uuid=uuid_,
                                                   type=amo.CONTRIB_PURCHASE,
                                                   user=self.user)
        self.domain = 'somenonexistantappdomain.com'
        self.addon.update(app_domain='https://' + self.domain)
        self.postback = '/postback'
        self.chargeback = '/chargeback'
        self.cfg = InappConfig.objects.create(addon=self.addon,
                                              status=amo.INAPP_STATUS_ACTIVE,
                                              postback_url=self.postback,
                                              chargeback_url=self.chargeback)
        self.signed_jwt = '<signed by solitude>'
        self.purchase_url = 'https://%s%s' % (self.domain, self.postback)

    def purchase_notify(self):
        tasks.purchase_notify(self.signed_jwt, self.contrib.pk)

    @fudge.patch('mkt.inapp_pay.utils.requests')
    def test_postback(self, fake_req):
        (fake_req.expects('post').with_args(self.purchase_url,
                                            self.signed_jwt,
                                            timeout=arg.any())
                                 .returns_fake()
                                 .has_attr(text=str(self.contrib.pk))
                                 .expects('raise_for_status'))
        self.purchase_notify()

    @fudge.patch('mkt.inapp_pay.utils.requests')
    def test_no_postback_when_not_configured(self, fake_req):
        InappConfig.objects.all().delete()
        self.purchase_notify()

    @fudge.patch('mkt.inapp_pay.utils.requests')
    @fudge.patch('mkt.purchase.webpay_tasks.purchase_notify.retry')
    def test_retry(self, fake_req, fake_retry):
        fake_req.expects('post').raises(Timeout())
        fake_retry.expects_call().with_args(self.signed_jwt,
                                            self.contrib.pk)
        self.purchase_notify()


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

    @patch('mkt.purchase.webpay_tasks.send_html_mail_jinja')
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
