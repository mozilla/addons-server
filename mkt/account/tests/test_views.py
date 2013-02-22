from datetime import datetime, timedelta

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.forms.models import model_to_dict

import mock
from jingo.helpers import datetime as datetime_filter
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

from access.models import Group, GroupUser
import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import AddonPremium, AddonUser
from devhub.models import ActivityLog
from market.models import PreApprovalUser, Price, PriceCurrency
import paypal
from reviews.models import Review
from stats.models import Contribution
from users.models import UserNotification, UserProfile
from versions.models import Version
import users.notifications as email

from mkt.site.fixtures import fixture
from mkt.webapps.models import Installed, Webapp


class TestAccountDelete(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.user = self.get_user()
        self.url = reverse('account.delete')
        assert self.client.login(username=self.user.email, password='password')

    def get_user(self):
        return UserProfile.objects.get(id=999)

    def test_anonymous(self):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertLoginRedirects(r, self.url)

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_success(self):
        r = self.client.post(self.url, {'confirm': True}, follow=True)
        self.assertRedirects(r, reverse('users.login'))
        user = self.get_user()
        eq_(user.deleted, True)
        eq_(user.email, None)

    def test_fail(self):
        r = self.client.post(self.url, {'submit': True}, follow=True)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'confirm', 'This field is required.')
        eq_(pq(r.content)('input[name=confirm]').siblings('.errorlist').length,
            1, 'Expected an error message to be shown')
        user = self.get_user()
        eq_(user.deleted, False, 'User should not have been deleted')
        eq_(user.email, self.user.email, 'Email should not have changed')


class TestAccountSettings(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        self.user = self.get_user()
        assert self.client.login(username=self.user.email, password='foo')
        self.url = reverse('account.settings')
        self.data = {'username': 'jbalogh', 'email': 'jbalogh@mozilla.com',
                     'oldpassword': 'foo', 'password': 'longenough',
                     'password2': 'longenough', 'bio': 'boop',
                     'lang': 'fr', 'region': 'br'}
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
        eq_(ActivityLog.objects.filter(action=amo.LOG.USER_EDITED.id)
                               .count(), 1)
        # Check that the values got updated appropriately.
        # TODO: Add back when settings is more complete.
        # user = self.get_user()
        # for field, expected in self.extra_data.iteritems():
        #     eq_(unicode(getattr(user, field)), expected)
        #     eq_(doc('#id_' + field).val(), expected)

        eq_(doc('#id_display_name').val(), 'Fligtar Scott')
        eq_(doc('#language option[selected]').attr('value'), 'fr')
        eq_(doc('#region option[selected]').attr('value'), 'br')

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
        # We're not doing user profiles right now.
        raise SkipTest
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

    def check_default_choices(self, choices, checked=None):
        checked = checked or []
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
        # We don't have notification settings right now
        raise SkipTest
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
        # We don't have notification settings right now
        raise SkipTest
        self.user.update(read_dev_agreement=datetime.now())
        self.post_notifications(email.APP_NOTIFICATIONS_CHOICES)

    def test_edit_non_dev_notifications(self):
        # We don't have notification settings right now
        raise SkipTest
        self.post_notifications(email.APP_NOTIFICATIONS_CHOICES_NOT_DEV)

    def test_edit_non_dev_notifications_error(self):
        # We don't have notification settings right now
        raise SkipTest
        # jbalogh isn't a developer so he can't set developer notifications.
        self.data['notifications'] = [email.app_surveys.id]
        r = self.client.post(self.url, self.data)
        assert r.context['form'].errors['notifications']

    def test_delete_photo_not(self):
        self.client.logout()
        self.assertLoginRequired(self.client
                                     .post(reverse('account.delete_photo')))

    @mock.patch('mkt.account.views.delete_photo_task')
    def test_delete_photo(self, delete_photo_task):
        res = self.client.post(reverse('account.delete_photo'))
        log = ActivityLog.objects.filter(user=self.user,
                                         action=amo.LOG.USER_EDITED.id)
        eq_(res.status_code, 200)
        eq_(log.count(), 1)
        eq_(self.get_user().picture_type, '')
        assert delete_photo_task.delay.called

    def test_lang_region_selector(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(r.status_code, 200)
        eq_(doc('#language option[selected]').attr('value'), 'en-us')
        eq_(doc('#region option[selected]').attr('value'), 'us')


class TestAdminAccountSettings(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
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
        # Admin settings don't exist for now.
        raise SkipTest
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
        # Admin settings don't exist for now.
        raise SkipTest
        r = self.client.post(self.url, self.get_data(anonymize=True))
        self.assertRedirects(r, reverse('zadmin.index'))
        eq_(self.get_user().password, 'sha512$Anonymous$Password')

    def test_restrict(self):
        # Admin settings don't exist for now.
        raise SkipTest
        Group.objects.create(name='Restricted', rules='Restricted:UGC')
        r = self.client.post(self.url, self.get_data(restricted=True))
        self.assertRedirects(r, reverse('zadmin.index'))
        assert self.get_user().groups.filter(rules='Restricted:UGC').exists()

    def test_anonymize_fails_with_other_changed_fields(self):
        # Admin settings don't exist for now.
        raise SkipTest
        # We don't let an admin change a field whilst anonymizing.
        data = self.get_data(anonymize=True, display_name='something@else.com')
        r = self.client.post(self.url, data)
        eq_(r.status_code, 200)
        eq_(self.get_user().password, self.regular.password)  # Hasn't changed.

    def test_admin_logs_edit(self):
        # Admin settings don't exist for now.
        raise SkipTest
        self.client.post(self.url, self.get_data(email='something@else.com'))
        r = ActivityLog.objects.filter(action=amo.LOG.ADMIN_USER_EDITED.id)
        eq_(r.count(), 1)
        assert self.get_data()['admin_log'] in r[0]._arguments

    def test_admin_logs_anonymize(self):
        # Admin settings don't exist for now.
        raise SkipTest
        self.client.post(self.url, self.get_data(anonymize=True))
        r = (ActivityLog.objects
                          .filter(action=amo.LOG.ADMIN_USER_ANONYMIZED.id))
        eq_(r.count(), 1)
        assert self.get_data()['admin_log'] in r[0]._arguments

    def test_admin_no_password(self):
        # Admin settings don't exist for now.
        raise SkipTest
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
        self.currency_url = reverse('account.payment.currency')

    def get_url(self, status=None):
        return reverse('account.payment', args=[status] if status else [])

    def test_currency_denied(self):
        self.client.logout()
        eq_(self.client.get(self.currency_url).status_code, 302)

    def test_currency_set(self):
        eq_(self.user.get_preapproval(), None)
        eq_(self.client.post(self.currency_url,
                             {'currency': 'USD'}).status_code, 302)
        eq_(self.user.get_preapproval().currency, 'USD')
        eq_((ActivityLog.objects.filter(action=amo.LOG.CURRENCY_UPDATED.id)
                                .count()), 1)

    def test_extra_currency(self):
        price = Price.objects.create(price='1')
        PriceCurrency.objects.create(price='1', tier=price, currency='EUR')
        eq_(self.client.post(self.currency_url,
                             {'currency': 'EUR'}).status_code, 302)
        eq_(self.user.get_preapproval().currency, 'EUR')
        eq_(self.client.post(self.currency_url,
                             {'currency': 'BRL'}).status_code, 200)
        eq_(self.user.get_preapproval().currency, 'EUR')

    def test_preapproval_denied(self):
        self.client.logout()
        eq_(self.client.get(self.get_url()).status_code, 302)

    def test_preapproval_allowed(self):
        eq_(self.client.get(self.get_url()).status_code, 200)

    def test_preapproval_setup(self):
        doc = pq(self.client.get(self.get_url()).content)
        eq_(doc('#preapproval').attr('action'),
            reverse('account.payment.preapproval'))

    @mock.patch('mkt.account.views.client')
    @mock.patch('mkt.account.views.waffle.flag_is_active')
    def test_preapproval_solitude(self, flag_is_active, client):
        flag_is_active.return_value = True
        url = 'http://foo.com/?bar'
        client.post_preapproval.return_value = {'paypal_url': url,
                                                'key': 'bar', 'pk': 'foo'}
        res = self.client.post(reverse('account.payment.preapproval'),
                               {'currency': 'USD'})
        eq_(res['Location'], url)
        eq_(self.user.pk,
            client.post_preapproval.call_args[1]['data']['uuid'].pk)

    @mock.patch('paypal.get_preapproval_key')
    @mock.patch('mkt.account.views.waffle.switch_is_active')
    def test_fake_preapproval_with_currency(self, switch_is_active,
                                            get_preapproval_key):
        switch_is_active.return_value = True
        get_preapproval_key.return_value = {'preapprovalKey': 'xyz'}
        self.client.post(reverse('account.payment.preapproval'),
                         {'currency': 'USD'})
        eq_(self.user.get_preapproval().currency, 'USD')

    @mock.patch('paypal.get_preapproval_key')
    @mock.patch('mkt.account.views.waffle.switch_is_active')
    def test_fake_preapproval_no_currency(self, switch_is_active,
                                          get_preapproval_key):
        switch_is_active.return_value = True
        get_preapproval_key.return_value = {'preapprovalKey': 'xyz'}
        res = self.client.post(reverse('account.payment.preapproval'))
        eq_(res.status_code, 200)
        eq_(self.user.get_preapproval().currency, None)

    @mock.patch('paypal.get_preapproval_key')
    def test_fake_preapproval(self, get_preapproval_key):
        get_preapproval_key.return_value = {'preapprovalKey': 'xyz'}
        res = self.client.post(reverse('account.payment.preapproval'),
                               {'currency': 'USD'})
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
        eq_((ActivityLog.objects.filter(action=amo.LOG.PREAPPROVAL_ADDED.id)
                                .count()), 1)

    @mock.patch('mkt.account.views.client')
    def test_preapproval_complete_solitude(self, client):
        ssn = self.client.session
        ssn['setup-preapproval'] = {'solitude-key': 'xyz'}
        ssn.save()
        waffle.models.Flag.objects.create(name='solitude-payments',
                                          everyone=True)
        res = self.client.post(self.get_url('complete'))
        eq_(res.status_code, 200)
        eq_(client.put_preapproval.call_args[1]['pk'], 'xyz')

    def test_preapproval_cancel(self):
        PreApprovalUser.objects.create(user=self.user, paypal_key='xyz')
        res = self.client.post(self.get_url('cancel'))
        eq_(res.status_code, 200)
        eq_(self.user.preapprovaluser.paypal_key, 'xyz')
        eq_(pq(res.content)('#preapproval').attr('action'),
            self.get_url('remove'))

    @mock.patch('mkt.account.views.client')
    def test_preapproval_remove_solitude(self, client):
        waffle.models.Flag.objects.create(name='solitude-payments',
                                          everyone=True)
        self.client.post(self.get_url('remove'))
        eq_(client.lookup_buyer_paypal.call_args[0][0].pk, self.user.pk)
        assert 'pk' in client.patch_buyer_paypal.call_args[1]
        eq_(client.patch_buyer_paypal.call_args[1]['data']['key'], '')

    def test_session_complete(self):
        ssn = self.client.session
        ssn['setup-preapproval'] = {'key': 'xyz', 'complete': '/foo'}
        ssn.save()
        res = self.client.post(self.get_url('complete'))
        assert res['Location'].endswith('/foo')
        eq_(self.user.preapprovaluser.paypal_key, 'xyz')

    def test_session_cancel(self):
        ssn = self.client.session
        ssn['setup-preapproval'] = {'key': 'abc', 'cancel': '/bar'}
        ssn.save()
        res = self.client.post(self.get_url('cancel'))
        assert res['Location'].endswith('/bar')
        eq_(self.user.preapprovaluser.paypal_key, None)

    def test_preapproval_remove(self):
        PreApprovalUser.objects.create(user=self.user, paypal_key='xyz')
        res = self.client.post(self.get_url('remove'))
        eq_(res.status_code, 200)
        eq_(self.user.preapprovaluser.paypal_key, '')
        eq_(pq(res.content)('#preapproval').attr('action'),
            reverse('account.payment.preapproval'))
        eq_((ActivityLog.objects.filter(action=amo.LOG.PREAPPROVAL_REMOVED.id)
                                .count()), 1)


class TestProfileLinks(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        raise SkipTest
        self.user = self.get_user()

    def get_user(self):
        return UserProfile.objects.get(username='31337')

    def get_url(self):
        return reverse('users.profile', args=[self.user.username])

    def log_in(self):
        assert self.client.login(username=self.user.email, password='password')

    def test_username(self):
        r = self.client.get(reverse('users.profile',
                            args=[self.user.username]))
        eq_(r.status_code, 200)

    def get_profile_links(self, username):
        """Grab profile, return edit links."""
        url = reverse('users.profile', args=[username])
        r = self.client.get(url)
        eq_(r.status_code, 200)
        return pq(r.content)('#profile-actions a')

    def test_viewing_my_profile(self):
        # Me as (non-admin) viewing my own profile.
        self.log_in()
        links = self.get_profile_links(self.user.username)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('account.settings'))

    def test_viewing_my_profile_as_other_user(self):
        # Ensure no edit buttons are shown.
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        links = self.get_profile_links(self.user.username)
        eq_(links.length, 0, 'No edit buttons should be shown.')

    def test_viewing_my_profile_as_anonymous(self):
        # Ensure no edit buttons are shown.
        links = self.get_profile_links(self.user.username)
        eq_(links.length, 0, 'No edit buttons should be shown.')

    def test_viewing_other_profile(self):
        self.log_in()
        # Me as (non-admin) viewing someone else's my own profile.
        eq_(self.get_profile_links('regularuser').length, 0)

    def test_viewing_my_profile_as_admin(self):
        self.log_in()
        # Me as (with admin) viewing my own profile.
        GroupUser.objects.create(
            group=Group.objects.create(rules='Users:Edit'), user=self.user)
        assert self.client.login(username=self.user.email, password='password')
        links = self.get_profile_links(self.user.username)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('account.settings'))

    def test_viewing_other_profile_as_admin(self):
        self.log_in()
        # Me as (with admin) viewing someone else's profile.
        GroupUser.objects.create(
            group=Group.objects.create(rules='Users:Edit'), user=self.user)
        assert self.client.login(username=self.user.email, password='password')
        links = self.get_profile_links('regularuser')
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.admin_edit', args=[999]))


class TestProfileSections(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        raise SkipTest
        self.user = self.get_user()
        # Authentication is required for now.
        assert self.client.login(username=self.user.email, password='password')
        self.url = reverse('users.profile', args=[self.user.username])

    def get_user(self):
        return UserProfile.objects.get(username='31337')

    def test_my_submissions(self):
        other_app = amo.tests.app_factory()
        AddonUser.objects.create(user=self.user, addon=other_app)
        AddonUser.objects.create(user=self.user, addon_id=3615)

        r = self.client.get(self.url)
        eq_(r.status_code, 200)

        subs = r.context['submissions'].object_list
        eq_(list(subs),
            sorted(subs, key=lambda x: x.weekly_downloads, reverse=True))
        eq_(sorted(s.id for s in subs), sorted([other_app.id, 337141]))

        doc = pq(r.content)
        eq_(doc('.num-submissions a[href="#my-submissions"]').length, 1)
        eq_(doc('#my-submissions .item').length, 2)

    def test_my_submissions_no_pagination(self):
        r = self.client.get(self.url)
        assert len(self.user.apps_listed) <= 10, (
            'This user should have fewer than 10 add-ons.')
        eq_(pq(r.content)('#my-submissions .paginator').length, 0)

    def test_my_submissions_pagination(self):
        for x in xrange(20):
            AddonUser.objects.create(user=self.user, addon_id=337141)
        assert len(self.user.apps_listed) > 10, (
            'This user should have way more than 10 add-ons.')
        r = self.client.get(self.url)
        eq_(pq(r.content)('#my-submissions .paginator').length, 1)

    def test_my_reviews(self):
        review = Review.objects.create(user=self.user, addon_id=337141)
        eq_(list(self.user.reviews), [review])

        r = self.client.get(self.url)
        doc = pq(r.content)('.reviews')
        eq_(doc('.items-profile li.review').length, 1)
        eq_(doc('.review-heading-profile').length, 1)
        eq_(doc('#review-%s' % review.id).length, 1)


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
            version = Version.objects.create(addon=app)
            app.update(_current_version=version)
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

    # We don't have this page/flow right now. It will be back.
    def setUp(self):
        raise SkipTest

    def get_support_url(self, pk=None, *args):
        return reverse('support', args=[pk or self.con.pk] + list(args))

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

        for app in self.apps.values():
            for contribution in app.contribution_set.all():
                contribution.update(created=datetime.now()
                                    + timedelta(days=app.id))

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

        self.apps['t2'].contribution_set.all()[0].update(
            created=datetime.now() + timedelta(days=999))
        cache.clear()
        eq_(self.get_order('purchased'), ['t2', 't4', 't3', 't1', 'f1', 'f2'])

    def get_pq(self, **kw):
        r = self.client.get(self.url, dict(sort='name', **kw))
        eq_(r.status_code, 200)
        return pq(r.content)('#purchases')

    def test_price(self):
        assert '$1.00' in self.get_pq()('.purchase').eq(0).text()

    def test_price_locale(self):
        purchases = self.get_pq(lang='fr')
        assert u'1,00' in purchases('.purchase').eq(0).text()

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

    def test_support_link(self):
        eq_(self.get_pq()('a.request-support').eq(0).attr('href'),
            self.get_support_url())

    def test_support_link_inapp(self):
        self.con.update(type=amo.CONTRIB_INAPP)
        eq_(self.get_pq()('a.request-support').eq(0).attr('href'),
            self.get_support_url())

    def test_support_link_inapp_multiple(self):
        self.con.update(type=amo.CONTRIB_INAPP)
        con = self.make_contribution(self.con.addon, 1, amo.CONTRIB_INAPP, 2)
        res = self.get_pq()
        eq_(res('a.request-support').eq(0).attr('href'),
            self.get_support_url())
        eq_(res('a.request-support').eq(1).attr('href'),
            self.get_support_url(pk=con.pk))

    def test_support_text_inapp(self):
        self.con.update(type=amo.CONTRIB_INAPP)
        assert self.get_pq()('span.purchase').eq(0).text().startswith('In-app')

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

    def test_inapp_not_installed(self):
        Contribution.objects.all().delete()
        Installed.objects.all().delete()
        self.make_contribution(self.apps['t1'], '1.00', amo.CONTRIB_INAPP, 2)
        eq_(len(self.get_pq()('.item a.request-support')), 1)

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


class TestUserAbuse(amo.tests.TestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        self.user = UserProfile.objects.get(username='regularuser')
        self.url = reverse('users.abuse', args=[self.user.username])
        self.data = {'tuber': '', 'sprout': 'potato', 'text': 'test'}

    def test_success(self):
        self.client.post(self.url, self.data)
        eq_(self.user.abuse_reports.count(), 1)

    def test_error(self):
        self.data['text'] = ''
        self.client.post(self.url, self.data)
        eq_(self.user.abuse_reports.count(), 0)


class TestFeedback(amo.tests.TestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        self.user = UserProfile.objects.get(username='regularuser')
        self.url = reverse('site.feedback')
        self.data = {'tuber': '', 'sprout': 'potato', 'feedback': 'hawt'}

    def do_login(self):
        self.client.login(username=self.user.email, password='password')

    def test_success_authenticated(self):
        self.do_login()
        res = self.client.post(self.url, self.data,
                               HTTP_USER_AGENT='test-agent')
        eq_(res.status_code, 302)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        eq_(msg.to, [settings.MKT_FEEDBACK_EMAIL])
        eq_(msg.subject, u'Marketplace Feedback')
        eq_(msg.from_email, self.user.email)
        assert 'hawt' in msg.body
        assert self.user.get_url_path() in msg.body
        assert 'test-agent' in msg.body
        assert '127.0.0.1' in msg.body

    def test_success_anonymous(self):
        res = self.client.post(self.url, self.data,
                               HTTP_USER_AGENT='test-agent')
        eq_(res.status_code, 302)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        eq_(msg.from_email, u'noreply@mozilla.com')
        assert 'hawt' in msg.body
        assert 'Anonymous' in msg.body
        assert '127.0.0.1' in msg.body

    def test_error(self):
        self.data['feedback'] = ''
        res = self.client.post(self.url, data=self.data)
        eq_(res.status_code, 200)
        eq_(len(mail.outbox), 0)

    def test_page_authenticated(self):
        self.do_login()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('.toggles').length, 1)
