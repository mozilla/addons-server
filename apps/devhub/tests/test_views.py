import re
import socket
from decimal import Decimal
from urllib import urlencode

from django import forms
from django.conf import settings
from django.utils import translation

import mock
from nose.tools import eq_, assert_not_equal, assert_raises
from pyquery import PyQuery as pq
import test_utils

import amo
import paypal
from amo.urlresolvers import reverse
from addons.models import Addon, AddonUser, Charity
from applications.models import AppVersion
from bandwagon.models import Collection
from devhub.forms import ContribForm
from devhub.models import ActivityLog, RssKey, SubmitStep
from files.models import File, Platform
from reviews.models import Review
from tags.models import Tag
from users.models import UserProfile
from versions.models import ApplicationsVersions, License, Version


class HubTest(test_utils.TestCase):
    fixtures = ['browse/nameless-addon', 'base/users']

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


class TestActivity(HubTest):
    """Test the activity feed."""

    def setUp(self):
        """Start with one user, two add-ons."""
        super(TestActivity, self).setUp()
        self.clone_addon(2)
        amo.set_user(self.user_profile)
        self.addon, self.addon2 = list(self.user_profile.addons.all())

    def log_creates(self, num, addon=None):
        if not addon:
            addon = self.addon
        for i in xrange(num):
            amo.log(amo.LOG.CREATE_ADDON, addon)

    def log_updates(self, num):
        version = Version.objects.create(version='1', addon=self.addon)
        for i in xrange(num):
            amo.log(amo.LOG.ADD_VERSION, self.addon, version)

    def log_status(self, num):
        for i in xrange(num):
            amo.log(amo.LOG.SET_INACTIVE, self.addon)

    def log_collection(self, num):
        for i in xrange(num):
            c = Collection(name='foo %d' % i)
            amo.log(amo.LOG.ADD_TO_COLLECTION, self.addon, c)

    def log_review(self, num):
        r = Review(addon=self.addon)
        for i in xrange(num):
            amo.log(amo.LOG.ADD_REVIEW, self.addon, r)

    def get_response(self, **kwargs):
        url = reverse('devhub.feed_all')
        if 'addon' in kwargs:
            url = reverse('devhub.feed', args=(kwargs['addon'],))

        if kwargs:
            url += '?' + urlencode(kwargs)

        return self.client.get(url, follow=True)

    def get_pq(self, **kwargs):
        return pq(self.get_response(**kwargs).content)

    def test_dashboard(self):
        """Make sure the dashboard is getting data."""
        self.log_creates(10)
        r = self.client.get(reverse('devhub.addons'))
        doc = pq(r.content)
        eq_(len(doc('li.item')), 4)
        eq_(doc('.subscribe-feed').attr('href')[:-32],
            reverse('devhub.feed_all') + '?privaterss=')

    def test_items(self):
        self.log_creates(10)
        doc = self.get_pq()
        eq_(len(doc('.item')), 10)

    def test_filter_updates(self):
        self.log_creates(10)
        self.log_updates(10)
        doc = self.get_pq()
        eq_(len(doc('.item')), 20)
        doc = self.get_pq(action='updates')
        eq_(len(doc('.item')), 10)

    def test_filter_status(self):
        self.log_creates(10)
        self.log_status(5)
        doc = self.get_pq()
        eq_(len(doc('.item')), 15)
        doc = self.get_pq(action='status')
        eq_(len(doc('.item')), 5)

    def test_filter_collections(self):
        self.log_creates(10)
        self.log_collection(3)
        doc = self.get_pq()
        eq_(len(doc('.item')), 13)
        doc = self.get_pq(action='collections')
        eq_(len(doc('.item')), 3)

    def test_filter_reviews(self):
        self.log_creates(10)
        self.log_review(10)
        doc = self.get_pq()
        eq_(len(doc('.item')), 20)
        doc = self.get_pq(action='reviews')
        eq_(len(doc('.item')), 10)

    def test_pagination(self):
        self.log_review(21)
        doc = self.get_pq()

        # 20 items on page 1.
        eq_(len(doc('.item')), 20)

        # 1 item on page 2
        doc = self.get_pq(page=2)
        eq_(len(doc('.item')), 1)

        # we have a pagination thingy
        eq_(len(doc('.pagination')), 1)
        assert doc('.listing-footer')

    def test_no_pagination(self):
        doc = self.get_pq()
        assert not doc('.listing-footer')

    def test_filter_addon(self):
        self.log_creates(10)
        self.log_creates(13, self.addon2)

        # We show everything without filters
        doc = self.get_pq()
        eq_(len(doc('.item')), 20)

        # We just show addon1
        doc = self.get_pq(addon=self.addon.id)
        eq_(len(doc('.item')), 10)

        # we just show addon2
        doc = self.get_pq(addon=self.addon2.id)
        eq_(len(doc('.item')), 13)

    def test_filter_addon_admin(self):
        """Admins should be able to see specific pages."""
        self.log_creates(10)
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        r = self.get_response(addon=self.addon.id)
        eq_(r.status_code, 200)

    def test_filter_addon_otherguy(self):
        """Make sure nobody else can see my precious add-on feed."""
        self.log_creates(10)
        assert self.client.login(username='clouserw@gmail.com',
                                 password='password')
        r = self.get_response(addon=self.addon.id)
        eq_(r.status_code, 403)

    def test_rss(self):
        self.log_creates(5)
        # This will give us a new RssKey
        r = self.get_response()
        key = RssKey.objects.get()
        r = self.get_response(privaterss=key.key)
        eq_(r['content-type'], 'application/rss+xml')

    def test_rss_single(self):
        self.log_creates(5)
        self.log_creates(13, self.addon2)

        # This will give us a new RssKey
        r = self.get_response(addon=self.addon.id)
        key = RssKey.objects.get()
        r = self.get_response(privaterss=key.key)
        eq_(r['content-type'], 'application/rss+xml')
        eq_(len(pq(r.content)('item')), 5)

    def test_logged_out(self):
        self.client.logout()
        r = self.get_response()
        eq_(r.redirect_chain[0][1], 302)


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

        eq_(len(doc('.item .item-info')), 10)
        eq_(doc('#addon-list-options').length, 0)
        eq_(doc('.listing-footer .pagination').length, 0)

        # Create 5 add-ons.
        self.clone_addon(5)

        r = self.client.get(self.url + '?page=2')
        doc = pq(r.content)

        eq_(len(doc('.item .item-info')), 5)
        eq_(doc('#addon-list-options').length, 1)
        eq_(doc('.listing-footer .pagination').length, 1)


class TestUpdateCompatibility(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_4594_a9',
                'base/addon_3615']

    def setUp(self):
        self.url = reverse('devhub.addons')

    def test_no_compat(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert not doc('.item[data-addonid=4594] .tooltip.compat-update')
        a = Addon.objects.get(pk=4594)
        r = self.client.get(reverse('devhub.ajax.compat.update',
                                    args=[a.id, a.current_version.id]))
        eq_(r.status_code, 404)

    def test_compat(self):
        a = Addon.objects.get(pk=3615)
        assert self.client.login(username='del@icio.us', password='password')

        r = self.client.get(self.url)
        doc = pq(r.content)
        cu = doc('.item[data-addonid=3615] .tooltip.compat-update')
        assert cu

        update_url = reverse('devhub.ajax.compat.update',
                             args=[a.id, a.current_version.id])
        eq_(cu.attr('data-updateurl'), update_url)

        status_url = reverse('devhub.ajax.compat.status', args=[a.id])
        eq_(doc('.item[data-addonid=3615] li.compat').attr('data-src'),
            status_url)

        assert doc('.item[data-addonid=3615] .compat-update-modal')

    def test_incompat(self):
        av = ApplicationsVersions.objects.get(pk=47881)
        av.max = AppVersion.objects.get(pk=97)  # Firefox 2.0
        av.save()
        assert self.client.login(username='del@icio.us', password='password')
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('.item[data-addonid=3615] .tooltip.compat-error')
        assert doc('.item[data-addonid=3615] .compat-error-popup .app.%s' %
                   amo.FIREFOX.short)


def formset(*args, **kw):
    """
    Build up a formset-happy POST.

    *args is a sequence of forms going into the formset.
    prefix and initial_count can be set in **kw.
    """
    prefix = kw.pop('prefix', 'form')
    initial_count = kw.pop('initial_count', len(args))
    data = {prefix + '-TOTAL_FORMS': len(args),
            prefix + '-INITIAL_FORMS': initial_count}
    for idx, d in enumerate(args):
        data.update(('%s-%s-%s' % (prefix, idx, k), v)
                    for k, v in d.items())
    data.update(kw)
    return data


class TestDevRequired(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.get_url = reverse('devhub.addons.payments', args=[3615])
        self.post_url = reverse('devhub.addons.payments.disable', args=[3615])
        assert self.client.login(username='del@icio.us', password='password')
        self.addon = Addon.objects.get(id=3615)
        self.au = AddonUser.objects.get(user__email='del@icio.us',
                                        addon=self.addon)
        eq_(self.au.role, amo.AUTHOR_ROLE_OWNER)

    def test_anon(self):
        self.client.logout()
        r = self.client.get(self.get_url, follow=True)
        login = reverse('users.login')
        self.assertRedirects(r, '%s?to=%s' % (login, self.get_url))

    def test_dev_get(self):
        eq_(self.client.get(self.get_url).status_code, 200)

    def test_dev_post(self):
        self.assertRedirects(self.client.post(self.post_url), self.get_url)

    def test_viewer_get(self):
        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        eq_(self.client.get(self.get_url).status_code, 200)

    def test_viewer_post(self):
        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        eq_(self.client.post(self.get_url).status_code, 403)


class TestOwnership(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.url = reverse('devhub.addons.owner', args=[3615])
        assert self.client.login(username='del@icio.us', password='password')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def formset(self, *args, **kw):
        defaults = {'builtin': License.OTHER, 'text': 'filler'}
        defaults.update(kw)
        return formset(*args, **defaults)

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
        kw['initial_count'] = len(init)
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
        user_form = self.client.get(self.url).context['user_form']
        one, two = user_form.initial_forms
        del two.initial['listed']
        empty = dict(user='', listed=True, role=5, position=0)
        data = self.formset(one.initial, two.initial, empty, initial_count=2)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(AddonUser.objects.no_cache().get(addon=3615, user=999).listed,
            False)

    def test_add_user_twice(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=1)
        data = self.formset(f.initial, u, u, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 200)
        eq_(r.context['user_form'].non_form_errors(),
            ['An author can only be listed once.'])

    def test_success_delete_user(self):
        # Add a new user so we have one to delete.
        data = self.formset(dict(user='regular@mozilla.com', listed=True,
                                 role=amo.AUTHOR_ROLE_OWNER, position=1),
                            initial_count=0)
        self.client.post(self.url, data)

        one, two = self.client.get(self.url).context['user_form'].initial_forms
        one.initial['DELETE'] = True
        data = self.formset(one.initial, two.initial, initial_count=2)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(999, AddonUser.objects.get(addon=3615).user_id)

    def test_logs(self):
        # A copy of switch ownership to test logs
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['user'] = 'regular@mozilla.com'
        data = self.formset(f.initial, initial_count=1)
        o = ActivityLog.objects
        eq_(o.count(), 0)
        r = self.client.post(self.url, data)
        eq_(o.filter(action=amo.LOG.CHANGE_USER_WITH_ROLE.id).count(), 1)
        eq_(o.filter(action=amo.LOG.CHANGE_LICENSE.id).count(), 1)
        eq_(o.filter(action=amo.LOG.CHANGE_POLICY.id).count(), 1)
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
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
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

    def test_logging(self):
        count = ActivityLog.objects.all().count()
        self.post(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                  annoying=amo.CONTRIB_AFTER)
        eq_(ActivityLog.objects.all().count(), count + 1)

    def test_success_dev(self):
        self.post(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                  annoying=amo.CONTRIB_AFTER)
        self.check(paypal_id='greed@dev', suggested_amount=2,
                   annoying=amo.CONTRIB_AFTER)

    def test_success_foundation(self):
        self.post(recipient='moz', suggested_amount=2,
                  annoying=amo.CONTRIB_ROADBLOCK)
        self.check(paypal_id='', suggested_amount=2,
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
        self.assertFormError(r, 'contrib_form', 'paypal_id',
                             'PayPal id required to accept contributions.')

    def test_bad_paypal_id_dev(self):
        self.paypal_mock.return_value = False, 'error'
        d = dict(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                 annoying=amo.CONTRIB_AFTER)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'contrib_form', 'paypal_id', 'error')

    def test_bad_paypal_id_charity(self):
        self.paypal_mock.return_value = False, 'error'
        d = dict(recipient='org', suggested_amount=11.5,
                 annoying=amo.CONTRIB_PASSIVE)
        d.update({'charity-name': 'fligtar fund',
                  'charity-url': 'http://feed.me',
                  'charity-paypal': 'greed@org'})
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'charity_form', 'paypal', 'error')

    def test_paypal_timeout(self):
        self.paypal_mock.side_effect = socket.timeout()
        d = dict(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                 annoying=amo.CONTRIB_AFTER)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'contrib_form', 'paypal_id',
                             'Could not validate PayPal id.')

    def test_max_suggested_amount(self):
        too_much = settings.MAX_CONTRIBUTION + 1
        msg = ('Please enter a suggested amount less than $%d.' %
               settings.MAX_CONTRIBUTION)
        r = self.client.post(self.url, {'suggested_amount': too_much})
        self.assertFormError(r, 'contrib_form', 'suggested_amount', msg)

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

    def test_enable_thankyou(self):
        d = dict(enable_thankyou='on', thankyou_note='woo',
                 annoying=1, recipient='moz')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        addon = self.get_addon()
        eq_(addon.enable_thankyou, True)
        eq_(unicode(addon.thankyou_note), 'woo')

    def test_enable_thankyou_unchecked_with_text(self):
        d = dict(enable_thankyou='', thankyou_note='woo',
                 annoying=1, recipient='moz')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        addon = self.get_addon()
        eq_(addon.enable_thankyou, False)
        eq_(addon.thankyou_note, None)

    def test_enable_thankyou_no_text(self):
        d = dict(enable_thankyou='on', thankyou_note='',
                 annoying=1, recipient='moz')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        addon = self.get_addon()
        eq_(addon.enable_thankyou, False)
        eq_(addon.thankyou_note, None)


class TestDisablePayments(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.addon.update(wants_contributions=True, paypal_id='woohoo')
        self.pay_url = reverse('devhub.addons.payments', args=[self.addon.id])
        self.disable_url = reverse('devhub.addons.payments.disable',
                                   args=[self.addon.id])
        assert self.client.login(username='del@icio.us', password='password')

    def test_statusbar_visible(self):
        r = self.client.get(self.pay_url)
        self.assertContains(r, '<div id="status-bar">')

        self.addon.update(wants_contributions=False)
        r = self.client.get(self.pay_url)
        self.assertNotContains(r, '<div id="status-bar">')

    def test_disable(self):
        r = self.client.post(self.disable_url)
        eq_(r.status_code, 302)
        assert(r['Location'].endswith(self.pay_url))
        eq_(Addon.uncached.get(id=3615).wants_contributions, False)


class TestPaymentsProfile(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = a = self.get_addon()
        self.url = reverse('devhub.addons.payments', args=[self.addon.id])
        # Make sure all the payment/profile data is clear.
        assert not (a.wants_contributions or a.paypal_id or a.the_reason
                    or a.the_future or a.takes_contributions)
        assert self.client.login(username='del@icio.us', password='password')
        self.paypal_mock = mock.Mock()
        self.paypal_mock.return_value = (True, None)
        paypal.check_paypal_id = self.paypal_mock

    def get_addon(self):
        return Addon.objects.get(id=3615)

    def test_intro_box(self):
        # We don't have payments/profile set up, so we see the intro.
        doc = pq(self.client.get(self.url).content)
        assert doc('.intro')
        assert doc('#setup.hidden')

    def test_status_bar(self):
        # We don't have payments/profile set up, so no status bar.
        doc = pq(self.client.get(self.url).content)
        assert not doc('#status-bar')

    def test_profile_form_exists(self):
        doc = pq(self.client.get(self.url).content)
        assert doc('#id_the_reason')
        assert doc('#id_the_future')

    def test_profile_form_success(self):
        d = dict(recipient='dev', suggested_amount=2, paypal_id='xx@yy',
                 annoying=amo.CONTRIB_ROADBLOCK, the_reason='xxx',
                 the_future='yyy')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)

        # The profile form is gone, we're accepting contributions.
        doc = pq(self.client.get(self.url).content)
        assert not doc('.intro')
        assert not doc('#setup.hidden')
        assert doc('#status-bar')
        assert not doc('#id_the_reason')
        assert not doc('#id_the_future')

        addon = self.get_addon()
        eq_(unicode(addon.the_reason), 'xxx')
        eq_(unicode(addon.the_future), 'yyy')
        eq_(addon.wants_contributions, True)

    def test_profile_required(self):
        def check_page(request):
            doc = pq(request.content)
            assert not doc('.intro')
            assert not doc('#setup.hidden')
            assert not doc('#status-bar')
            assert doc('#id_the_reason')
            assert doc('#id_the_future')

        d = dict(recipient='dev', suggested_amount=2, paypal_id='xx@yy',
                 annoying=amo.CONTRIB_ROADBLOCK)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_reason',
                             'This field is required.')
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')
        check_page(r)
        eq_(self.get_addon().wants_contributions, False)

        d = dict(recipient='dev', suggested_amount=2, paypal_id='xx@yy',
                 annoying=amo.CONTRIB_ROADBLOCK, the_reason='xxx')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')
        check_page(r)
        eq_(self.get_addon().wants_contributions, False)


class TestDelete(test_utils.TestCase):
    fixtures = ('base/apps', 'base/users', 'base/addon_3615',
                'base/addon_5579',)

    def setUp(self):
        self.addon = self.get_addon()
        assert self.client.login(username='del@icio.us', password='password')
        self.url = reverse('devhub.addons.delete', args=[self.addon.id])

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def test_post_nopw(self):
        r = self.client.post(self.url, follow=True)
        eq_(pq(r.content)('.notification-box').text(),
                          'Password was incorrect. Add-on was not deleted.')

    def test_post(self):
        r = self.client.post(self.url, dict(password='password'), follow=True)
        eq_(pq(r.content)('.notification-box').text(), 'Add-on deleted.')
        self.assertRaises(Addon.DoesNotExist, self.get_addon)


class TestEdit(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'base/addon_5579']

    def setUp(self):
        super(TestEdit, self).setUp()
        self.addon = self.get_addon()
        assert self.client.login(username='del@icio.us', password='password')
        self.url = reverse('devhub.addons.edit', args=[self.addon.id])
        self.user = UserProfile.objects.get(pk=55021)

        self.tags = ['tag3', 'tag2', 'tag1']
        for t in self.tags:
            Tag(tag_text=t).save_tag(self.addon, self.user)

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def get_url(self, section, edit=False):
        args = [self.addon.id, section]
        if edit:
            args.append('edit')

        return reverse('devhub.addons.section', args=args)

    def test_redirect(self):
        # /addon/:id => /addon/:id/edit
        r = self.client.get('/en-US/developers/addon/3615/', follow=True)
        url = reverse('devhub.addons.edit', args=[3615])
        self.assertRedirects(r, url, 301)

    def test_edit_basic(self):
        old_name = self.addon.name

        data = dict(name='new name',
                    slug='test_addon',
                    summary='new summary',
                    tags=', '.join(self.tags))

        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)
        addon = self.get_addon()

        eq_(unicode(addon.name), data['name'])
        eq_(addon.name.id, old_name.id)

        eq_(unicode(addon.slug), data['slug'])
        eq_(unicode(addon.summary), data['summary'])

        self.tags.sort()
        eq_([unicode(t) for t in addon.tags.all()], self.tags)

    def test_edit_basic_slugs_unique(self):
        Addon.objects.get(id=5579).update(slug='test_slug')

        data = dict(name='new name',
                    slug='test_slug',
                    summary='new summary',
                    tags=','.join(self.tags))

        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        self.assertFormError(r, 'form', 'slug', 'This slug is already in use.')

    def test_edit_basic_add_tag(self):
        count = ActivityLog.objects.all().count()
        self.tags.insert(0, 'tag4')
        data = dict(name='new name',
                    slug='test_slug',
                    summary='new summary',
                    tags=', '.join(self.tags))

        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        doc = pq(r.content)

        result = doc('#addon_tags_edit').eq(0).text()

        self.tags.sort()
        eq_(result, ', '.join(self.tags))
        eq_((ActivityLog.objects.for_addons(self.addon)
             .get(action=amo.LOG.ADD_TAG.id)).to_string(),
            '<a href="/en-US/firefox/tag/tag4">tag4</a> added to '
            '<a href="/en-US/firefox/addon/3615/">new name</a>')
        eq_(ActivityLog.objects.filter(action=amo.LOG.ADD_TAG.id).count(),
                                        count + 1)

    def test_edit_basic_remove_tag(self):
        self.tags.remove('tag2')

        count = ActivityLog.objects.all().count()

        data = dict(name='new name',
                    slug='test_slug',
                    summary='new summary',
                    tags=', '.join(self.tags))

        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        doc = pq(r.content)

        result = doc('#addon_tags_edit').eq(0).text()

        self.tags.sort()
        eq_(result, ', '.join(self.tags))

        eq_(ActivityLog.objects.filter(action=amo.LOG.REMOVE_TAG.id).count(),
            count + 1)

    def test_edit_basic_minlength_tags(self):
        tags = self.tags
        tags.append('a' * (amo.MIN_TAG_LENGTH - 1))

        data = dict(name='new name',
                    slug='test_slug',
                    summary='new summary',
                    tags=', '.join(tags))

        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        self.assertFormError(r, 'form', 'tags',
                             'All tags must be at least %d characters.' %
                             amo.MIN_TAG_LENGTH)

    def test_edit_basic_max_tags(self):
        tags = self.tags

        for i in range(amo.MAX_TAGS + 1):
            tags.append('test%d' % i)

        data = dict(name='new name',
                    slug='test_slug',
                    summary='new summary',
                    tags=', '.join(tags))

        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        self.assertFormError(r, 'form', 'tags', 'You have %d too many tags.' %
                                                 (len(tags) - amo.MAX_TAGS))

    def test_edit_basic_name_not_empty(self):
        data = dict(name='',
                    slug=self.addon.slug,
                    summary=self.addon.summary)

        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_basic_name_max_length(self):
        data = dict(name='xx' * 70, slug=self.addon.slug,
                    summary=self.addon.summary)
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'name',
                             'Ensure this value has at most 50 '
                             'characters (it has 140).')

    def test_edit_basic_summary_max_length(self):
        data = dict(name=self.addon.name, slug=self.addon.slug,
                    summary='x' * 251)
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'summary',
                             'Ensure this value has at most 250 '
                             'characters (it has 251).')

    def test_edit_details(self):
        data = dict(description='New description with <em>html</em>!',
                    default_locale='es-ES',
                    homepage='http://twitter.com/fligtarsmom')

        r = self.client.post(self.get_url('details', True), data)
        eq_(r.status_code, 200)
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_details_locale(self):
        addon = self.get_addon()
        addon.update(default_locale='en-US')

        r = self.client.get(self.get_url('details', False))

        doc = pq(r.content)

        eq_(doc('.addon_edit_locale').eq(0).text(), "English (US)")

    def test_edit_support(self):
        data = dict(support_email='sjobs@apple.com',
                    support_url='http://apple.com/')

        r = self.client.post(self.get_url('support', True), data)
        eq_(r.status_code, 200)
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_support_getsatisfaction(self):
        urls = [("getsatisfaction.com/abc/products/def", 'abcdef'),  # GS URL
                ("getsatisfaction.com/abc/", 'abc'),  # No company
                ("google.com", None)]  # Delete GS

        for (url, val) in urls:
            data = dict(support_email='abc@def.com',
                        support_url=url)

            r = self.client.post(self.get_url('support', True), data)
            eq_(r.status_code, 200)

            r = self.client.get(self.get_url('support', False))
            doc = pq(r.content)

            result = doc('.addon_edit_gs').eq(0).text()

            result = re.sub('\W', '', result) if result else None

            eq_(result, val)

    def test_log(self):
        data = {'developer_comments': 'This is a test'}
        o = ActivityLog.objects
        eq_(o.count(), 0)
        r = self.client.post(self.get_url('technical', True), data)
        eq_(r.status_code, 200)
        eq_(o.filter(action=amo.LOG.EDIT_PROPERTIES.id).count(), 1)

    def test_technical_on(self):
        # Turn everything on
        data = dict(developer_comments='Test comment!',
                    binary='on',
                    external_software='on',
                    site_specific='on',
                    view_source='on')

        r = self.client.post(self.get_url('technical', True), data)
        eq_(r.status_code, 200)

        addon = self.get_addon()
        for k in data:
            if k == 'developer_comments':
                eq_(unicode(getattr(addon, k)), unicode(data[k]))
            else:
                eq_(getattr(addon, k), True if data[k] == 'on' else False)

        # Andddd offf
        data = dict(developer_comments='Test comment!')
        r = self.client.post(self.get_url('technical', True), data)
        addon = self.get_addon()

        eq_(addon.binary, False)
        eq_(addon.external_software, False)
        eq_(addon.site_specific, False)
        eq_(addon.view_source, False)


class TestProfileBase(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.url = reverse('devhub.addons.profile', args=[3615])
        assert self.client.login(username='del@icio.us', password='password')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def get_addon(self):
        return Addon.objects.no_cache().get(id=self.addon.id)

    def enable_addon_contributions(self):
        self.addon.wants_contributions = True
        self.addon.paypal_id = 'somebody'
        self.addon.save()

    def post(self, *args, **kw):
        d = dict(*args, **kw)
        eq_(self.client.post(self.url, d).status_code, 302)

    def check(self, **kw):
        addon = self.get_addon()
        for k, v in kw.items():
            if k in ('the_reason', 'the_future'):
                eq_(getattr(getattr(addon, k), 'localized_string'), unicode(v))
            else:
                eq_(getattr(addon, k), v)


class TestProfileStatusBar(TestProfileBase):

    def setUp(self):
        super(TestProfileStatusBar, self).setUp()
        self.remove_url = reverse('devhub.addons.profile.remove',
                                  args=[self.addon.id])

    def test_no_status_bar(self):
        self.addon.the_reason = self.addon.the_future = None
        self.addon.save()
        assert not pq(self.client.get(self.url).content)('#status-bar')

    def test_status_bar_no_contrib(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.wants_contributions = False
        self.addon.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('#status-bar')
        eq_(doc('#status-bar button').text(), 'Remove Profile')

    def test_status_bar_with_contrib(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.wants_contributions = True
        self.addon.paypal_id = 'xxx'
        self.addon.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('#status-bar')
        eq_(doc('#status-bar button').text(), 'Remove Both')

    def test_remove_profile(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.client.post(self.remove_url)
        addon = self.get_addon()
        eq_(addon.the_reason, None)
        eq_(addon.the_future, None)
        eq_(addon.takes_contributions, False)
        eq_(addon.wants_contributions, False)

    def test_remove_both(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.wants_contributions = True
        self.addon.paypal_id = 'xxx'
        self.addon.save()
        self.client.post(self.remove_url)
        addon = self.get_addon()
        eq_(addon.the_reason, None)
        eq_(addon.the_future, None)
        eq_(addon.takes_contributions, False)
        eq_(addon.wants_contributions, False)


class TestProfile(TestProfileBase):

    def test_without_contributions_labels(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('label[for=id_the_reason] .optional').length, 1)
        eq_(doc('label[for=id_the_future] .optional').length, 1)

    def test_without_contributions_fields_optional(self):
        self.post(the_reason='', the_future='')
        self.check(the_reason='', the_future='')

        self.post(the_reason='to be cool', the_future='')
        self.check(the_reason='to be cool', the_future='')

        self.post(the_reason='', the_future='hot stuff')
        self.check(the_reason='', the_future='hot stuff')

        self.post(the_reason='to be hot', the_future='cold stuff')
        self.check(the_reason='to be hot', the_future='cold stuff')

    def test_with_contributions_labels(self):
        self.enable_addon_contributions()
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('label[for=id_the_reason] .req').length, \
               'the_reason field should be required.'
        assert doc('label[for=id_the_future] .req').length, \
               'the_future field should be required.'

    def test_log(self):
        self.enable_addon_contributions()
        d = dict(the_reason='because', the_future='i can')
        o = ActivityLog.objects
        eq_(o.count(), 0)
        self.client.post(self.url, d)
        eq_(o.filter(action=amo.LOG.EDIT_PROPERTIES.id).count(), 1)

    def test_with_contributions_fields_required(self):
        self.enable_addon_contributions()

        d = dict(the_reason='', the_future='')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_reason',
                             'This field is required.')
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')

        d = dict(the_reason='to be cool', the_future='')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')

        d = dict(the_reason='', the_future='hot stuff')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_reason',
                             'This field is required.')

        self.post(the_reason='to be hot', the_future='cold stuff')
        self.check(the_reason='to be hot', the_future='cold stuff')


def initial(form):
    """Gather initial data from the form into a dict."""
    data = {}
    for name, field in form.fields.items():
        if form.is_bound:
            data[name] = form[name].data
        else:
            data[name] = form.initial.get(name, field.initial)
        # The browser sends nothing for an unchecked checkbox.
        if isinstance(field, forms.BooleanField):
            val = field.to_python(data[name])
            if not val:
                del data[name]
    return data


class TestVersionEdit(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'base/thunderbird']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.addon = self.get_addon()
        self.version = self.get_version()
        self.url = reverse('devhub.versions.edit',
                           args=[3615, self.version.id])
        self.v1 = AppVersion(application_id=amo.FIREFOX.id, version='1.0')
        self.v4 = AppVersion(application_id=amo.FIREFOX.id, version='4.0')
        for v in self.v1, self.v4:
            v.save()

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def get_version(self):
        return self.get_addon().current_version

    def formset(self, *args, **kw):
        defaults = {'approvalnotes': 'xxx'}
        defaults.update(kw)
        return formset(*args, **defaults)


class TestVersionEditDetails(TestVersionEdit):

    def setUp(self):
        super(TestVersionEditDetails, self).setUp()
        ctx = self.client.get(self.url).context
        compat = initial(ctx['compat_form'].forms[0])
        files = initial(ctx['file_form'].forms[0])
        self.initial = formset(compat, **formset(files, prefix='files'))

    def formset(self, *args, **kw):
        defaults = dict(self.initial)
        defaults.update(kw)
        return super(TestVersionEditDetails, self).formset(*args, **defaults)

    def test_edit_notes(self):
        d = self.formset(releasenotes='xx', approvalnotes='yy')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        version = self.get_version()
        eq_(unicode(version.releasenotes), 'xx')
        eq_(unicode(version.approvalnotes), 'yy')

    def test_version_number_redirect(self):
        url = self.url.replace(str(self.version.id), self.version.version)
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, self.url)


class TestVersionEditSearchEngine(TestVersionEdit):
    # https://bugzilla.mozilla.org/show_bug.cgi?id=605941
    fixtures = ['base/apps', 'base/users',
                'base/thunderbird', 'base/addon_4594_a9.json']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.versions.edit',
                           args=[4594, 42352])

    def test_search_engine_edit(self):
        dd = self.formset(prefix="files", releasenotes='xx',
                          approvalnotes='yy')

        r = self.client.post(self.url, dd)
        eq_(r.status_code, 302)
        version = Addon.objects.no_cache().get(id=4594).current_version
        eq_(unicode(version.releasenotes), 'xx')
        eq_(unicode(version.approvalnotes), 'yy')

    def test_no_compat(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert not doc("#id_form-TOTAL_FORMS")


class TestVersionEditFiles(TestVersionEdit):

    def setUp(self):
        super(TestVersionEditFiles, self).setUp()
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        self.compat = initial(f)

    def formset(self, *args, **kw):
        compat = formset(self.compat, initial_count=1)
        compat.update(kw)
        return super(TestVersionEditFiles, self).formset(*args, **compat)

    def test_delete_file(self):
        eq_(self.version.files.count(), 1)
        forms = map(initial,
                    self.client.get(self.url).context['file_form'].forms)
        forms[0]['DELETE'] = True
        eq_(ActivityLog.objects.count(), 0)
        r = self.client.post(self.url, self.formset(*forms, prefix='files'))

        eq_(ActivityLog.objects.count(), 1)
        log = ActivityLog.objects.all()[0]
        eq_(log.to_string(), u'File delicious_bookmarks-2.1.072-fx.xpi '
                              'deleted from <a href="/en-US/firefox/addon/3615'
                              '/versions/2.1.072">Version 2.1.072</a> of <a '
                              'href="/en-US/firefox/addon/3615/">Delicious '
                              'Bookmarks</a>')
        eq_(r.status_code, 302)
        eq_(self.version.files.count(), 0)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_edit_status(self):
        f = self.client.get(self.url).context['file_form'].forms[0]
        # Public is one of the choices since the file is currently public.
        eq_([x[0] for x in f.fields['status'].choices],
            [amo.STATUS_BETA, amo.STATUS_UNREVIEWED, amo.STATUS_PUBLIC])
        # Switch the status to Beta.
        data = initial(f)
        data['status'] = amo.STATUS_BETA
        r = self.client.post(self.url, self.formset(data, prefix='files'))
        eq_(r.status_code, 302)
        eq_(self.version.files.get().status, amo.STATUS_BETA)

        # Beta and unreviewed are the only choices.
        f = self.client.get(self.url).context['file_form'].forms[0]
        eq_([x[0] for x in f.fields['status'].choices],
            [amo.STATUS_BETA, amo.STATUS_UNREVIEWED])

    def test_unique_platforms(self):
        for platform in amo.PLATFORMS:
            k, _ = Platform.objects.get_or_create(id=platform)
        # Move the existing file to Linux.
        f = self.version.files.get()
        f.update(platform=Platform.objects.get(id=amo.PLATFORM_LINUX.id))
        # And make a new file for Mac.
        File.objects.create(version=self.version,
                            platform_id=amo.PLATFORM_MAC.id)

        forms = map(initial,
                    self.client.get(self.url).context['file_form'].forms)
        forms[1]['platform'] = forms[0]['platform']
        r = self.client.post(self.url, self.formset(*forms, prefix='files'))
        doc = pq(r.content)
        assert doc('#id_files-0-platform')
        eq_(r.status_code, 200)
        eq_(r.context['file_form'].non_form_errors(),
            ['A platform can only be chosen once.'])


class TestPlatformSearch(TestVersionEdit):
    fixtures = ['base/apps', 'base/users',
                'base/thunderbird', 'base/addon_4594_a9.json']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.versions.edit',
                           args=[4594, 42352])
        self.version = Version.objects.get(id=42352)
        self.file = self.version.files.all()[0]
        for platform in amo.PLATFORMS:
            k, _ = Platform.objects.get_or_create(id=platform)

    def test_no_platform_search_engine(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('#id_files-0-platform')

    def test_changing_platform_search_engine(self):
        dd = self.formset({'id': int(self.file.pk),
                           'status': self.file.status,
                           'platform': amo.PLATFORM_LINUX.id},
                           prefix='files', releasenotes='xx',
                           approvalnotes='yy')
        response = self.client.post(self.url, dd)
        eq_(response.status_code, 302)
        uncached = Version.uncached.get(id=42352).files.all()[0]
        eq_(amo.PLATFORM_ALL.id, uncached.platform.id)


class TestVersionEditCompat(TestVersionEdit):

    def formset(self, *args, **kw):
        defaults = formset(prefix='files')
        defaults.update(kw)
        return super(TestVersionEditCompat, self).formset(*args, **defaults)

    def test_add_appversion(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = self.formset(initial(f), dict(application=18, min=28, max=29),
                         initial_count=1)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        apps = self.get_version().compatible_apps.keys()
        eq_(sorted(apps), sorted([amo.FIREFOX, amo.THUNDERBIRD]))

    def test_update_appversion(self):
        av = self.version.apps.get()
        eq_(av.min.version, '2.0')
        eq_(av.max.version, '3.7a1pre')
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d.update(min=self.v1.id, max=self.v4.id)
        r = self.client.post(self.url,
                             self.formset(d, initial_count=1))
        eq_(r.status_code, 302)
        av = self.version.apps.get()
        eq_(av.min.version, '1.0')
        eq_(av.max.version, '4.0')

    def test_delete_appversion(self):
        # Add thunderbird compat so we can delete firefox.
        self.test_add_appversion()
        f = self.client.get(self.url).context['compat_form']
        d = map(initial, f.initial_forms)
        d[0]['DELETE'] = True
        r = self.client.post(self.url, self.formset(*d, initial_count=2))
        eq_(r.status_code, 302)
        apps = self.get_version().compatible_apps.keys()
        eq_(apps, [amo.THUNDERBIRD])

    def test_unique_apps(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        dupe = initial(f)
        del dupe['id']
        d = self.formset(initial(f), dupe, initial_count=1)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        # Because of how formsets work, the second form is expected to be a
        # tbird version range.  We got an error, so we're good.

    def test_require_appversion(self):
        old_av = self.version.apps.get()
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d['DELETE'] = True
        r = self.client.post(self.url, self.formset(d, initial_count=1))
        eq_(r.status_code, 200)
        eq_(r.context['compat_form'].non_form_errors(),
            ['Need at least one compatible application.'])
        eq_(self.version.apps.get(), old_av)

    def test_proper_min_max(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d['min'], d['max'] = d['max'], d['min']
        r = self.client.post(self.url, self.formset(d, initial_count=1))
        eq_(r.status_code, 200)
        eq_(r.context['compat_form'].forms[0].non_field_errors(),
            ['Invalid version range.'])


class TestSubmitBase(test_utils.TestCase):
    fixtures = ['base/addon_3615', 'base/addon_5579', 'base/users']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')

    def get_addon(self):
        return Addon.objects.no_cache().get(pk=3615)

    def get_step(self):
        return SubmitStep.objects.get(addon=self.get_addon())


class TestSubmitStep1(TestSubmitBase):

    def test_step1_submit(self):
        response = self.client.get(reverse('devhub.submit.1'))
        eq_(response.status_code, 200)
        doc = pq(response.content)
        assert len(response.context['agreement_text'])
        links = doc('#agreement-container a')
        assert len(links)
        for ln in links:
            href = ln.attrib['href']
            assert not href.startswith('%'), (
                "Looks like link %r to %r is still a placeholder" % (href,
                                                                     ln.text))


class TestSubmitStep2(test_utils.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='regular@mozilla.com', password='password')

    def test_step_2_with_cookie(self):
        r = self.client.post(reverse('devhub.submit.1'))
        self.assertRedirects(r, reverse('devhub.submit.2'))
        r = self.client.get(reverse('devhub.submit.2'))
        eq_(r.status_code, 200)

    def test_step_2_no_cookie(self):
        # We require a cookie that gets set in step 1.
        r = self.client.get(reverse('devhub.submit.2'), follow=True)
        self.assertRedirects(r, reverse('devhub.submit.1'))


class TestSubmitStep3(test_utils.TestCase):
    fixtures = ['base/addon_3615', 'base/addon_5579', 'base/users']

    def setUp(self):
        super(TestSubmitStep3, self).setUp()
        self.url = reverse('devhub.submit.3', args=[3615])
        assert self.client.login(username='del@icio.us', password='password')
        SubmitStep.objects.create(addon_id=3615, step=3)

    def test_submit(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

        # Post and be redirected.
        d = {'name': 'Test name',
             'slug': 'testname',
             'summary': 'Hello!'}
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        eq_(SubmitStep.objects.get(addon=3615).step, 4)

    def test_submit_name_required(self):
        # Make sure name is required.
        r = self.client.post(self.url, {'dummy': 'text'})
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_submit_name_length(self):
        # Make sure the name isn't too long.
        r = self.client.post(self.url, {'name': 'a' * 51})
        eq_(r.status_code, 200)
        error = 'Ensure this value has at most 50 characters (it has 51).'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_slug_invalid(self):
        # Submit an invalid slug.
        d = dict(slug='slug!!! aksl23%%')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'slug', "Enter a valid 'slug' " +
                    "consisting of letters, numbers, underscores or hyphens.")

    def test_submit_slug_required(self):
        # Make sure the slug is required.
        r = self.client.post(self.url, {'dummy': 'text'})
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'slug', 'This field is required.')

    def test_submit_summary_required(self):
        # Make sure summary is required.
        r = self.client.post(self.url, {'dummy': 'text'})
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'summary', 'This field is required.')

    def test_submit_summary_length(self):
        # Summary is too long.
        r = self.client.post(self.url, {'summary': 'a' * 251})
        eq_(r.status_code, 200)
        error = 'Ensure this value has at most 250 characters (it has 251).'
        self.assertFormError(r, 'form', 'summary', error)

class TestSubmitStep5(TestSubmitBase):

    def setUp(self):
        super(TestSubmitStep5, self).setUp()
        SubmitStep.objects.create(addon_id=3615, step=5)
        self.url = reverse('devhub.submit.5', args=[3615])
        self.next_step = reverse('devhub.submit.6', args=[3615])
        License.objects.create(builtin=3, on_form=True)

    def test_get(self):
        eq_(self.client.get(self.url).status_code, 200)

    def test_set_license(self):
        r = self.client.post(self.url, {'builtin': 3})
        self.assertRedirects(r, self.next_step)
        eq_(self.get_addon().current_version.license.builtin, 3)
        eq_(self.get_step().step, 6)

    def test_license_error(self):
        r = self.client.post(self.url, {'builtin': 4})
        eq_(r.status_code, 200)
        self.assertFormError(r, 'license_form', 'builtin',
                             'Select a valid choice. 4 is not one of '
                             'the available choices.')
        eq_(self.get_step().step, 5)

    def test_set_eula(self):
        r = self.client.post(self.url, dict(builtin=3, has_eula=True,
                                            eula='xxx'))
        self.assertRedirects(r, self.next_step)
        eq_(unicode(self.get_addon().eula), 'xxx')
        eq_(self.get_step().step, 6)


class TestSubmitStep6(TestSubmitBase):

    def setUp(self):
        super(TestSubmitStep6, self).setUp()
        SubmitStep.objects.create(addon_id=3615, step=6)
        self.url = reverse('devhub.submit.6', args=[3615])

    def test_get(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_require_review_type(self):
        r = self.client.post(self.url, {'dummy': 'text'})
        eq_(r.status_code, 200)
        self.assertFormError(r, 'review_type_form', 'review_type',
                             'A review type must be selected.')

    def test_bad_review_type(self):
        d = dict(review_type='jetsfool')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'review_type_form', 'review_type',
                             'Select a valid choice. jetsfool is not one of '
                             'the available choices.')

    def test_prelim_review(self):
        d = dict(review_type=amo.STATUS_UNREVIEWED)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        eq_(self.get_addon().status, amo.STATUS_UNREVIEWED)
        assert_raises(SubmitStep.DoesNotExist, self.get_step)

    def test_full_review(self):
        d = dict(review_type=amo.STATUS_NOMINATED)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        eq_(self.get_addon().status, amo.STATUS_NOMINATED)
        assert_raises(SubmitStep.DoesNotExist, self.get_step)


class TestSubmitStep7(TestSubmitBase):

    def test_finish_submitting_addon(self):
        addon = Addon.objects.get(
                        name__localized_string='Delicious Bookmarks')
        eq_(addon.current_version.supported_platforms, [amo.PLATFORM_ALL])

        response = self.client.get(reverse('devhub.submit.7', args=[3615]))
        eq_(response.status_code, 200)
        doc = pq(response.content)

        eq_(response.status_code, 200)
        eq_(response.context['addon'].name.localized_string,
            u"Delicious Bookmarks")

        abs_url = settings.SITE_URL + "/en-US/firefox/addon/3615/"
        eq_(doc("a#submitted-addon-url").text().strip(), abs_url)
        eq_(doc("a#submitted-addon-url").attr('href'),
            "/en-US/firefox/addon/3615/")

        next_steps = doc(".done-next-steps li a")

        # edit listing of freshly submitted add-on...
        eq_(next_steps[0].attrib['href'],
            reverse('devhub.addons.edit',
                    kwargs=dict(addon_id=addon.id)))

        # edit your developer profile...
        eq_(next_steps[1].attrib['href'],
            reverse('users.edit') + '#user-profile')

        # keep up with your add-on's activity feed:
        eq_(next_steps[2].attrib['href'], reverse('devhub.feed_all'))

        # view wait times:
        eq_(next_steps[3].attrib['href'],
            "https://forums.addons.mozilla.org/viewforum.php?f=21")

    def test_finish_submitting_platform_specific_addon(self):
        # mac-only Add-on:
        addon = Addon.objects.get(name__localized_string='Cooliris')
        AddonUser.objects.create(user=UserProfile.objects.get(pk=55021),
                                 addon=addon)
        response = self.client.get(reverse('devhub.submit.7', args=[5579]))
        eq_(response.status_code, 200)
        doc = pq(response.content)
        next_steps = doc(".done-next-steps li a")

        # upload more platform specific files...
        eq_(next_steps[0].attrib['href'],
            reverse('devhub.versions.edit', kwargs=dict(
                                addon_id=addon.id,
                                version_id=addon.current_version.id)))

        # edit listing of freshly submitted add-on...
        eq_(next_steps[1].attrib['href'],
            reverse('devhub.addons.edit',
                    kwargs=dict(addon_id=addon.id)))

    def test_finish_addon_for_prelim_review(self):
        addon = Addon.objects.get(pk=3615)
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()

        response = self.client.get(reverse('devhub.submit.7', args=[3615]))
        eq_(response.status_code, 200)
        doc = pq(response.content)
        exp = 'Your add-on has been submitted to the Preliminary Review queue'
        intro = doc('.addon-submission-process p').text()
        assert exp in intro, ('Unexpected intro: %s' % intro.strip())

    def test_finish_addon_for_full_review(self):
        addon = Addon.objects.get(pk=3615)
        addon.status = amo.STATUS_NOMINATED
        addon.save()

        response = self.client.get(reverse('devhub.submit.7', args=[3615]))
        eq_(response.status_code, 200)
        doc = pq(response.content)
        exp = 'Your add-on has been submitted to the Full Review queue'
        intro = doc('.addon-submission-process p').text()
        assert exp in intro, ('Unexpected intro: %s' % intro.strip())


class TestSubmitSteps(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')

    def assert_linked(self, doc, numbers):
        """Check that the nth <li> in the steps list is a link."""
        lis = doc('.submit-addon-progress li')
        eq_(len(lis), 7)
        for idx, li in enumerate(lis):
            links = pq(li)('a')
            if (idx + 1) in numbers:
                eq_(len(links), 1)
            else:
                eq_(len(links), 0)

    def assert_highlight(self, doc, num):
        """Check that the nth <li> is marked as .current."""
        lis = doc('.submit-addon-progress li')
        assert pq(lis[num - 1]).hasClass('current')
        eq_(len(pq('.current', lis)), 1)

    def test_step_1(self):
        r = self.client.get(reverse('devhub.submit.1'))
        eq_(r.status_code, 200)

    def test_on_step_6(self):
        # Hitting the step we're supposed to be on is a 200.
        SubmitStep.objects.create(addon_id=3615, step=6)
        r = self.client.get(reverse('devhub.submit.6',
                                    args=[3615]))
        eq_(r.status_code, 200)

    def test_skip_step_6(self):
        # We get bounced back to step 3.
        SubmitStep.objects.create(addon_id=3615, step=3)
        r = self.client.get(reverse('devhub.submit.6',
                                    args=[3615]), follow=True)
        self.assertRedirects(r, reverse('devhub.submit.3', args=[3615]))

    def test_all_done(self):
        # There's no SubmitStep, so we must be done.
        r = self.client.get(reverse('devhub.submit.6',
                                    args=[3615]), follow=True)
        self.assertRedirects(r, reverse('devhub.submit.7', args=[3615]))

    def test_menu_step_1(self):
        doc = pq(self.client.get(reverse('devhub.submit.1')).content)
        self.assert_linked(doc, [1])
        self.assert_highlight(doc, 1)

    def test_menu_step_2(self):
        r = self.client.post(reverse('devhub.submit.1'))
        doc = pq(self.client.get(reverse('devhub.submit.2')).content)
        self.assert_linked(doc, [1, 2])
        self.assert_highlight(doc, 2)

    def test_menu_step_3(self):
        SubmitStep.objects.create(addon_id=3615, step=3)
        url = reverse('devhub.submit.3', args=[3615])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [3])
        self.assert_highlight(doc, 3)

    def test_menu_step_3_from_6(self):
        SubmitStep.objects.create(addon_id=3615, step=6)
        url = reverse('devhub.submit.3', args=[3615])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [3, 4, 5, 6])
        self.assert_highlight(doc, 3)

    def test_menu_step_6(self):
        SubmitStep.objects.create(addon_id=3615, step=6)
        url = reverse('devhub.submit.6', args=[3615])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [3, 4, 5, 6])
        self.assert_highlight(doc, 6)

    def test_menu_step_7(self):
        url = reverse('devhub.submit.7', args=[3615])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [])
        self.assert_highlight(doc, 7)
