from datetime import datetime, timedelta

from django.core import mail
from django.core.cache import cache
from django.forms.models import model_to_dict

import mock
from jingo.helpers import datetime as datetime_filter
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import AddonPremium
from market.models import PreApprovalUser, Price
from mkt.developers.models import ActivityLog
import paypal
from stats.models import Contribution
from users.models import UserNotification, UserProfile
import users.notifications as email
from mkt.webapps.models import Installed, Webapp


class TestAccountSettings(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        self.user = self.get_user()
        self.client.login(username=self.user.email, password='foo')
        self.url = reverse('account.settings')
        self.data = {'username': 'jbalogh', 'email': 'jbalogh@mozilla.com',
                     'oldpassword': 'foo', 'password': 'longenough',
                     'password2': 'longenough', 'bio': 'boop'}
        self.extra_data = {'homepage': 'http://omg.org/',
                           'occupation': 'bro', 'location': 'desk 42',
                           'display_name': 'Fligtar Scott'}
        self.data.update(self.extra_data)

    def get_user(self):
        return UserProfile.objects.get(username='jbalogh')

    def test_success(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assertRedirects(r, self.url)
        doc = pq(r.content)

        # Check that the values got updated appropriately.
        user = self.get_user()
        for field, expected in self.extra_data.iteritems():
            eq_(unicode(getattr(user, field)), expected)
            eq_(doc('#id_' + field).val(), expected)

    def test_no_password_changes(self):
        self.client.post(self.url, self.data)
        eq_(self.user.userlog_set
                .filter(activity_log__action=amo.LOG.CHANGE_PASSWORD.id)
                .count(), 0)

    def test_email_cant_change(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf'}
        r = self.client.post(self.url, data)
        self.assertRedirects(r, self.url)
        eq_(len(mail.outbox), 0)
        eq_(self.get_user().email, self.data['email'],
            'Email address should not have changed')

    def test_edit_bio(self):
        eq_(self.get_user().bio, None)

        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'bio': 'xxx unst unst'}

        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, data['bio'])
        eq_(unicode(self.get_user().bio), data['bio'])

        data['bio'] = 'yyy unst unst'
        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, data['bio'])
        eq_(unicode(self.get_user().bio), data['bio'])

    def check_default_choices(self, choices, checked=[]):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('input[name=notifications]:checkbox').length, len(choices))
        for id, label in choices:
            box = doc('input[name=notifications][value=%s]' % id)
            if id in checked:
                eq_(box.filter(':checked').length, 1)
            else:
                eq_(box.length, 1)
            parent = box.parent('label')
            eq_(parent.remove('.req').text(), label)

    def post_notifications(self, choices):
        self.check_default_choices(choices=choices, checked=choices)

        self.data['notifications'] = []
        r = self.client.post(self.url, self.data)
        self.assertRedirects(r, self.url)

        eq_(UserNotification.objects.count(), len(email.APP_NOTIFICATIONS))
        eq_(UserNotification.objects.filter(enabled=True).count(),
            len(filter(lambda x: x.mandatory, email.APP_NOTIFICATIONS)))
        self.check_default_choices(choices=choices, checked=[])

    def test_edit_notifications(self):
        # Make jbalogh a developer.
        self.user.update(read_dev_agreement=True)

        self.check_default_choices(choices=email.APP_NOTIFICATIONS_CHOICES,
            checked=[email.individual_contact.id])

        self.data['notifications'] = [email.app_individual_contact.id,
                                      email.app_surveys.id]
        r = self.client.post(self.url, self.data)
        self.assertRedirects(r, self.url)

        mandatory = [n.id for n in email.APP_NOTIFICATIONS if n.mandatory]
        total = len(set(self.data['notifications'] + mandatory))
        eq_(UserNotification.objects.count(), len(email.APP_NOTIFICATIONS))
        eq_(UserNotification.objects.filter(enabled=True).count(), total)

        doc = pq(self.client.get(self.url).content)
        eq_(doc('input[name=notifications]:checked').length, total)

    def test_edit_all_notifications(self):
        self.user.update(read_dev_agreement=True)
        self.post_notifications(email.APP_NOTIFICATIONS_CHOICES)

    def test_edit_non_dev_notifications(self):
        self.post_notifications(email.APP_NOTIFICATIONS_CHOICES_NOT_DEV)

    def test_edit_non_dev_notifications_error(self):
        # jbalogh isn't a developer so he can't set developer notifications.
        self.data['notifications'] = [email.app_surveys.id]
        r = self.client.post(self.url, self.data)
        assert r.context['form'].errors['notifications']


class TestAdminAccountSettings(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.regular = self.get_user()
        self.url = reverse('users.admin_edit', args=[self.regular.pk])

    def get_data(self, **kw):
        data = model_to_dict(self.regular)
        data['admin_log'] = 'test'
        for key in ['password', 'resetcode_expires']:
            del data[key]
        data.update(kw)
        return data

    def get_user(self):
        # Using pk so that we can still get the user after anonymize.
        return UserProfile.objects.get(pk=999)

    def test_get(self):
        eq_(self.client.get(self.url).status_code, 200)

    def test_forbidden(self):
        self.client.logout()
        self.client.login(username='editor@mozilla.com', password='password')
        eq_(self.client.get(self.url).status_code, 403)

    def test_forbidden_anon(self):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertLoginRedirects(r, self.url)

    def test_anonymize(self):
        r = self.client.post(self.url, self.get_data(anonymize=True))
        self.assertRedirects(r, reverse('zadmin.index'))
        eq_(self.get_user().password, 'sha512$Anonymous$Password')

    def test_anonymize_fails_with_other_changed_fields(self):
        # We don't let an admin change a field whilst anonymizing.
        data = self.get_data(anonymize=True, display_name='something@else.com')
        r = self.client.post(self.url, data)
        eq_(r.status_code, 200)
        eq_(self.get_user().password, self.regular.password)  # Hasn't changed.

    def test_admin_logs_edit(self):
        self.client.post(self.url, self.get_data(email='something@else.com'))
        r = ActivityLog.objects.filter(action=amo.LOG.ADMIN_USER_EDITED.id)
        eq_(r.count(), 1)
        assert self.get_data()['admin_log'] in r[0]._arguments

    def test_admin_logs_anonymize(self):
        self.client.post(self.url, self.get_data(anonymize=True))
        r = (ActivityLog.objects
                          .filter(action=amo.LOG.ADMIN_USER_ANONYMIZED.id))
        eq_(r.count(), 1)
        assert self.get_data()['admin_log'] in r[0]._arguments

    def test_admin_no_password(self):
        data = self.get_data(password='pass1234', password2='pass1234',
                             oldpassword='password')
        self.client.post(self.url, data)
        logs = ActivityLog.objects.filter
        eq_(logs(action=amo.LOG.CHANGE_PASSWORD.id).count(), 0)
        r = logs(action=amo.LOG.ADMIN_USER_EDITED.id)
        eq_(r.count(), 1)
        eq_(r[0].details['password'][0], u'****')


class TestPreapproval(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.user = UserProfile.objects.get(pk=999)
        assert self.client.login(username=self.user.email, password='password')

    def get_url(self, status=None):
        return reverse('account.payment', args=[status] if status else [])

    def test_preapproval_denied(self):
        self.client.logout()
        eq_(self.client.get(self.get_url()).status_code, 302)

    def test_preapproval_allowed(self):
        eq_(self.client.get(self.get_url()).status_code, 200)

    def test_preapproval_setup(self):
        doc = pq(self.client.get(self.get_url()).content)
        eq_(doc('#preapproval').attr('action'),
            reverse('account.payment.preapproval'))

    @mock.patch('paypal.get_preapproval_key')
    def test_fake_preapproval(self, get_preapproval_key):
        get_preapproval_key.return_value = {'preapprovalKey': 'xyz'}
        res = self.client.post(reverse('account.payment.preapproval'))
        ssn = self.client.session['setup-preapproval']
        eq_(ssn['key'], 'xyz')
        # Checking it's in the future at least 353 just so this test will work
        # on leap years at 11:59pm.
        assert (ssn['expiry'] - datetime.today()).days > 353
        eq_(res['Location'], paypal.get_preapproval_url('xyz'))

    def test_preapproval_complete(self):
        ssn = self.client.session
        ssn['setup-preapproval'] = {'key': 'xyz'}
        ssn.save()
        res = self.client.post(self.get_url('complete'))
        eq_(res.status_code, 200)
        eq_(self.user.preapprovaluser.paypal_key, 'xyz')
        # Check that re-loading doesn't error.
        res = self.client.post(self.get_url('complete'))
        eq_(res.status_code, 200)

    def test_preapproval_cancel(self):
        PreApprovalUser.objects.create(user=self.user, paypal_key='xyz')
        res = self.client.post(self.get_url('cancel'))
        eq_(res.status_code, 200)
        eq_(self.user.preapprovaluser.paypal_key, 'xyz')
        eq_(pq(res.content)('#preapproval').attr('action'),
            self.get_url('remove'))

    def test_preapproval_remove(self):
        PreApprovalUser.objects.create(user=self.user, paypal_key='xyz')
        res = self.client.post(self.get_url('remove'))
        eq_(res.status_code, 200)
        eq_(self.user.preapprovaluser.paypal_key, '')
        eq_(pq(res.content)('#preapproval').attr('action'),
            reverse('account.payment.preapproval'))


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
        return reverse('support', args=[self.con.pk] + list(args))


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
        res = self.client.get(reverse('account.purchases.receipt',
                                      args=[self.app.pk]))
        eq_([a.pk for a in res.context['pager'].object_list], [self.app.pk])

    def test_receipt_404(self):
        url = reverse('account.purchases.receipt', args=[545])
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
            reverse('support', args=[c[1].id]))

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
