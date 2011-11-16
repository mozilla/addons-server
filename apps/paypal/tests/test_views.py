# -*- coding: utf-8 -*-
import urllib

from django import http, test
from django.conf import settings
from django.core.cache import cache
from django.core import mail

from mock import patch, Mock
from nose.tools import eq_

import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from stats.models import SubscriptionEvent, Contribution
from users.models import UserProfile


URL_ENCODED = 'application/x-www-form-urlencoded'


class Client(test.Client):
    """Test client that uses form-urlencoded (like browsers)."""

    def post(self, url, data={}, **kw):
        if hasattr(data, 'items'):
            data = urllib.urlencode(data)
            kw['content_type'] = URL_ENCODED
        return super(Client, self).post(url, data, **kw)


@patch('paypal.views.urllib2.urlopen')
class TestPaypal(amo.tests.TestCase):

    def setUp(self):
        self.url = reverse('amo.paypal')
        self.item = 1234567890
        self.client = Client()

    def urlopener(self, status):
        m = Mock()
        m.readline.return_value = status
        return m

    def test_not_verified(self, urlopen):
        urlopen.return_value = self.urlopener('xxx')
        response = self.client.post(self.url, {'foo': 'bar'})
        assert isinstance(response, http.HttpResponseForbidden)

    def test_no_payment_status(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url)
        eq_(response.status_code, 200)

    def test_subscription_event(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url, {'txn_type': 'subscr_xxx'})
        eq_(response.status_code, 200)
        eq_(SubscriptionEvent.objects.count(), 1)

    def test_mail(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        add = Addon.objects.create(enable_thankyou=True,
                                   support_email='a@a.com',
                                   type=amo.ADDON_EXTENSION)
        Contribution.objects.create(addon_id=add.pk,
                                    uuid='123')
        response = self.client.post(self.url, {u'action_type': u'PAY',
                                               u'sender_email': u'a@a.com',
                                               u'status': u'COMPLETED',
                                               u'tracking_id': u'123'})
        eq_(response.status_code, 200)
        eq_(len(mail.outbox), 1)

    def test_get_not_allowed(self, urlopen):
        response = self.client.get(self.url)
        assert isinstance(response, http.HttpResponseNotAllowed)

    def test_mysterious_contribution(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')

        key = "%s%s:%s" % (settings.CACHE_PREFIX, 'contrib', self.item)

        data = {'txn_id': 100,
                'payer_email': 'jbalogh@wherever.com',
                'receiver_email': 'clouserw@gmail.com',
                'mc_gross': '99.99',
                'item_number': self.item,
                'payment_status': 'Completed'}
        response = self.client.post(self.url, data)
        assert isinstance(response, http.HttpResponseServerError)
        eq_(cache.get(key), 1)

        cache.set(key, 10, 1209600)
        response = self.client.post(self.url, data)
        assert isinstance(response, http.HttpResponse)
        eq_(cache.get(key), None)

    def test_query_string_order(self, urlopen):
        urlopen.return_value = self.urlopener('HEY MISTER')
        query = 'x=x&a=a&y=y'
        response = self.client.post(self.url, data=query,
                                    content_type=URL_ENCODED)
        eq_(response.status_code, 403)
        _, path, _ = urlopen.call_args[0]
        eq_(path, 'cmd=_notify-validate&%s' % query)

    def test_any_exception(self, urlopen):
        urlopen.side_effect = Exception()
        response = self.client.post(self.url)
        eq_(response.status_code, 500)
        eq_(response.content, 'Unknown error.')


@patch('paypal.views.urllib2.urlopen')
class TestEmbeddedPaymentsPaypal(amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        self.url = reverse('amo.paypal')
        self.addon = Addon.objects.get(pk=3615)

    def urlopener(self, status):
        m = Mock()
        m.readline.return_value = status
        return m

    def test_success(self, urlopen):
        uuid = 'e76059abcf747f5b4e838bf47822e6b2'
        Contribution.objects.create(uuid=uuid, addon=self.addon)
        data = {'tracking_id': uuid, 'payment_status': 'Completed'}
        urlopen.return_value = self.urlopener('VERIFIED')

        response = self.client.post(self.url, data)
        eq_(response.content, 'Success!')

    def test_wrong_uuid(self, urlopen):
        uuid = 'e76059abcf747f5b4e838bf47822e6b2'
        Contribution.objects.create(uuid=uuid, addon=self.addon)
        data = {'tracking_id': 'sdf', 'payment_status': 'Completed'}
        urlopen.return_value = self.urlopener('VERIFIED')

        response = self.client.post(self.url, data)
        eq_(response.content, 'Contribution not found')

    def _receive_refund_ipn(self, uuid, urlopen):
        """
        Create and post a refund IPN.
        """
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.url, {u'action_type': u'PAY',
                                               u'sender_email': u'a@a.com',
                                               u'status': u'REFUNDED',
                                               u'tracking_id': u'123',
                                               u'mc_gross': u'12.34',
                                               u'mc_currency': u'US',
                                               u'item_number': uuid})
        return response

    def test_refund(self, urlopen):
        """
        Receipt of an IPN for a refund results in a Contribution
        object recording its relation to the original payment.
        """
        uuid = 'e76059abcf747f5b4e838bf47822e6b2'
        user = UserProfile.objects.get(pk=999)
        original = Contribution.objects.create(uuid=uuid, user=user,
                                               addon=self.addon)

        response = self._receive_refund_ipn(uuid, urlopen)
        eq_(response.content, 'Success!')
        refunds = Contribution.objects.filter(related=original)
        eq_(len(refunds), 1)
        eq_(refunds[0].addon, self.addon)
        eq_(refunds[0].user, user)
        eq_(refunds[0].type, amo.CONTRIB_REFUND)

    def test_orphanedRefund(self, urlopen):
        """
        Receipt of an IPN for a refund for a payment we haven't
        recorded results in an error.
        """
        uuid = 'e76059abcf747f5b4e838bf47822e6b2'
        response = self._receive_refund_ipn(uuid, urlopen)
        eq_(response.content, 'Contribution not found')
        refunds = Contribution.objects.filter(type=amo.CONTRIB_REFUND)
        eq_(len(refunds), 0)
