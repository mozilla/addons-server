import fudge
from fudge.inspector import arg

from requests.exceptions import Timeout

import amo
from mkt.inapp_pay.models import InappConfig
from mkt.purchase import bluevia_tasks as tasks
from stats.models import Contribution

from .test_views import PurchaseTest


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
    @fudge.patch('mkt.purchase.bluevia_tasks.purchase_notify.retry')
    def test_retry(self, fake_req, fake_retry):
        fake_req.expects('post').raises(Timeout())
        fake_retry.expects_call().with_args(self.signed_jwt,
                                            self.contrib.pk)
        self.purchase_notify()
