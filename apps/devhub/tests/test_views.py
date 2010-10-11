from decimal import Decimal
import socket

from django.utils import translation

import mock
from nose.tools import eq_, assert_not_equal
from pyquery import PyQuery as pq
import test_utils

import amo
import paypal
from amo.urlresolvers import reverse
from addons.models import Addon, AddonUser, Charity
from devhub.forms import ContribForm
from users.models import UserProfile
from versions.models import License, Version


class HubTest(test_utils.TestCase):
    fixtures = ('browse/nameless-addon', 'base/users')

    def setUp(self):
        translation.activate('en-US')

        self.url = reverse('devhub.index')
        self.login_as_developer()
        eq_(self.client.get(self.url).status_code, 200)

        self.user_profile = UserProfile.objects.get(id=999)
        self.num_addon_clones = 0

    def login_as_developer(self):
        self.client.login(username='regular@mozilla.com', password='password')

    def clone_addon(self, num_copies, addon_id=57132):
        for i in xrange(num_copies):
            addon = Addon.objects.get(id=addon_id)
            addon.id = addon.guid = None
            addon.save()
            AddonUser.objects.create(user=self.user_profile, addon=addon)

            new_addon = Addon.objects.get(id=addon.id)
            new_addon.name = 'addon-%s' % self.num_addon_clones
            new_addon.save()

            self.num_addon_clones += 1


class TestNav(HubTest):

    def test_navbar(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#navbar').length, 1)

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert_not_equal(doc('#navbar ul li.top a').eq(0).text(),
            'My Add-ons',
            'My Add-ons menu should not be visible if user has no add-ons.')

    def test_my_addons(self):
        """Check that the correct items are listed for the My Add-ons menu."""
        # Assign this add-on to the current user profile.
        addon = Addon.objects.get(id=57132)
        AddonUser.objects.create(user=self.user_profile, addon=addon)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # Check the anchor for the 'My Add-ons' menu item.
        eq_(doc('#navbar ul li.top a').eq(0).text(), 'My Add-ons')

        # Check the anchor for the single add-on.
        edit_url = reverse('devhub.addons.edit', args=[57132])
        eq_(doc('#navbar ul li.top li a').eq(0).attr('href'), edit_url)

        # Create 6 add-ons.
        self.clone_addon(6)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # There should be 8 items in this menu.
        eq_(doc('#navbar ul li.top').eq(0).find('ul li').length, 8)

        # This should be the 8th anchor, after the 7 addons.
        eq_(doc('#navbar ul li.top').eq(0).find('li a').eq(7).text(),
            'Submit a New Add-on')

        self.clone_addon(1)

        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#navbar ul li.top').eq(0).find('li a').eq(7).text(),
            'more add-ons...')


class TestDashboard(HubTest):

    def setUp(self):
        super(TestDashboard, self).setUp()
        self.url = reverse('devhub.addons')
        eq_(self.client.get(self.url).status_code, 200)

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('.item item').length, 0)

    def test_addons_items(self):
        """Check that the correct info. is displayed for each add-on:
        namely, that add-ons are paginated at 10 items per page, and that
        when there is more than one page, the 'Sort by' header and pagination
        footer appear.

        """
        # Create 10 add-ons.
        self.clone_addon(10)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # There should be 10 add-on listing items.
        eq_(len(doc('.item .item-info')), 10)

        # There should be neither a listing header nor a pagination footer.
        eq_(doc('#addon-list-options').length, 0)
        eq_(doc('.listing-footer .pagination').length, 0)

        # Create 5 add-ons.
        self.clone_addon(5)

        r = self.client.get(self.url + '?page=2')
        doc = pq(r.content)

        # There should be 10 add-on listing items.
        eq_(len(doc('.item .item-info')), 5)

        # There should be a listing header and pagination footer.
        eq_(doc('#addon-list-options').length, 1)
        eq_(doc('.listing-footer .pagination').length, 1)


class TestOwnership(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.url = reverse('devhub.addons.owner', args=[3615])
        assert self.client.login(username='del@icio.us', password='password')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def formset(self, *args, **kw):
        # def f(*args, prefix='form') is a syntax error.
        prefix = kw.pop('prefix', 'form')
        initial_count = kw.pop('initial_count', 0)
        data = {prefix + '-TOTAL_FORMS': len(args),
                prefix + '-INITIAL_FORMS': initial_count,
                'builtin': License.OTHER, 'text': 'filler'}
        for idx, d in enumerate(args):
            data.update(('%s-%s-%s' % (prefix, idx, k), v)
                        for k, v in d.items())
        data.update(kw)
        return data

    def get_version(self):
        return Version.objects.no_cache().get(id=self.version.id)

    def get_addon(self):
        return Addon.objects.no_cache().get(id=self.addon.id)


class TestEditPolicy(TestOwnership):

    def formset(self, *args, **kw):
        init = self.client.get(self.url).context['user_form'].initial_forms
        args = args + tuple(f.initial for f in init)
        return super(TestEditPolicy, self).formset(*args, **kw)

    def test_edit_eula(self):
        old_eula = self.addon.eula
        data = self.formset(eula='new eula', has_eula=True)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        addon = self.get_addon()
        eq_(unicode(addon.eula), 'new eula')
        eq_(addon.eula.id, old_eula.id)

    def test_delete_eula(self):
        assert self.addon.eula
        r = self.client.post(self.url, self.formset(has_eula=False))
        eq_(r.status_code, 302)
        eq_(self.get_addon().eula, None)


class TestEditLicense(TestOwnership):

    def setUp(self):
        super(TestEditLicense, self).setUp()
        self.version.license = None
        self.version.save()
        self.license = License.objects.create(builtin=1, name='bsd',
                                              on_form=True)

    def formset(self, *args, **kw):
        init = self.client.get(self.url).context['user_form'].initial_forms
        args = args + tuple(f.initial for f in init)
        data = super(TestEditLicense, self).formset(*args, **kw)
        if 'text' not in kw:
            del data['text']
        return data

    def test_success_add_builtin(self):
        data = self.formset(builtin=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(self.license, self.get_version().license)

    def test_success_add_custom(self):
        data = self.formset(builtin=License.OTHER, text='text', name='name')
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        license = self.get_version().license
        eq_(unicode(license.text), 'text')
        eq_(unicode(license.name), 'name')
        eq_(license.builtin, License.OTHER)

    def test_success_edit_custom(self):
        data = self.formset(builtin=License.OTHER, text='text', name='name')
        r = self.client.post(self.url, data)
        license_one = self.get_version().license

        data = self.formset(builtin=License.OTHER, text='woo', name='name')
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        license_two = self.get_version().license
        eq_(unicode(license_two.text), 'woo')
        eq_(unicode(license_two.name), 'name')
        eq_(license_two.builtin, License.OTHER)
        eq_(license_two.id, license_one.id)

    def test_success_switch_license(self):
        data = self.formset(builtin=1)
        r = self.client.post(self.url, data)
        license_one = self.get_version().license

        data = self.formset(builtin=License.OTHER, text='text', name='name')
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        license_two = self.get_version().license
        eq_(unicode(license_two.text), 'text')
        eq_(unicode(license_two.name), 'name')
        eq_(license_two.builtin, License.OTHER)
        assert license_one != license_two

        # Make sure the old license wasn't edited.
        license = License.objects.get(builtin=1)
        eq_(unicode(license.name), 'bsd')

        data = self.formset(builtin=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        license_three = self.get_version().license
        eq_(license_three, license_one)

    def test_custom_has_text(self):
        data = self.formset(builtin=License.OTHER, name='name')
        r = self.client.post(self.url, data)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'license_form', None,
                             'License text is required when choosing Other.')

    def test_custom_has_name(self):
        data = self.formset(builtin=License.OTHER, text='text')
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        license = self.get_version().license
        eq_(unicode(license.text), 'text')
        eq_(unicode(license.name), 'Custom License')
        eq_(license.builtin, License.OTHER)

    def test_no_version(self):
        # Make sure nothing bad happens if there's no version.
        self.addon.update(_current_version=None)
        Version.objects.all().delete()
        data = self.formset(builtin=License.OTHER, text='text')
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)


class TestEditAuthor(TestOwnership):

    def test_success_add_user(self):
        q = (AddonUser.objects.no_cache().filter(addon=3615)
             .values_list('user', flat=True))
        eq_(list(q.all()), [55021])

        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=0)
        data = self.formset(f.initial, u, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(list(q.all()), [55021, 999])

    def test_success_edit_user(self):
        # Add an author b/c we can't edit anything about the current one.
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=1)
        data = self.formset(f.initial, u, initial_count=1)
        self.client.post(self.url, data)
        eq_(AddonUser.objects.get(addon=3615, user=999).listed, True)

        # Edit the user we just added.
        one, two = self.client.get(self.url).context['user_form'].initial_forms
        two.initial['listed'] = False
        data = self.formset(one.initial, two.initial, initial_count=2)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(AddonUser.objects.no_cache().get(addon=3615, user=999).listed,
            False)

    def test_success_delete_user(self):
        data = self.formset(dict(user='regular@mozilla.com', listed=True,
                                 role=amo.AUTHOR_ROLE_OWNER, position=1))
        self.client.post(self.url, data)

        one, two = self.client.get(self.url).context['user_form'].initial_forms
        one.initial['DELETE'] = True
        data = self.formset(one.initial, two.initial, initial_count=2)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(999, AddonUser.objects.get(addon=3615).user_id)

    def test_switch_owner(self):
        # See if we can transfer ownership in one POST.
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['user'] = 'regular@mozilla.com'
        data = self.formset(f.initial, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(999, AddonUser.objects.get(addon=3615).user_id)

    def test_only_owner_can_edit(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=0)
        data = self.formset(f.initial, u, initial_count=1)
        self.client.post(self.url, data)

        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.url, data, follow=True)

        # Try deleting the other AddonUser
        one, two = self.client.get(self.url).context['user_form'].initial_forms
        one.initial['DELETE'] = True
        data = self.formset(one.initial, two.initial, initial_count=2)
        r = self.client.post(self.url, data, follow=True)
        eq_(r.status_code, 403)
        eq_(AddonUser.objects.filter(addon=3615).count(), 2)

    def test_must_have_listed(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['listed'] = False
        data = self.formset(f.initial, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.context['user_form'].non_form_errors(),
            ['At least one author must be listed.'])

    def test_must_have_owner(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['role'] = amo.AUTHOR_ROLE_DEV
        data = self.formset(f.initial, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.context['user_form'].non_form_errors(),
            ['Must have at least one owner.'])

    def test_must_have_owner_delete(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['DELETE'] = True
        data = self.formset(f.initial, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.context['user_form'].non_form_errors(),
            ['Must have at least one owner.'])


class TestEditPayments(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = self.get_addon()
        self.foundation = Charity.objects.create(
            id=amo.FOUNDATION_ORG, name='moz', url='$$.moz', paypal='moz.pal')
        self.url = reverse('devhub.addons.payments', args=[self.addon.id])
        assert self.client.login(username='del@icio.us', password='password')
        self.paypal_mock = mock.Mock()
        self.paypal_mock.return_value = (True, None)
        paypal.check_paypal_id = self.paypal_mock

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def post(self, *args, **kw):
        d = dict(*args, **kw)
        eq_(self.client.post(self.url, d).status_code, 302)

    def check(self, **kw):
        addon = self.get_addon()
        for k, v in kw.items():
            eq_(getattr(addon, k), v)
        assert addon.wants_contributions
        assert addon.takes_contributions

    def test_success_dev(self):
        self.post(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                  annoying=amo.CONTRIB_AFTER)
        self.check(paypal_id='greed@dev', suggested_amount=2,
                   annoying=amo.CONTRIB_AFTER)

    def test_success_foundation(self):
        self.post(recipient='moz', suggested_amount=2, paypal_id='greed@dev',
                  annoying=amo.CONTRIB_ROADBLOCK)
        self.check(paypal_id='greed@dev', suggested_amount=2,
                   charity=self.foundation, annoying=amo.CONTRIB_ROADBLOCK)

    def test_success_charity(self):
        d = dict(recipient='org', suggested_amount=11.5,
                 annoying=amo.CONTRIB_PASSIVE)
        d.update({'charity-name': 'fligtar fund',
                  'charity-url': 'http://feed.me',
                  'charity-paypal': 'greed@org'})
        self.post(d)
        self.check(paypal_id='', suggested_amount=Decimal('11.50'),
                   charity=Charity.objects.get(name='fligtar fund'))

    def test_dev_paypal_reqd(self):
        d = dict(recipient='dev', suggested_amount=2,
                 annoying=amo.CONTRIB_PASSIVE)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'contrib_form', None,
                             'PayPal id required to accept contributions.')

    def test_bad_paypal_id(self):
        self.paypal_mock.return_value = False, 'error'
        d = dict(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                 annoying=amo.CONTRIB_AFTER)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'contrib_form', None, 'error')

    def test_paypal_timeout(self):
        self.paypal_mock.side_effect = socket.timeout()
        d = dict(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                 annoying=amo.CONTRIB_AFTER)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'contrib_form', None,
                             'Could not validate PayPal id.')

    def test_charity_details_reqd(self):
        d = dict(recipient='org', suggested_amount=11.5,
                 annoying=amo.CONTRIB_PASSIVE)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'charity_form', 'name',
                             'This field is required.')
        eq_(self.get_addon().suggested_amount, None)

    def test_switch_charity_to_dev(self):
        self.test_success_charity()
        self.test_success_dev()
        eq_(self.get_addon().charity, None)
        eq_(self.get_addon().charity_id, None)

    def test_switch_charity_to_foundation(self):
        self.test_success_charity()
        self.test_success_foundation()
        # This will break if we start cleaning up licenses.
        old_charity = Charity.objects.get(name='fligtar fund')
        assert old_charity.id != self.foundation

    def test_switch_foundation_to_charity(self):
        self.test_success_foundation()
        self.test_success_charity()
        moz = Charity.objects.get(id=self.foundation.id)
        eq_(moz.name, 'moz')
        eq_(moz.url, '$$.moz')
        eq_(moz.paypal, 'moz.pal')

    def test_contrib_form_initial(self):
        eq_(ContribForm.initial(self.addon)['recipient'], 'dev')
        self.addon.charity = self.foundation
        eq_(ContribForm.initial(self.addon)['recipient'], 'moz')
        self.addon.charity_id = amo.FOUNDATION_ORG + 1
        eq_(ContribForm.initial(self.addon)['recipient'], 'org')

        eq_(ContribForm.initial(self.addon)['annoying'], amo.CONTRIB_PASSIVE)
        self.addon.annoying = amo.CONTRIB_AFTER
        eq_(ContribForm.initial(self.addon)['annoying'], amo.CONTRIB_AFTER)
