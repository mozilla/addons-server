from datetime import datetime, timedelta

from django.core import mail
from django.core.cache import cache
from django.conf import settings

from jingo.helpers import datetime as datetime_filter
import mock
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import AddonPremium
from market.models import Price
from stats.models import Contribution
from users.models import UserProfile
import users.notifications as email
from mkt.webapps.models import Installed, Webapp


class PurchaseBase(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        waffle.models.Switch.objects.create(name='allow-refund', active=True)

        self.url = reverse('account.purchases')
        self.client.login(username='regular@mozilla.com', password='password')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')

        self.app, self.con = None, None
        self.apps = {}
        for x in xrange(1, 5):
            name = 't%s' % x
            price = Price.objects.create(price=10 - x)
            app = Webapp.objects.create(name=name, guid=name)
            AddonPremium.objects.create(price=price, addon=app)
            con = Contribution.objects.create(user=self.user,
                addon=app, amount='%s.00' % x, type=amo.CONTRIB_PURCHASE,
                transaction_id='txn-%d' % x)
            con.created = datetime(2011, 11, 1)
            con.save()
            if not self.app and not self.con:
                self.app, self.con = app, con
            self.apps[name] = app

    def get_support_url(self, *args):
        return reverse('users.support', args=[self.con.pk] + list(args))


class TestPurchases(PurchaseBase):

    def make_contribution(self, product, amt, type, day, user=None):
        c = Contribution.objects.create(user=user or self.user,
                                        addon=product, amount=amt, type=type)
        # This needs to be a date in the past for contribution sorting
        # to work, so don't change this - or get scared by this.
        c.created = datetime(2011, 11, day)
        c.save()
        return c

    def test_login_required(self):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertLoginRedirects(r, self.url, 302)

    def test_no_purchases(self):
        Contribution.objects.all().delete()
        Installed.objects.all().delete()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

    def test_purchase_list(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(len(res.context['pager'].object_list), 4)

    def test_purchase_date(self):
        # Some date that's not the same as the contribution.
        self.app.update(created=datetime(2011, 10, 15))
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        node = pq(res.content)('.purchase').eq(0).text()
        ts = datetime_filter(self.con.created)
        assert ts in node, '%s not found' % ts

    def get_order(self, order):
        res = self.client.get(self.url, dict(sort=order))
        return [str(c.name) for c in res.context['pager'].object_list]

    def test_ordering(self):
        eq_(self.get_order('name'), ['t1', 't2', 't3', 't4'])
        eq_(self.get_order('price'), ['t4', 't3', 't2', 't1'])

    def test_ordering_purchased(self):
        # Generate two apps to ensure sure those are also listed.
        for x in xrange(1, 3):
            app = Webapp.objects.create(name='f%s' % x, guid='f%s' % x)
            Installed.objects.create(addon=app, user=self.user)

        for guid, app in self.apps.iteritems():
            purchase = app.addonpurchase_set.get(user=self.user)
            purchase.update(created=datetime.now() + timedelta(days=app.id))

        # Purchase an app on behalf of a different user, which shouldn't
        # affect the ordering of my purchases. Right?
        clouserw = UserProfile.objects.get(email='clouserw@gmail.com')
        self.make_contribution(self.apps['t3'], '1.00', amo.CONTRIB_PURCHASE,
                               5, user=clouserw)
        self.apps['t3'].addonpurchase_set.get(user=clouserw).update(
            created=datetime.now() + timedelta(days=999))

        # Now check the order of my purchased apps.
        default = ['t4', 't3', 't2', 't1', 'f1', 'f2']
        eq_(self.get_order(''), default)
        eq_(self.get_order('purchased'), default)

        # Make another purchase for app `t2`.
        self.apps['t2'].addonpurchase_set.all()[0].update(
            created=datetime.now() + timedelta(days=999))
        cache.clear()
        eq_(self.get_order('purchased'), ['t2', 't4', 't3', 't1', 'f1', 'f2'])

    def get_pq(self):
        r = self.client.get(self.url, dict(sort='name'))
        eq_(r.status_code, 200)
        return pq(r.content)('#purchases')

    def test_price(self):
        assert '$1.00' in self.get_pq()('.purchase').eq(0).text()

    def test_price_locale(self):
        self.url = self.url.replace('/en-US', '/fr')
        assert u'1,00' in self.get_pq()('.purchase').eq(0).text()

    def test_receipt(self):
        res = self.client.get(reverse('users.purchases.receipt',
                                      args=[self.app.pk]))
        eq_([a.pk for a in res.context['pager'].object_list], [self.app.pk])

    def test_receipt_404(self):
        url = reverse('users.purchases.receipt', args=[545])
        eq_(self.client.get(url).status_code, 404)

    def test_receipt_view(self):
        res = self.client.get(reverse('account.purchases.receipt',
                                      args=[self.app.pk]))
        eq_(pq(res.content)('#sorter a').attr('href'),
            reverse('account.purchases'))

    def test_purchases_attribute(self):
        doc = pq(self.client.get(self.url).content)
        ids = list(Webapp.objects.values_list('pk', flat=True).order_by('pk'))
        eq_(doc('body').attr('data-purchases'),
            ','.join([str(i) for i in ids]))

    def test_no_purchases_attribute(self):
        self.user.addonpurchase_set.all().delete()
        doc = pq(self.client.get(self.url).content)
        eq_(doc('body').attr('data-purchases'), '')

    def test_refund_link(self):
        eq_(self.get_pq()('a.request-support').eq(0).attr('href'),
            self.get_support_url())

    def test_free_shows_up(self):
        Contribution.objects.all().delete()
        res = self.client.get(self.url)
        eq_(sorted(a.guid for a in res.context['pager'].object_list),
            ['t1', 't2', 't3', 't4'])

    def test_others_free_dont(self):
        Contribution.objects.all().delete()
        other = UserProfile.objects.get(pk=10482)
        Installed.objects.all()[0].update(user=other)
        res = self.client.get(self.url)
        eq_(len(res.context['pager'].object_list), 3)

    def test_purchase_multiple(self):
        Contribution.objects.create(user=self.user,
            addon=self.app, amount='1.00', type=amo.CONTRIB_PURCHASE)
        eq_(self.get_pq()('.contributions').eq(0)('.purchase').length, 2)

    def test_refunded(self):
        self.make_contribution(self.apps['t1'], '-1.00', amo.CONTRIB_REFUND, 2)
        item = self.get_pq()('.item').eq(0)
        assert item.hasClass('refunded'), (
            "Expected '.item' to have 'refunded' class")
        assert item.find('.refund-notice'), 'Expected refund message'

    def test_repurchased(self):
        app = self.apps['t1']
        c = [
            self.make_contribution(app, '-1.00', amo.CONTRIB_REFUND, 2),
            self.make_contribution(app, '1.00', amo.CONTRIB_PURCHASE, 3)
        ]
        item = self.get_pq()('.item').eq(0)
        assert not item.hasClass('reversed'), (
            "Unexpected 'refunded' class on '.item'")
        assert not item.find('.refund-notice'), 'Unexpected refund message'
        purchases = item.find('.contributions')
        eq_(purchases.find('.request-support').length, 1)
        eq_(purchases.find('li').eq(2).find('.request-support').attr('href'),
            reverse('users.support', args=[c[1].id]))

    def test_rerefunded(self):
        app = self.apps['t1']
        self.make_contribution(app, '-1.00', amo.CONTRIB_REFUND, 2)
        self.make_contribution(app, '1.00', amo.CONTRIB_PURCHASE, 3)
        self.make_contribution(app, '-1.00', amo.CONTRIB_REFUND, 4)
        item = self.get_pq()('.item').eq(0)
        assert item.hasClass('refunded'), (
            "Unexpected 'refunded' class on '.item'")
        assert item.find('.refund-notice'), 'Expected refund message'
        assert not item.find('a.request-support'), (
            "Unexpected 'Request Support' link")

    def test_chargeback(self):
        self.make_contribution(self.apps['t1'], '-1.00',
                               amo.CONTRIB_CHARGEBACK, 2)
        item = self.get_pq()('.item').eq(0)
        assert item.hasClass('reversed'), (
            "Expected '.item' to have 'reversed' class")
        assert not item.find('a.request-support'), (
            "Unexpected 'Request Support' link")


class TestRequestSupport(PurchaseBase):

    def test_support_not_logged_in(self):
        self.client.logout()
        eq_(self.client.get(self.get_support_url()).status_code, 302)

    def test_support_not_mine(self):
        self.client.login(username='admin@mozilla.com', password='password')
        eq_(self.client.get(self.get_support_url()).status_code, 404)

    def test_support_page(self):
        raise SkipTest  # cvan will fix in bug 738854.
        doc = pq(self.client.get(self.get_support_url()).content)
        eq_(doc('section.primary a').attr('href'),
            self.get_support_url('author'))

    def test_support_page_other(self):
        raise SkipTest  # cvan will fix in bug 738854.
        self.app.support_url = 'http://omg.org/yes'
        self.app.save()

        doc = pq(self.client.get(self.get_support_url()).content)
        eq_(doc('section.primary a').attr('href'),
            self.get_support_url('site'))

    def test_support_site(self):
        raise SkipTest  # cvan will fix in bug 738854.
        self.app.support_url = 'http://omg.org/yes'
        self.app.save()

        doc = pq(self.client.get(self.get_support_url('site')).content)
        eq_(doc('section.primary a').attr('href'), self.app.support_url)

    def test_contact(self):
        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        res = self.client.post(self.get_support_url('author'), data)
        eq_(res.status_code, 302)

    def test_contact_mails(self):
        self.app.support_email = 'a@a.com'
        self.app.save()

        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        self.client.post(self.get_support_url('author'), data)
        eq_(len(mail.outbox), 1)

        msg = mail.outbox[0]
        eq_(msg.to, ['a@a.com'])
        eq_(msg.from_email, 'regular@mozilla.com')

    def test_contact_fails(self):
        raise SkipTest  # cvan will fix in bug 738854.
        res = self.client.post(self.get_support_url('author'), {'b': 'c'})
        assert 'text' in res.context['form'].errors

    def test_contact_mozilla(self):
        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        res = self.client.post(self.get_support_url('mozilla'), data)
        eq_(res.status_code, 302)

    def test_contact_mozilla_mails(self):
        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        self.client.post(self.get_support_url('mozilla'), data)
        eq_(len(mail.outbox), 1)

        msg = mail.outbox[0]
        eq_(msg.to, [settings.MARKETPLACE_EMAIL])
        eq_(msg.from_email, 'regular@mozilla.com')
        assert 'Lorem' in msg.body

    def test_contact_mozilla_fails(self):
        raise SkipTest  # cvan will fix in bug 738854.
        res = self.client.post(self.get_support_url('mozilla'), {'b': 'c'})
        assert 'text' in res.context['form'].errors

    def test_refund_remove(self):
        res = self.client.post(self.get_support_url('request'), {'remove': 1})
        eq_(res.status_code, 302)

    def test_refund_remove_passes(self):
        res = self.client.post(self.get_support_url('request'), {})
        eq_(res.status_code, 302)

    def test_skip_fails(self):
        raise SkipTest  # cvan will fix in bug 738854.
        res = self.client.post(self.get_support_url('reason'), {})
        self.assertRedirects(res, self.get_support_url('request'))

    def test_request(self):
        self.client.post(self.get_support_url('request'), {'remove': 1})
        res = self.client.post(self.get_support_url('reason'),
                               {'text': 'something'})
        eq_(res.status_code, 302)

    def test_no_txnid_request(self):
        self.con.transaction_id = None
        self.con.save()
        self.client.post(self.get_support_url('request'), {'remove': 1})
        res = self.client.post(self.get_support_url('reason'),
                               {'text': 'something'})
        assert 'cannot be applied for yet' in res.cookies['messages'].value
        eq_(len(mail.outbox), 0)
        self.assertRedirects(res, reverse('users.purchases'), 302)

    @mock.patch('stats.models.Contribution.is_instant_refund')
    def test_request_mails(self, is_instant_refund):
        is_instant_refund.return_value = False
        self.app.support_email = 'a@a.com'
        self.app.save()

        reason = 'something'
        self.client.post(self.get_support_url('request'), {'remove': 1})
        self.client.post(self.get_support_url('reason'), {'text': reason})
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        eq_(msg.to, ['a@a.com'])
        eq_(msg.from_email, 'nobody@mozilla.org')
        assert '$1.00' in msg.body, 'Missing refund reason in %s' % email.body
        assert reason in msg.body, 'Missing refund reason in %s' % email.body

    @mock.patch('stats.models.Contribution.is_instant_refund')
    def test_request_fails(self, is_instant_refund):
        raise SkipTest  # cvan will fix in bug 738854.
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
