# -*- coding: utf8 -*-
import json
import os
import re
import shutil
import socket
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal

from django import forms
from django.conf import settings
from django.utils import translation

import mock
from nose.tools import eq_, assert_not_equal, assert_raises
from nose.plugins.attrib import attr
from PIL import Image
from pyquery import PyQuery as pq
from redisutils import mock_redis, reset_redis
import test_utils

import amo
import files.tests
import paypal
from amo.urlresolvers import reverse
from amo.tests.test_helpers import get_image_path
from addons import cron
from addons.forms import AddonFormBasic
from addons.models import Addon, AddonUser, Charity, Category, AddonCategory
from addons.utils import ReverseNameLookup
from applications.models import Application, AppVersion
from devhub.forms import ContribForm, LicenseForm
from devhub.models import ActivityLog, SubmitStep
from files.models import File, FileUpload, Platform, FileValidation
from reviews.models import Review
from tags.models import Tag, AddonTag
from users.models import UserProfile
from versions.models import ApplicationsVersions, License, Version


def assert_no_validation_errors(validation):
    """Assert that the validation (JSON) does not contain a traceback.

    Note that this does not test whether the addon passed
    validation or not.
    """
    if hasattr(validation, 'task_error'):
        # FileUpload object:
        error = validation.task_error
    else:
        # Upload detail - JSON output
        error = validation['error']
    if error:
        print '-' * 70
        print error
        print '-' * 70
        raise AssertionError("Unexpected task error: %s" %
                             error.rstrip().split("\n")[-1])


def assert_close_to_now(dt):
    """
    Compare a datetime with datetime.now, with resolution up to the minute.
    """
    eq_(dt.timetuple()[:5], datetime.now().timetuple()[:5])


class HubTest(test_utils.TestCase):
    fixtures = ['browse/nameless-addon', 'base/users']

    def setUp(self):
        translation.activate('en-US')
        self.url = reverse('devhub.index')
        self.login_as_developer()
        eq_(self.client.get(self.url).status_code, 200)
        self.user_profile = UserProfile.objects.get(id=999)

    def login_as_developer(self):
        self.client.login(username='regular@mozilla.com', password='password')

    def clone_addon(self, num, addon_id=57132):
        ids = []
        for i in range(num):
            addon = Addon.objects.get(id=addon_id)
            addon.id = addon.guid = None
            addon.save()
            AddonUser.objects.create(user=self.user_profile, addon=addon)
            new_addon = Addon.objects.get(id=addon.id)
            new_addon.name = str(addon.id)
            new_addon.save()
            ids.append(addon.id)
        return ids


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
        edit_url = reverse('devhub.addons.edit', args=[addon.slug])
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

    def get_action_links(self, addon_id):
        r = self.client.get(self.url)
        doc = pq(r.content)
        links = [a.text.strip() for a in
                 doc('.item[data-addonid=%s] .item-actions li > a' % addon_id)]
        return links

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('.item item').length, 0)

    def test_addon_pagination(self):
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

    def test_show_hide_statistics(self):
        a_pk = self.clone_addon(1)[0]

        # when Active and Public show statistics
        Addon.objects.get(pk=a_pk).update(disabled_by_user=False,
                                          status=amo.STATUS_PUBLIC)
        links = self.get_action_links(a_pk)
        assert 'Statistics' in links, ('Unexpected: %r' % links)

        # when Active and Incomplete hide statistics
        Addon.objects.get(pk=a_pk).update(disabled_by_user=False,
                                          status=amo.STATUS_NULL)
        links = self.get_action_links(a_pk)
        assert 'Statistics' not in links, ('Unexpected: %r' % links)

    def test_complete_addon_item(self):
        a_pk = self.clone_addon(1)[0]
        a = Addon.objects.get(pk=a_pk)
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(a.status, amo.STATUS_PUBLIC)
        assert doc('.item[data-addonid=%s] ul.item-details' % a_pk)
        assert doc('.item[data-addonid=%s] h4 a' % a_pk)
        assert not doc('.item[data-addonid=%s] > p' % a_pk)

    def test_incomplete_addon_item(self):
        a_pk = self.clone_addon(1)[0]
        Addon.objects.get(pk=a_pk).update(status=amo.STATUS_NULL)
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert not doc('.item[data-addonid=%s] ul.item-details' % a_pk)
        assert not doc('.item[data-addonid=%s] h4 a' % a_pk)
        assert doc('.item[data-addonid=%s] > p' % a_pk)


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
        assert not doc('.item[data-addonid=4594] li.compat')
        a = Addon.objects.get(pk=4594)
        r = self.client.get(reverse('devhub.ajax.compat.update',
                                    args=[a.slug, a.current_version.id]))
        eq_(r.status_code, 404)
        r = self.client.get(reverse('devhub.ajax.compat.status',
                                    args=[a.slug]))
        eq_(r.status_code, 404)

    def test_compat(self):
        a = Addon.objects.get(pk=3615)
        assert self.client.login(username='del@icio.us', password='password')

        r = self.client.get(self.url)
        doc = pq(r.content)
        cu = doc('.item[data-addonid=3615] .tooltip.compat-update')
        assert cu

        update_url = reverse('devhub.ajax.compat.update',
                             args=[a.slug, a.current_version.id])
        eq_(cu.attr('data-updateurl'), update_url)

        status_url = reverse('devhub.ajax.compat.status', args=[a.slug])
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


def formset(*args, **kw):
    """
    Build up a formset-happy POST.

    *args is a sequence of forms going into the formset.
    prefix and initial_count can be set in **kw.
    """
    prefix = kw.pop('prefix', 'form')
    total_count = kw.pop('total_count', len(args))
    initial_count = kw.pop('initial_count', len(args))
    data = {prefix + '-TOTAL_FORMS': total_count,
            prefix + '-INITIAL_FORMS': initial_count}
    for idx, d in enumerate(args):
        data.update(('%s-%s-%s' % (prefix, idx, k), v)
                    for k, v in d.items())
    data.update(kw)
    return data


class TestDevRequired(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.get_url = reverse('devhub.addons.payments', args=['a3615'])
        self.post_url = reverse('devhub.addons.payments.disable',
                                args=['a3615'])
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

    def test_disabled_post_dev(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        eq_(self.client.post(self.get_url).status_code, 403)

    def test_disabled_post_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.assertRedirects(self.client.post(self.post_url), self.get_url)


class TestOwnership(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.url = reverse('devhub.addons.owner', args=['a3615'])
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
                                              url='license.url', on_form=True)

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
        eq_(ActivityLog.objects.filter(
            action=amo.LOG.CHANGE_LICENSE.id).count(), 1)

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

    def test_license_details_links(self):
        # Check that builtin licenses get details links.
        doc = pq(unicode(LicenseForm()))
        for license in License.objects.builtins():
            radio = 'input.license[value=%s]' % license.builtin
            eq_(doc(radio).parent().text(), unicode(license.name) + ' Details')
            eq_(doc(radio + '+ a').attr('href'), license.url)
        eq_(doc('input[name=builtin]:last-child').parent().text(), 'Other')

    def test_license_logs(self):
        data = self.formset(builtin=License.OTHER, text='text')
        self.version.files.all().delete()
        self.version.addon.update(status=amo.STATUS_PUBLIC)
        self.client.post(self.url, data)
        eq_(ActivityLog.objects.all().count(), 2)

        self.version.license = License.objects.all()[1]
        self.version.save()

        data = self.formset(builtin=License.OTHER, text='text')
        self.client.post(self.url, data)
        eq_(ActivityLog.objects.all().count(), 3)


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


class TestVersionStats(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def test_counts(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        user = UserProfile.objects.get(email='admin@mozilla.com')
        for _ in range(10):
            Review.objects.create(addon=addon, user=user,
                                  version=addon.current_version)

        url = reverse('devhub.versions.stats', args=[addon.slug])
        r = json.loads(self.client.get(url).content)
        exp = {str(version.id):
               {'reviews': 10, 'files': 1, 'version': version.version,
                'id': version.id}}
        self.assertDictEqual(r, exp)


class TestEditPayments(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = self.get_addon()
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.foundation = Charity.objects.create(
            id=amo.FOUNDATION_ORG, name='moz', url='$$.moz', paypal='moz.pal')
        self.url = reverse('devhub.addons.payments', args=[self.addon.slug])
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
                             'PayPal ID required to accept contributions.')

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

    def test_neg_suggested_amount(self):
        msg = 'Please enter a suggested amount greater than 0.'
        r = self.client.post(self.url, {'suggested_amount': -1})
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

    def test_require_public_status_to_edit(self):
        # pyquery drops all the attributes on <body> so we just go
        # for string search.
        assert 'no-edit' not in self.client.get(self.url).content
        self.get_addon().update(status=amo.STATUS_LITE)
        assert 'no-edit' in self.client.get(self.url).content


class TestDisablePayments(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.addon.update(wants_contributions=True, paypal_id='woohoo')
        self.pay_url = reverse('devhub.addons.payments',
                               args=[self.addon.slug])
        self.disable_url = reverse('devhub.addons.payments.disable',
                                   args=[self.addon.slug])
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
        self.url = reverse('devhub.addons.payments', args=[self.addon.slug])
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
        assert doc('#trans-the_reason')
        assert doc('#trans-the_future')

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
        assert not doc('#trans-the_reason')
        assert not doc('#trans-the_future')

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
            assert doc('#trans-the_reason')
            assert doc('#trans-the_future')

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
        self.url = reverse('devhub.addons.delete', args=[self.addon.slug])

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
    fixtures = ('base/apps', 'base/users', 'base/addon_3615',
                'base/addon_5579', 'base/addon_3615_categories')

    def setUp(self):
        super(TestEdit, self).setUp()
        addon = self.get_addon()
        assert self.client.login(username='del@icio.us', password='password')
        self.url = reverse('devhub.addons.edit', args=[addon.slug])
        self.user = UserProfile.objects.get(pk=55021)

        AddonCategory.objects.filter(addon=addon,
                category=Category.objects.get(id=23)).delete()
        AddonCategory.objects.filter(addon=addon,
                category=Category.objects.get(id=24)).delete()

        self.tags = ['tag3', 'tag2', 'tag1']
        for t in self.tags:
            Tag(tag_text=t).save_tag(addon)
        self._redis = mock_redis()

        self.addon = self.get_addon()

        self.old_settings = {
            'preview': settings.PREVIEW_THUMBNAIL_PATH,
            'icons': settings.ADDON_ICONS_PATH,
        }
        settings.PREVIEW_THUMBNAIL_PATH = tempfile.mkstemp()[1] + '%s/%d.png'
        settings.ADDON_ICONS_PATH = tempfile.mkdtemp()

        self.basic_url = self.get_url('basic', True)
        ctx = self.client.get(self.basic_url).context['cat_form']
        self.cat_initial = initial(ctx.initial_forms[0])
        self.preview_upload = reverse('devhub.addons.upload_preview',
                                      args=[self.addon.slug])
        self.icon_upload = reverse('devhub.addons.upload_icon',
                                   args=[self.addon.slug])

    def tearDown(self):
        reset_redis(self._redis)
        settings.PREVIEW_THUMBNAIL_PATH = self.old_settings['preview']
        settings.ADDON_ICONS_PATH = self.old_settings['icons']

    def formset_new_form(self, *args, **kw):
        ctx = self.client.get(self.get_url('media', True)).context

        blank = initial(ctx['preview_form'].forms[-1])
        blank.update(**kw)
        return blank

    def formset_media(self, *args, **kw):
        kw.setdefault('initial_count', 0)
        kw.setdefault('prefix', 'files')

        fs = formset(*[a for a in args] + [self.formset_new_form()], **kw)
        return dict([(k, '' if v is None else v) for k, v in fs.items()])

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def get_url(self, section, edit=False):
        args = [self.addon.slug, section]
        if edit:
            args.append('edit')
        return reverse('devhub.addons.section', args=args)

    def test_redirect(self):
        # /addon/:id => /addon/:id/edit
        r = self.client.get('/en-US/developers/addon/3615/', follow=True)
        url = reverse('devhub.addons.edit', args=['a3615'])
        self.assertRedirects(r, url, 301)

    def get_dict(self, **kw):
        fs = formset(self.cat_initial, initial_count=1)
        result = {'name': 'new name', 'slug': 'test_slug',
                  'summary': 'new summary',
                  'tags': ', '.join(self.tags)}
        result.update(**kw)
        result.update(fs)
        return result

    def test_edit_basic(self):
        old_name = self.addon.name
        data = self.get_dict()

        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)
        addon = self.get_addon()

        eq_(unicode(addon.name), data['name'])
        eq_(addon.name.id, old_name.id)

        eq_(unicode(addon.slug), data['slug'])
        eq_(unicode(addon.summary), data['summary'])

        eq_([unicode(t) for t in addon.tags.all()], sorted(self.tags))

    def test_edit_basic_check_description(self):
        # Make sure bug 629779 doesn't return.
        old_desc = self.addon.description
        data = self.get_dict()

        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)
        addon = self.get_addon()

        eq_(addon.description, old_desc)

    def test_edit_slug_invalid(self):
        old_edit = self.get_url('basic', True)
        data = self.get_dict(name='', slug='invalid')
        r = self.client.post(self.get_url('basic', True), data)
        doc = pq(r.content)
        eq_(doc('form').attr('action'), old_edit)

    def test_edit_slug_valid(self):
        old_edit = self.get_url('basic', True)
        data = self.get_dict(slug='valid')
        r = self.client.post(self.get_url('basic', True), data)
        doc = pq(r.content)
        assert doc('form').attr('action') != old_edit

    def test_edit_summary_escaping(self):
        data = self.get_dict()
        data['summary'] = '<b>oh my</b>'
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        # Fetch the page so the LinkifiedTranslation gets in cache.
        r = self.client.get(reverse('devhub.addons.edit', args=[data['slug']]))
        eq_(pq(r.content)('[data-name=summary]').html().strip(),
            '<span lang="en-us">&lt;b&gt;oh my&lt;/b&gt;</span>')

        # Now make sure we don't have escaped content in the rendered form.
        form = AddonFormBasic(instance=self.get_addon(), request=object())
        eq_(pq('<body>%s</body>' % form['summary'])('[lang="en-us"]').html(),
            '<b>oh my</b>')

    def test_edit_basic_as_developer(self):
        self.client.login(username='regular@mozilla.com', password='password')
        data = self.get_dict()
        r = self.client.post(self.get_url('basic', True), data)
        # Make sure we get errors when they are just regular users.
        eq_(r.status_code, 403)

        devuser = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.get_addon(), user=devuser,
                                 role=amo.AUTHOR_ROLE_DEV)
        r = self.client.post(self.get_url('basic', True), data)

        eq_(r.status_code, 200)
        addon = self.get_addon()

        eq_(unicode(addon.name), data['name'])

        eq_(unicode(addon.slug), data['slug'])
        eq_(unicode(addon.summary), data['summary'])

        eq_([unicode(t) for t in addon.tags.all()], sorted(self.tags))

    def test_edit_basic_name_required(self):
        data = self.get_dict(name='', slug='test_addon')
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_basic_name_spaces(self):
        data = self.get_dict(name='    ', slug='test_addon')
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_basic_slugs_unique(self):
        Addon.objects.get(id=5579).update(slug='test_slug')
        data = self.get_dict()
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'slug', 'This slug is already in use.')

    def test_edit_basic_add_tag(self):
        count = ActivityLog.objects.all().count()
        self.tags.insert(0, 'tag4')
        data = self.get_dict()
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        result = pq(r.content)('#addon_tags_edit').eq(0).text()

        eq_(result, ', '.join(sorted(self.tags)))
        eq_((ActivityLog.objects.for_addons(self.addon)
             .get(action=amo.LOG.ADD_TAG.id)).to_string(),
            '<a href="/en-US/firefox/tag/tag4">tag4</a> added to '
            '<a href="/en-US/firefox/addon/test_slug/">new name</a>.')
        eq_(ActivityLog.objects.filter(action=amo.LOG.ADD_TAG.id).count(),
                                        count + 1)

    def test_edit_basic_blacklisted_tag(self):
        Tag.objects.get_or_create(tag_text='blue', blacklisted=True)
        data = self.get_dict(tags='blue')
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        error = 'Invalid tag: blue'
        self.assertFormError(r, 'form', 'tags', error)

    def test_edit_basic_blacklisted_tags_2(self):
        Tag.objects.get_or_create(tag_text='blue', blacklisted=True)
        Tag.objects.get_or_create(tag_text='darn', blacklisted=True)
        data = self.get_dict(tags='blue, darn, swearword')
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        error = 'Invalid tags: blue, darn'
        self.assertFormError(r, 'form', 'tags', error)

    def test_edit_basic_blacklisted_tags_3(self):
        Tag.objects.get_or_create(tag_text='blue', blacklisted=True)
        Tag.objects.get_or_create(tag_text='darn', blacklisted=True)
        Tag.objects.get_or_create(tag_text='swearword', blacklisted=True)
        data = self.get_dict(tags='blue, darn, swearword')
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        error = 'Invalid tags: blue, darn, swearword'
        self.assertFormError(r, 'form', 'tags', error)

    def test_edit_basic_remove_tag(self):
        self.tags.remove('tag2')

        count = ActivityLog.objects.all().count()
        data = self.get_dict()
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        result = pq(r.content)('#addon_tags_edit').eq(0).text()

        eq_(result, ', '.join(sorted(self.tags)))

        eq_(ActivityLog.objects.filter(action=amo.LOG.REMOVE_TAG.id).count(),
            count + 1)

    def test_edit_basic_minlength_tags(self):
        tags = self.tags
        tags.append('a' * (amo.MIN_TAG_LENGTH - 1))
        data = self.get_dict()
        r = self.client.post(self.get_url('basic', True), data)
        eq_(r.status_code, 200)

        self.assertFormError(r, 'form', 'tags',
                             'All tags must be at least %d characters.' %
                             amo.MIN_TAG_LENGTH)

    def test_edit_basic_max_tags(self):
        tags = self.tags

        for i in range(amo.MAX_TAGS + 1):
            tags.append('test%d' % i)

        data = self.get_dict()
        r = self.client.post(self.get_url('basic', True), data)
        self.assertFormError(r, 'form', 'tags', 'You have %d too many tags.' %
                                                 (len(tags) - amo.MAX_TAGS))

    def test_edit_tag_empty_after_slug(self):
        start = Tag.objects.all().count()
        data = self.get_dict(tags='>>')
        self.client.post(self.get_url('basic', True), data)

        # Check that the tag did not get created.
        eq_(start, Tag.objects.all().count())

    def test_edit_tag_slugified(self):
        data = self.get_dict(tags='<script>alert("foo")</script>')
        self.client.post(self.get_url('basic', True), data)
        tag = Tag.objects.all().order_by('-pk')[0]
        eq_(tag.tag_text, 'scriptalertfooscript')

    def test_edit_basic_categories_add(self):
        eq_([c.id for c in self.get_addon().all_categories], [22])
        self.cat_initial['categories'] = [22, 23]

        self.client.post(self.basic_url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        eq_(sorted(addon_cats), [22, 23])

    def test_edit_basic_categories_addandremove(self):
        AddonCategory(addon=self.addon, category_id=23).save()
        eq_([c.id for c in self.get_addon().all_categories], [22, 23])

        self.cat_initial['categories'] = [22, 24]
        self.client.post(self.basic_url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        eq_(sorted(addon_cats), [22, 24])

    def test_edit_basic_categories_xss(self):
        c = Category.objects.get(id=22)
        c.name = '<script>alert("test");</script>'
        c.save()

        self.cat_initial['categories'] = [22, 24]
        r = self.client.post(self.basic_url, formset(self.cat_initial,
                                                     initial_count=1))

        assert '<script>alert' not in r.content
        assert '&lt;script&gt;alert' in r.content

    def test_edit_basic_categories_remove(self):
        c = Category.objects.get(id=23)
        AddonCategory(addon=self.addon, category=c).save()
        eq_([c.id for c in self.get_addon().all_categories], [22, 23])

        self.cat_initial['categories'] = [22]
        self.client.post(self.basic_url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        eq_(sorted(addon_cats), [22])

    def test_edit_basic_categories_required(self):
        del self.cat_initial['categories']
        r = self.client.post(self.basic_url, formset(self.cat_initial,
                                                     initial_count=1))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['This field is required.'])

    def test_edit_basic_categories_max(self):
        eq_(amo.MAX_CATEGORIES, 2)
        self.cat_initial['categories'] = [22, 23, 24]
        r = self.client.post(self.basic_url, formset(self.cat_initial,
                                                     initial_count=1))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['You can have only 2 categories.'])

    def test_edit_basic_categories_other_failure(self):
        Category.objects.get(id=22).update(misc=True)
        self.cat_initial['categories'] = [22, 23]
        r = self.client.post(self.basic_url, formset(self.cat_initial,
                                                     initial_count=1))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['The miscellaneous category cannot be combined with additional '
             'categories.'])

    def test_edit_basic_categories_nonexistent(self):
        self.cat_initial['categories'] = [100]
        r = self.client.post(self.basic_url, formset(self.cat_initial,
                                                     initial_count=1))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['Select a valid choice. 100 is not one of the available '
             'choices.'])

    def test_edit_basic_name_not_empty(self):
        data = self.get_dict(name='', slug=self.addon.slug,
                             summary=self.addon.summary)
        r = self.client.post(self.get_url('basic', True), data)
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_edit_basic_name_max_length(self):
        data = self.get_dict(name='xx' * 70, slug=self.addon.slug,
                             summary=self.addon.summary)
        r = self.client.post(self.get_url('basic', True), data)
        self.assertFormError(r, 'form', 'name',
                             'Ensure this value has at most 50 '
                             'characters (it has 140).')

    def test_edit_basic_summary_max_length(self):
        data = self.get_dict(name=self.addon.name, slug=self.addon.slug,
                             summary='x' * 251)
        r = self.client.post(self.get_url('basic', True), data)
        self.assertFormError(r, 'form', 'summary',
                             'Ensure this value has at most 250 '
                             'characters (it has 251).')

    def test_edit_details(self):
        data = dict(description='New description with <em>html</em>!',
                    default_locale='en-US',
                    homepage='http://twitter.com/fligtarsmom')

        r = self.client.post(self.get_url('details', True), data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_details_xss(self):
        """
        Let's try to put xss in our description, and safe html, and verify
        that we are playing safe.
        """
        self.addon.description = ("This\n<b>IS</b>"
                                  "<script>alert('awesome')</script>")
        self.addon.save()
        r = self.client.get(reverse('devhub.addons.edit',
                                    args=[self.addon.slug]))
        doc = pq(r.content)
        eq_(doc('#edit-addon-details span[lang]').html(),
                "This<br/><b>IS</b>&lt;script&gt;alert('awesome')"
                '&lt;/script&gt;')

    def test_edit_basic_homepage_optional(self):
        data = dict(description='New description with <em>html</em>!',
                    default_locale='en-US', homepage='')

        r = self.client.post(self.get_url('details', True), data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_default_locale_required_trans(self):
        # name, summary, and description are required in the new locale.
        description, homepage = map(unicode, [self.addon.description,
                                              self.addon.homepage])
        # TODO: description should get fixed up with the form.
        fields = ['description', 'name', 'summary']
        error = ('Before changing your default locale you must have a name, '
                 'summary, and description in that locale. '
                 'You are missing %s.')
        missing = lambda f: error % ', '.join(map(repr, f))

        d = dict(description=description, homepage=homepage,
                 default_locale='fr')
        r = self.client.post(self.get_url('details', True), d)
        self.assertFormError(r, 'form', None, missing(fields))

        # Now we have a name.
        self.addon.name = {'fr': 'fr name'}
        self.addon.save()
        fields.remove('name')
        r = self.client.post(self.get_url('details', True), d)
        self.assertFormError(r, 'form', None, missing(fields))

        # Now we have a summary.
        self.addon.summary = {'fr': 'fr summary'}
        self.addon.save()
        fields.remove('summary')
        r = self.client.post(self.get_url('details', True), d)
        self.assertFormError(r, 'form', None, missing(fields))

        # Now we're sending an fr description with the form.
        d['description_fr'] = 'fr description'
        r = self.client.post(self.get_url('details', True), d)
        eq_(r.context['form'].errors, {})

    def test_edit_default_locale_frontend_error(self):
        d = dict(description='xx', homepage='yy', default_locale='fr')
        r = self.client.post(self.get_url('details', True), d)
        self.assertContains(r, 'Before changing your default locale you must')

    def test_edit_details_locale(self):
        addon = self.get_addon()
        addon.update(default_locale='en-US')

        r = self.client.get(self.get_url('details', False))

        eq_(pq(r.content)('.addon_edit_locale').eq(0).text(), "English (US)")

    def test_edit_details_restricted_tags(self):
        addon = self.get_addon()
        tag = Tag.objects.create(tag_text='restartless', restricted=True)
        AddonTag.objects.create(tag=tag, addon=addon)

        res = self.client.get(self.get_url('basic', True))
        divs = pq(res.content)('#addon_tags_edit .edit-addon-details')
        eq_(len(divs), 2)
        assert 'restartless' in divs.eq(1).text()

    def test_edit_support(self):
        data = dict(support_email='sjobs@apple.com',
                    support_url='http://apple.com/')

        r = self.client.post(self.get_url('support', True), data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_support_getsatisfaction(self):
        urls = [("http://getsatisfaction.com/abc/products/def", 'abcdef'),
                ("http://getsatisfaction.com/abc/", 'abc'),  # No company
                ("http://google.com", None)]  # Delete GS

        for (url, val) in urls:
            data = dict(support_email='abc@def.com',
                        support_url=url)

            r = self.client.post(self.get_url('support', True), data)
            eq_(r.context['form'].errors, {})

            result = pq(r.content)('.addon_edit_gs').eq(0).text()
            doc = pq(r.content)
            result = doc('.addon_edit_gs').eq(0).text()

            result = re.sub('\W', '', result) if result else None

            eq_(result, val)

    def test_edit_support_optional_url(self):
        data = dict(support_email='sjobs@apple.com',
                    support_url='')

        r = self.client.post(self.get_url('support', True), data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_support_optional_email(self):
        data = dict(support_email='',
                    support_url='http://apple.com/')

        r = self.client.post(self.get_url('support', True), data)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_media_defaulticon(self):
        data = dict(icon_type='')
        data_formset = self.formset_media(**data)

        r = self.client.post(self.get_url('media', True), data_formset)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/default-64.png')

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_media_preuploadedicon(self):
        data = dict(icon_type='icon/appearance')
        data_formset = self.formset_media(**data)

        r = self.client.post(self.get_url('media', True), data_formset)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/appearance-64.png')

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_media_uploadedicon(self):
        img = "%s/img/amo2009/tab-mozilla.png" % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(**data)

        r = self.client.post(self.get_url('media', True), data_formset)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        url = addon.get_icon_url(64)
        assert ('addon_icon/%s' % addon.id) in url, (
                                                "Unexpected path: %r" % url)

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-32.png' % addon.id)

        assert os.path.exists(dest)

        eq_(Image.open(dest).size, (32, 12))

    def test_edit_media_icon_log(self):
        self.test_edit_media_uploadedicon()
        log = ActivityLog.objects.all()
        eq_(log.count(), 1)
        eq_(log[0].action, amo.LOG.CHANGE_ICON.id)

    def test_edit_media_uploadedicon_noresize(self):
        img = "%s/img/amo2009/notifications/error.png" % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(**data)

        r = self.client.post(self.get_url('media', True), data_formset)
        eq_(r.context['form'].errors, {})
        addon = self.get_addon()

        url = addon.get_icon_url(64)
        assert ('addon_icon/%s' % addon.id) in url, (
                                                "Unexpected path: %r" % url)

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-64.png' % addon.id)

        assert os.path.exists(dest)

        eq_(Image.open(dest).size, (48, 48))

    def test_edit_media_uploadedicon_wrongtype(self):
        img = "%s/js/zamboni/devhub.js" % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = {'upload_image': src_image}

        res = self.client.post(self.preview_upload, data)
        response_json = json.loads(res.content)

        eq_(response_json['errors'][0], u'Icons must be either PNG or JPG.')

    def setup_image_status(self):
        addon = self.get_addon()
        self.icon_dest = os.path.join(addon.get_icon_dir(),
                                      '%s-32.png' % addon.id)
        os.makedirs(os.path.dirname(self.icon_dest))
        open(self.icon_dest, 'w')

        self.preview = addon.previews.create()
        self.preview.save()
        os.makedirs(os.path.dirname(self.preview.thumbnail_path))
        open(self.preview.thumbnail_path, 'w')

        self.url = reverse('devhub.ajax.image.status', args=[addon.slug])

    def test_image_status_no_choice(self):
        addon = self.get_addon()
        addon.update(icon_type='')
        url = reverse('devhub.ajax.image.status', args=[addon.slug])
        result = json.loads(self.client.get(url).content)
        assert result['icons']

    def test_image_status_works(self):
        self.setup_image_status()
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_image_status_fails(self):
        self.setup_image_status()
        os.remove(self.icon_dest)
        result = json.loads(self.client.get(self.url).content)
        assert not result['icons']

    def test_preview_status_works(self):
        self.setup_image_status()
        result = json.loads(self.client.get(self.url).content)
        assert result['previews']

        # No previews means that all the images are done.
        self.addon.previews.all().delete()
        result = json.loads(self.client.get(self.url).content)
        assert result['previews']

    def test_preview_status_fails(self):
        self.setup_image_status()
        os.remove(self.preview.thumbnail_path)
        result = json.loads(self.client.get(self.url).content)
        assert not result['previews']

    def test_image_status_persona(self):
        self.setup_image_status()
        os.remove(self.icon_dest)
        self.get_addon().update(type=amo.ADDON_PERSONA)
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_image_status_default(self):
        self.setup_image_status()
        os.remove(self.icon_dest)
        self.get_addon().update(icon_type='icon/photos')
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_icon_animated(self):
        filehandle = open(get_image_path('animated.png'), 'rb')
        data = {'upload_image': filehandle}

        res = self.client.post(self.preview_upload, data)
        response_json = json.loads(res.content)

        eq_(response_json['errors'][0], u'Icons cannot be animated.')

    def preview_add(self, amount=1):
        img = "%s/img/amo2009/tab-mozilla.png" % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)
        data_formset = self.formset_media(**data)
        url = self.preview_upload

        r = self.client.post(url, data_formset)

        details = json.loads(r.content)
        upload_hash = details['upload_hash']

        # Create and post with the formset.
        fields = []
        for i in range(amount):
            fields.append(self.formset_new_form(caption='hi',
                                                upload_hash=upload_hash,
                                                position=i))
        data_formset = self.formset_media(*fields)

        self.get_url('media', True)

        r = self.client.post(self.get_url('media', True), data_formset)

    def test_edit_media_preview_add(self):
        self.preview_add()

        eq_(str(self.get_addon().previews.all()[0].caption), 'hi')

    def test_edit_media_preview_edit(self):
        self.preview_add()
        preview = self.get_addon().previews.all()[0]
        edited = {'caption': 'bye',
                  'upload_hash': '',
                  'id': preview.id,
                  'position': preview.position,
                  'file_upload': None}

        data_formset = self.formset_media(edited, initial_count=1)

        self.client.post(self.get_url('media', True), data_formset)

        eq_(str(self.get_addon().previews.all()[0].caption), 'bye')
        eq_(len(self.get_addon().previews.all()), 1)

    def test_edit_media_preview_reorder(self):
        self.preview_add(3)

        previews = self.get_addon().previews.all()

        base = dict(upload_hash='', file_upload=None)

        # Three preview forms were generated; mix them up here.
        a = dict(caption="first", position=1, id=previews[2].id)
        b = dict(caption="second", position=2, id=previews[0].id)
        c = dict(caption="third", position=3, id=previews[1].id)
        a.update(base)
        b.update(base)
        c.update(base)

        # Add them in backwards ("third", "second", "first")
        data_formset = self.formset_media(c, b, a, initial_count=3)
        eq_(data_formset['files-0-caption'], 'third')
        eq_(data_formset['files-1-caption'], 'second')
        eq_(data_formset['files-2-caption'], 'first')

        self.client.post(self.get_url('media', True), data_formset)

        # They should come out "first", "second", "third"
        eq_(self.get_addon().previews.all()[0].caption, 'first')
        eq_(self.get_addon().previews.all()[1].caption, 'second')
        eq_(self.get_addon().previews.all()[2].caption, 'third')

    def test_edit_media_preview_delete(self):
        self.preview_add()
        preview = self.get_addon().previews.get()
        edited = {'DELETE': 'checked',
                  'upload_hash': '',
                  'id': preview.id,
                  'position': 0,
                  'file_upload': None}

        data_formset = self.formset_media(edited, initial_count=1)

        self.client.post(self.get_url('media', True), data_formset)

        eq_(len(self.get_addon().previews.all()), 0)

    def test_edit_media_preview_add_another(self):
        self.preview_add()
        self.preview_add()

        eq_(len(self.get_addon().previews.all()), 2)

    def test_edit_media_preview_add_two(self):
        self.preview_add(2)

        eq_(len(self.get_addon().previews.all()), 2)

    def test_log(self):
        data = {'developer_comments': 'This is a test'}
        o = ActivityLog.objects
        eq_(o.count(), 0)
        r = self.client.post(self.get_url('technical', True), data)
        eq_(r.context['form'].errors, {})
        eq_(o.filter(action=amo.LOG.EDIT_PROPERTIES.id).count(), 1)

    def test_technical_on(self):
        # Turn everything on
        data = dict(developer_comments='Test comment!',
                    binary='on',
                    external_software='on',
                    site_specific='on',
                    view_source='on')

        r = self.client.post(self.get_url('technical', True), data)
        eq_(r.context['form'].errors, {})

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

    def test_technical_devcomment_notrequired(self):
        data = dict(developer_comments='',
                    binary='on',
                    external_software='on',
                    site_specific='on',
                    view_source='on')

        r = self.client.post(self.get_url('technical', True), data)
        eq_(r.context['form'].errors, {})

        addon = self.get_addon()
        for k in data:
            if k == 'developer_comments':
                eq_(unicode(getattr(addon, k)), unicode(data[k]))
            else:
                eq_(getattr(addon, k), True if data[k] == 'on' else False)

    def test_nav_links(self):
        url = reverse('devhub.addons.edit', args=['a3615'])
        activity_url = reverse('devhub.feed', args=['a3615'])
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(doc('#edit-addon-nav ul:last').find('li a').eq(1).attr('href'),
            activity_url)

    def get_l10n_urls(self):
        paths = ('devhub.addons.edit', 'devhub.addons.profile',
                 'devhub.addons.payments', 'devhub.addons.owner')
        return [reverse(p, args=['a3615']) for p in paths]

    def test_l10n(self):
        Addon.objects.get(id=3615).update(default_locale='en-US')
        for url in self.get_l10n_urls():
            r = self.client.get(url)
            eq_(pq(r.content)('#l10n-menu').attr('data-default'), 'en-us')

    def test_l10n_not_us(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            r = self.client.get(url)
            eq_(pq(r.content)('#l10n-menu').attr('data-default'), 'fr')

    def test_l10n_not_us_id_url(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            url = '/id' + url[6:]
            r = self.client.get(url)
            eq_(pq(r.content)('#l10n-menu').attr('data-default'), 'fr')


class TestActivityFeed(test_utils.TestCase):
    fixtures = ('base/apps', 'base/users', 'base/addon_3615')

    def setUp(self):
        super(TestActivityFeed, self).setUp()
        assert self.client.login(username='del@icio.us', password='password')

    def test_feed_for_all(self):
        r = self.client.get(reverse('devhub.feed_all'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('header h2').text(),
            'Recent Activity for My Add-ons')
        eq_(doc('.breadcrumbs li:eq(2)').text(),
            'Recent Activity')

    def test_feed_for_addon(self):
        addon = Addon.objects.no_cache().get(id=3615)
        r = self.client.get(reverse('devhub.feed', args=[addon.slug]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('header h2').text(),
            'Recent Activity for %s' % addon.name)
        eq_(doc('.breadcrumbs li:eq(3)').text(),
            addon.slug)


class TestProfileBase(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.url = reverse('devhub.addons.profile', args=['a3615'])
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
                                  args=[self.addon.slug])

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

    def test_remove_profile_without_content(self):
        # See bug 624852
        self.addon.the_reason = self.addon.the_future = None
        self.addon.save()
        self.client.post(self.remove_url)
        addon = self.get_addon()
        eq_(addon.the_reason, None)
        eq_(addon.the_future, None)

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
        eq_(doc('label[for=the_reason] .optional').length, 1)
        eq_(doc('label[for=the_future] .optional').length, 1)

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
        assert doc('label[for=the_reason] .req').length, \
               'the_reason field should be required.'
        assert doc('label[for=the_future] .req').length, \
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


class TestVersion(test_utils.TestCase):
    fixtures = ['base/users',
                'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.addon = Addon.objects.get(id=3615)
        self.version = Version.objects.get(id=81551)
        self.url = reverse('devhub.versions', args=['a3615'])

        self.disable_url = reverse('devhub.addons.disable', args=['a3615'])
        self.enable_url = reverse('devhub.addons.enable', args=['a3615'])
        self.delete_url = reverse('devhub.versions.delete', args=['a3615'])
        self.delete_data = {'addon_id': self.addon.pk,
                            'version_id': self.version.pk}

    def get_doc(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        return pq(res.content)

    def test_version_status_public(self):
        doc = self.get_doc()
        assert doc('#version-status')

        self.addon.status = amo.STATUS_DISABLED
        self.addon.save()
        doc = self.get_doc()
        assert doc('#version-status .status-admin-disabled')
        eq_(doc('#version-status strong').text(),
            'This add-on has been disabled by Mozilla .')

        self.addon.update(disabled_by_user=True)
        doc = self.get_doc()
        eq_(doc('#version-status strong').text(),
            'You have disabled this add-on.')

    def test_no_validation_results(self):
        doc = self.get_doc()
        v = doc('td.file-validation').text()
        eq_(re.sub(r'\s+', ' ', v),
            'All Platforms Not validated. Validate now.')
        eq_(doc('td.file-validation a').attr('href'),
            reverse('devhub.file_validation',
                    args=[self.addon.slug, self.version.all_files[0].id]))

    def test_delete_message(self):
        """Make sure we warn our users of the pain they will feel."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#modal-delete p').eq(0).text(),
            'Deleting your add-on will permanently remove it from the site '
            'and prevent its GUID from being submitted ever again, even by '
            'you. The existing users of your add-on will remain on this '
            'update channel and never receive updates again.')

    def test_delete_message_if_bits_are_messy(self):
        """Make sure we warn krupas of the pain they will feel."""
        self.addon.highest_status = amo.STATUS_NULL
        self.addon.status = amo.STATUS_UNREVIEWED
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#modal-delete p').eq(0).text(),
            'Deleting your add-on will permanently remove it from the site '
            'and prevent its GUID from being submitted ever again, even by '
            'you. The existing users of your add-on will remain on this '
            'update channel and never receive updates again.')

    def test_delete_message_incomplete(self):
        """
        If an addon has highest_status = 0, they shouldn't be bothered with a
        blacklisting threat if they hit delete.
        """
        self.addon.highest_status = amo.STATUS_NULL
        self.addon.status = amo.STATUS_NULL
        self.addon.save()
        r = self.client.get(self.url)
        doc = pq(r.content)
        # Normally 2 paragraphs, one is the warning which we should take out.
        eq_(len(doc('#modal-delete p')), 1, 'We might be lying to our users.')

    def test_delete_version(self):
        self.client.post(self.delete_url, self.delete_data)
        assert not Version.objects.filter(pk=81551).exists()

    def test_delete_version_then_detail(self):
        version, file = self._extra_version_and_file(amo.STATUS_LITE)
        self.client.post(self.delete_url, self.delete_data)
        res = self.client.get(reverse('addons.detail', args=[self.addon.slug]))
        eq_(res.status_code, 200)

    def test_cant_delete_version(self):
        self.client.logout()
        res = self.client.post(self.delete_url, self.delete_data)
        eq_(res.status_code, 302)
        assert Version.objects.filter(pk=81551).exists()

    def test_version_delete_status_null(self):
        res = self.client.post(self.delete_url, self.delete_data)
        eq_(res.status_code, 302)
        eq_(self.addon.versions.count(), 0)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_NULL)

    def _extra_version_and_file(self, status):
        version = Version.objects.get(id=81551)

        version_two = Version(addon=self.addon,
                              license=version.license,
                              version='1.2.3')
        version_two.save()

        file_two = File(status=status, version=version_two)
        file_two.save()
        return version_two, file_two

    def test_version_delete_status(self):
        self._extra_version_and_file(amo.STATUS_PUBLIC)

        res = self.client.post(self.delete_url, self.delete_data)
        eq_(res.status_code, 302)
        eq_(self.addon.versions.count(), 1)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_PUBLIC)

    def test_version_delete_status_unreviewd(self):
        self._extra_version_and_file(amo.STATUS_BETA)

        res = self.client.post(self.delete_url, self.delete_data)
        eq_(res.status_code, 302)
        eq_(self.addon.versions.count(), 1)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_UNREVIEWED)

    @mock.patch('files.models.File.hide_disabled_file')
    def test_user_can_disable_addon(self, hide_mock):
        self.addon.update(status=amo.STATUS_PUBLIC,
                          disabled_by_user=False)
        res = self.client.post(self.disable_url)
        eq_(res.status_code, 302)
        addon = Addon.objects.get(id=3615)
        eq_(addon.disabled_by_user, True)
        eq_(addon.status, amo.STATUS_PUBLIC)
        assert hide_mock.called

        entry = ActivityLog.objects.get()
        eq_(entry.action, amo.LOG.USER_DISABLE.id)
        msg = entry.to_string()
        assert self.addon.name.__unicode__() in msg, ("Unexpected: %r" % msg)

    def test_user_can_enable_addon(self):
        self.addon.update(status=amo.STATUS_PUBLIC,
                          disabled_by_user=True)
        res = self.client.get(self.enable_url)
        eq_(res.status_code, 302)
        addon = Addon.objects.get(id=3615)
        eq_(addon.disabled_by_user, False)
        eq_(addon.status, amo.STATUS_PUBLIC)

        entry = ActivityLog.objects.get()
        eq_(entry.action, amo.LOG.USER_ENABLE.id)
        msg = entry.to_string()
        assert unicode(self.addon.name) in msg, ("Unexpected: %r" % msg)

    def test_unprivileged_user_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        res = self.client.post(self.disable_url)
        eq_(res.status_code, 302)
        eq_(Addon.objects.get(id=3615).disabled_by_user, False)

    def test_non_owner_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        res = self.client.post(self.disable_url)
        eq_(res.status_code, 403)
        eq_(Addon.objects.get(id=3615).disabled_by_user, False)

    def test_non_owner_cant_enable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        res = self.client.get(self.enable_url)
        eq_(res.status_code, 403)
        eq_(Addon.objects.get(id=3615).disabled_by_user, False)

    def test_show_disable_button(self):
        self.addon.update(disabled_by_user=False)
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert doc('#modal-disable')
        assert doc('#disable-addon')
        assert not doc('#enable-addon')

    def test_not_show_disable(self):
        self.addon.update(status=amo.STATUS_DISABLED, disabled_by_user=False)
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not doc('#modal-disable')
        assert not doc('#disable-addon')

    def test_show_enable_button(self):
        self.addon.update(disabled_by_user=True)
        res = self.client.get(self.url)
        doc = pq(res.content)
        a = doc('#enable-addon')
        assert a, "Expected Enable addon link"
        eq_(a.attr('href'), self.enable_url)
        assert not doc('#modal-disable')
        assert not doc('#disable-addon')

    def test_cancel_wrong_status(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        for status in amo.STATUS_CHOICES:
            if status in amo.STATUS_UNDER_REVIEW:
                continue

            self.addon.update(status=status)
            self.client.post(cancel_url)
            eq_(Addon.objects.get(id=3615).status, status)

    def test_cancel(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.client.post(cancel_url)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_LITE)

        for status in (amo.STATUS_UNREVIEWED, amo.STATUS_NOMINATED):
            self.addon.update(status=status)
            self.client.post(cancel_url)
            eq_(Addon.objects.get(id=3615).status, amo.STATUS_NULL)

    def test_not_cancel(self):
        self.client.logout()
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        res = self.client.post(cancel_url)
        eq_(res.status_code, 302)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_PUBLIC)

    def test_cancel_button(self):
        for status in amo.STATUS_CHOICES:
            if status not in amo.STATUS_UNDER_REVIEW:
                continue

            self.addon.update(status=status)
            res = self.client.get(self.url)
            doc = pq(res.content)
            assert doc('#cancel-review')
            assert doc('#modal-cancel')

    def test_not_cancel_button(self):
        for status in amo.STATUS_CHOICES:
            if status in amo.STATUS_UNDER_REVIEW:
                continue

            self.addon.update(status=status)
            res = self.client.get(self.url)
            doc = pq(res.content)
            assert not doc('#cancel-review')
            assert not doc('#modal-cancel')

    def test_purgatory_request_review(self):
        self.addon.update(status=amo.STATUS_PURGATORY)
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button').text()
        eq_(buttons, 'Request Preliminary Review Request Full Review')

    def test_add_version_modal(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        # Make sure checkboxes are visible:
        eq_(doc('input.platform').length, 4)
        eq_(set([i.attrib['type'] for i in doc('input.platform')]),
            set(['checkbox']))


class TestVersionEdit(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'base/thunderbird', 'base/platforms']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.addon = self.get_addon()
        self.version = self.get_version()
        self.url = reverse('devhub.versions.edit',
                           args=['a3615', self.version.id])
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

    def test_supported_platforms(self):
        res = self.client.get(self.url)
        choices = res.context['new_file_form'].fields['platform'].choices
        taken = [f.platform_id for f in self.version.files.all()]
        platforms = set(amo.SUPPORTED_PLATFORMS) - set(taken)
        eq_(len(choices), len(platforms))

    def test_can_upload(self):
        self.version.files.all().delete()
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('a.add-file')

    def test_not_upload(self):
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not doc('a.add-file')

    def test_add(self):
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert res.context['compat_form'].extra_forms
        assert doc('p.add-app')[0].attrib['class'] == 'add-app'

    def test_add_not(self):
        Application(id=52).save()
        for id in [18, 52, 59, 60]:
            av = AppVersion(application_id=id, version='1')
            av.save()
            ApplicationsVersions(application_id=id, min=av, max=av,
                                 version=self.version).save()

        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not res.context['compat_form'].extra_forms
        assert doc('p.add-app')[0].attrib['class'] == 'add-app hide'


class TestVersionEditSearchEngine(TestVersionEdit):
    # https://bugzilla.mozilla.org/show_bug.cgi?id=605941
    fixtures = ['base/apps', 'base/users',
                'base/thunderbird', 'base/addon_4594_a9.json',
                'base/platforms']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.versions.edit',
                           args=['a4594', 42352])

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

    def test_no_upload(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert not doc('a.add-file')

    @mock.patch('versions.models.Version.is_allowed_upload')
    def test_can_upload(self, allowed):
        allowed.return_value = True
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert doc('a.add-file')


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

        eq_(ActivityLog.objects.count(), 2)
        log = ActivityLog.objects.order_by('created')[1]
        eq_(log.to_string(), u'File delicious_bookmarks-2.1.072-fx.xpi deleted'
                              ' from <a href="/en-US/firefox/addon/a3615'
                              '/versions/2.1.072">Version 2.1.072</a> of <a '
                              'href="/en-US/firefox/addon/a3615/">Delicious '
                              'Bookmarks</a>.')
        eq_(r.status_code, 302)
        eq_(self.version.files.count(), 0)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_unique_platforms(self):
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

    def test_all_platforms(self):
        File.objects.create(version=self.version,
                            platform_id=amo.PLATFORM_MAC.id)
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        res = self.client.post(self.url, self.formset(*forms, prefix='files'))
        eq_(res.context['file_form'].non_form_errors()[0],
            'The platfom All cannot be combined with specific platforms.')

    def test_all_platforms_and_delete(self):
        File.objects.create(version=self.version,
                    platform_id=amo.PLATFORM_MAC.id)
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        # A test that we don't check the platform for deleted files.
        forms[1]['DELETE'] = 1
        self.client.post(self.url, self.formset(*forms, prefix='files'))
        eq_(self.version.files.count(), 1)

    def add_in_bsd(self):
        f = self.version.files.get()
        # The default file is All, which prevents the addition of more files.
        f.update(platform=Platform.objects.get(id=amo.PLATFORM_MAC.id))
        return File.objects.create(version=self.version,
                                   platform_id=amo.PLATFORM_BSD.id)

    def test_all_unsupported_platforms(self):
        self.add_in_bsd()
        forms = self.client.get(self.url).context['file_form'].forms
        # Forms[0] is the form for the MAC and forms[1] is the form for the
        # BSD file, which should have one extra platform in it.
        eq_(len(forms[0].fields['platform'].choices), 4)
        eq_(len(forms[1].fields['platform'].choices), 5)

    def test_all_unsupported_platforms_unchange(self):
        bsd = self.add_in_bsd()
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        self.client.post(self.url, self.formset(*forms, prefix='files'))
        eq_(File.objects.no_cache().get(pk=bsd.pk).platform_id,
            amo.PLATFORM_BSD.id)

    def test_all_unsupported_platforms_change(self):
        bsd = self.add_in_bsd()
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        forms[1]['platform'] = 2
        self.client.post(self.url, self.formset(*forms, prefix='files'))
        eq_(File.objects.no_cache().get(pk=bsd.pk).platform_id,
            amo.PLATFORM_LINUX.id)
        # Check you can't choose BSD anymore.
        forms = self.client.get(self.url).context['file_form'].forms
        eq_(len(forms[1].fields['platform'].choices), 4)

    def test_add_file_modal(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        # Make sure radio buttons are visible:
        eq_(doc('input.platform').length, 3)
        eq_(set([i.attrib['type'] for i in doc('input.platform')]),
            set(['radio']))


class TestPlatformSearch(TestVersionEdit):
    fixtures = ['base/apps', 'base/users',
                'base/thunderbird', 'base/addon_4594_a9.json']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.versions.edit',
                           args=['a4594', 42352])
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

    def test_same_min_max(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d['min'] = d['max']
        r = self.client.post(self.url, self.formset(d, initial_count=1))
        eq_(r.status_code, 302)
        av = self.version.apps.all()[0]
        eq_(av.min, av.max)


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
                "Looks like link %r to %r is still a placeholder" %
                (href, ln.text))


class TestSubmitStep2(test_utils.TestCase):
    # More tests in TestCreateAddon.
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
    fixtures = ['base/addon_3615', 'base/addon_3615_categories',
                'base/addon_5579', 'base/users']

    def setUp(self):
        super(TestSubmitStep3, self).setUp()
        self.addon = self.get_addon()
        self.url = reverse('devhub.submit.3', args=['a3615'])
        assert self.client.login(username='del@icio.us', password='password')
        SubmitStep.objects.create(addon_id=3615, step=3)
        self._redis = mock_redis()
        cron.build_reverse_name_lookup()

        AddonCategory.objects.filter(addon=self.get_addon(),
                category=Category.objects.get(id=23)).delete()
        AddonCategory.objects.filter(addon=self.get_addon(),
                category=Category.objects.get(id=24)).delete()

        ctx = self.client.get(self.url).context['cat_form']
        self.cat_initial = initial(ctx.initial_forms[0])

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def tearDown(self):
        reset_redis(self._redis)

    def get_dict(self, **kw):
        cat_initial = kw.pop('cat_initial', self.cat_initial)
        fs = formset(cat_initial, initial_count=1)
        result = {'name': 'Test name', 'slug': 'testname',
                  'description': 'desc', 'summary': 'Hello!'}
        result.update(**kw)
        result.update(fs)
        return result

    def test_submit_success(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

        # Post and be redirected.
        d = self.get_dict()
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        eq_(SubmitStep.objects.get(addon=3615).step, 4)

        addon = self.get_addon()
        eq_(addon.name, 'Test name')
        eq_(addon.slug, 'testname')
        eq_(addon.description, 'desc')
        eq_(addon.summary, 'Hello!')
        # Test add-on log activity.
        log_items = ActivityLog.objects.for_addons(addon)
        assert not log_items.filter(action=amo.LOG.EDIT_DESCRIPTIONS.id), \
                "Creating a description needn't be logged."

    def test_submit_name_unique(self):
        # Make sure name is unique.
        r = self.client.post(self.url, self.get_dict(name='Cooliris'))
        error = 'This add-on name is already in use. Please choose another.'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_name_unique_strip(self):
        # Make sure we can't sneak in a name by adding a space or two.
        r = self.client.post(self.url, self.get_dict(name='  Cooliris  '))
        error = 'This add-on name is already in use. Please choose another.'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_name_unique_case(self):
        # Make sure unique names aren't case sensitive.
        r = self.client.post(self.url, self.get_dict(name='cooliris'))
        error = 'This add-on name is already in use. Please choose another.'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_name_required(self):
        # Make sure name is required.
        r = self.client.post(self.url, self.get_dict(name=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'name', 'This field is required.')

    def test_submit_name_length(self):
        # Make sure the name isn't too long.
        d = self.get_dict(name='a' * 51)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        error = 'Ensure this value has at most 50 characters (it has 51).'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_slug_invalid(self):
        # Submit an invalid slug.
        d = self.get_dict(slug='slug!!! aksl23%%')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'slug', "Enter a valid 'slug' " +
                    "consisting of letters, numbers, underscores or hyphens.")

    def test_submit_slug_required(self):
        # Make sure the slug is required.
        r = self.client.post(self.url, self.get_dict(slug=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'slug', 'This field is required.')

    def test_submit_summary_required(self):
        # Make sure summary is required.
        r = self.client.post(self.url, self.get_dict(summary=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'summary', 'This field is required.')

    def test_submit_summary_length(self):
        # Summary is too long.
        r = self.client.post(self.url, self.get_dict(summary='a' * 251))
        eq_(r.status_code, 200)
        error = 'Ensure this value has at most 250 characters (it has 251).'
        self.assertFormError(r, 'form', 'summary', error)

    def test_submit_categories_required(self):
        del self.cat_initial['categories']
        r = self.client.post(self.url,
                             self.get_dict(cat_initial=self.cat_initial))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['This field is required.'])

    def test_submit_categories_max(self):
        eq_(amo.MAX_CATEGORIES, 2)
        self.cat_initial['categories'] = [22, 23, 24]
        r = self.client.post(self.url,
                             self.get_dict(cat_initial=self.cat_initial))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['You can have only 2 categories.'])

    def test_submit_categories_add(self):
        eq_([c.id for c in self.get_addon().all_categories], [22])
        self.cat_initial['categories'] = [22, 23]

        self.client.post(self.url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        eq_(sorted(addon_cats), [22, 23])

    def test_submit_categories_addandremove(self):
        AddonCategory(addon=self.addon, category_id=23).save()
        eq_([c.id for c in self.get_addon().all_categories], [22, 23])

        self.cat_initial['categories'] = [22, 24]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [c.id for c in self.get_addon().all_categories]
        eq_(category_ids_new, [22, 24])

    def test_submit_categories_remove(self):
        c = Category.objects.get(id=23)
        AddonCategory(addon=self.addon, category=c).save()
        eq_([c.id for c in self.get_addon().all_categories], [22, 23])

        self.cat_initial['categories'] = [22]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [c.id for c in self.get_addon().all_categories]
        eq_(category_ids_new, [22])

    def test_check_version(self):
        addon = Addon.objects.get(pk=3615)

        r = self.client.get(self.url)
        doc = pq(r.content)
        version = doc("#current_version").val()

        eq_(version, addon.current_version.version)


class TestSubmitStep4(TestSubmitBase):

    def setUp(self):
        self.old_addon_icon_url = settings.ADDON_ICON_URL
        settings.ADDON_ICON_URL = "%s/%s/%s/images/addon_icon/%%d/%%s" % (
            settings.STATIC_URL, settings.LANGUAGE_CODE, settings.DEFAULT_APP)
        super(TestSubmitStep4, self).setUp()
        SubmitStep.objects.create(addon_id=3615, step=5)
        self.url = reverse('devhub.submit.4', args=['a3615'])
        self.next_step = reverse('devhub.submit.5', args=['a3615'])
        self.icon_upload = reverse('devhub.addons.upload_icon',
                                      args=['a3615'])
        self.preview_upload = reverse('devhub.addons.upload_preview',
                                      args=['a3615'])

    def tearDown(self):
        settings.ADDON_ICON_URL = self.old_addon_icon_url

    def test_get(self):
        eq_(self.client.get(self.url).status_code, 200)

    def test_post(self):
        data = dict(icon_type='')
        data_formset = self.formset_media(**data)
        r = self.client.post(self.url, data_formset)
        eq_(r.status_code, 302)
        eq_(self.get_step().step, 5)

    def formset_new_form(self, *args, **kw):
        ctx = self.client.get(self.url).context

        blank = initial(ctx['preview_form'].forms[-1])
        blank.update(**kw)
        return blank

    def formset_media(self, *args, **kw):
        kw.setdefault('initial_count', 0)
        kw.setdefault('prefix', 'files')

        fs = formset(*[a for a in args] + [self.formset_new_form()], **kw)
        return dict([(k, '' if v is None else v) for k, v in fs.items()])

    def test_edit_media_defaulticon(self):
        data = dict(icon_type='')
        data_formset = self.formset_media(**data)

        self.client.post(self.url, data_formset)

        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/default-64.png')

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_media_preuploadedicon(self):
        data = dict(icon_type='icon/appearance')
        data_formset = self.formset_media(**data)
        self.client.post(self.url, data_formset)

        addon = self.get_addon()

        eq_('/'.join(addon.get_icon_url(64).split('/')[-2:]),
            'addon-icons/appearance-64.png')

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_media_uploadedicon(self):
        img = "%s/img/amo2009/tab-mozilla.png" % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(**data)

        self.client.post(self.url, data_formset)

        addon = self.get_addon()

        eq_('/'.join(addon.get_icon_url(64).split('/')[-3:-1]),
            'addon_icon/%s' % addon.id)

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-32.png' % addon.id)

        assert os.path.exists(dest)

        eq_(Image.open(dest).size, (32, 12))

    def test_edit_media_uploadedicon_noresize(self):
        img = "%s/img/amo2009/notifications/error.png" % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(**data)

        self.client.post(self.url, data_formset)
        addon = self.get_addon()

        eq_('/'.join(addon.get_icon_url(64).split('/')[-3:-1]),
            'addon_icon/%s' % addon.id)

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-64.png' % addon.id)

        assert os.path.exists(dest)

        eq_(Image.open(dest).size, (48, 48))

    def test_client_lied(self):
        filehandle = open(get_image_path('non-animated.gif'), 'rb')

        data = {'upload_image': filehandle}

        res = self.client.post(self.preview_upload, data)
        response_json = json.loads(res.content)

        eq_(response_json['errors'][0], u'Icons must be either PNG or JPG.')

    def test_icon_animated(self):
        filehandle = open(get_image_path('animated.png'), 'rb')
        data = {'upload_image': filehandle}

        res = self.client.post(self.preview_upload, data)
        response_json = json.loads(res.content)

        eq_(response_json['errors'][0], u'Icons cannot be animated.')

    def test_icon_non_animated(self):
        filehandle = open(get_image_path('non-animated.png'), 'rb')
        data = {'icon_type': 'image/png', 'icon_upload': filehandle}
        data_formset = self.formset_media(**data)
        res = self.client.post(self.url, data_formset)
        eq_(res.status_code, 302)
        eq_(self.get_step().step, 5)


class TestSubmitStep5(TestSubmitBase):
    """License submission."""

    def setUp(self):
        super(TestSubmitStep5, self).setUp()
        SubmitStep.objects.create(addon_id=3615, step=5)
        self.url = reverse('devhub.submit.5', args=['a3615'])
        self.next_step = reverse('devhub.submit.6', args=['a3615'])
        License.objects.create(builtin=3, on_form=True)

    def test_get(self):
        eq_(self.client.get(self.url).status_code, 200)

    def test_set_license(self):
        r = self.client.post(self.url, {'builtin': 3})
        self.assertRedirects(r, self.next_step)
        eq_(self.get_addon().current_version.license.builtin, 3)
        eq_(self.get_step().step, 6)
        log_items = ActivityLog.objects.for_addons(self.get_addon())
        assert not log_items.filter(action=amo.LOG.CHANGE_LICENSE.id), \
                "Initial license choice:6 needn't be logged."

    def test_license_error(self):
        r = self.client.post(self.url, {'builtin': 4})
        eq_(r.status_code, 200)
        self.assertFormError(r, 'license_form', 'builtin',
                             'Select a valid choice. 4 is not one of '
                             'the available choices.')
        eq_(self.get_step().step, 5)

    def test_set_eula(self):
        self.get_addon().update(eula=None, privacy_policy=None)
        r = self.client.post(self.url, dict(builtin=3, has_eula=True,
                                            eula='xxx'))
        self.assertRedirects(r, self.next_step)
        eq_(unicode(self.get_addon().eula), 'xxx')
        eq_(self.get_step().step, 6)

    def test_set_eula_nomsg(self):
        """
        You should not get punished with a 500 for not writing your EULA...
        but perhaps you should feel shame for lying to us.  This test does not
        test for shame.
        """
        self.get_addon().update(eula=None, privacy_policy=None)
        r = self.client.post(self.url, dict(builtin=3, has_eula=True))
        self.assertRedirects(r, self.next_step)
        eq_(self.get_step().step, 6)


class TestSubmitStep6(TestSubmitBase):

    def setUp(self):
        super(TestSubmitStep6, self).setUp()
        SubmitStep.objects.create(addon_id=3615, step=6)
        self.url = reverse('devhub.submit.6', args=['a3615'])

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
        self.get_addon().update(nomination_date=None)
        d = dict(review_type=amo.STATUS_NOMINATED)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        addon = self.get_addon()
        eq_(addon.status, amo.STATUS_NOMINATED)
        assert_close_to_now(addon.nomination_date)
        assert_raises(SubmitStep.DoesNotExist, self.get_step)


class TestSubmitStep7(TestSubmitBase):

    def test_finish_submitting_addon(self):
        addon = Addon.objects.get(
                        name__localized_string='Delicious Bookmarks')
        eq_(addon.current_version.supported_platforms, [amo.PLATFORM_ALL])

        response = self.client.get(reverse('devhub.submit.7', args=['a3615']))
        eq_(response.status_code, 200)
        doc = pq(response.content)

        eq_(response.status_code, 200)
        eq_(response.context['addon'].name.localized_string,
            u"Delicious Bookmarks")

        abs_url = settings.SITE_URL + "/en-US/firefox/addon/a3615/"
        eq_(doc("a#submitted-addon-url").text().strip(), abs_url)
        eq_(doc("a#submitted-addon-url").attr('href'),
            "/en-US/firefox/addon/a3615/")

        next_steps = doc(".done-next-steps li a")

        # edit listing of freshly submitted add-on...
        eq_(next_steps[0].attrib['href'],
            reverse('devhub.addons.edit',
                    kwargs=dict(addon_id=addon.slug)))

        # edit your developer profile...
        eq_(next_steps[1].attrib['href'],
            reverse('devhub.addons.profile', args=[addon.slug]))

        # view wait times:
        eq_(next_steps[3].attrib['href'],
            "https://forums.addons.mozilla.org/viewforum.php?f=21")

    def test_finish_submitting_platform_specific_addon(self):
        # mac-only Add-on:
        addon = Addon.objects.get(name__localized_string='Cooliris')
        AddonUser.objects.create(user=UserProfile.objects.get(pk=55021),
                                 addon=addon)
        response = self.client.get(reverse('devhub.submit.7', args=['a5579']))
        eq_(response.status_code, 200)
        doc = pq(response.content)
        next_steps = doc(".done-next-steps li a")

        # upload more platform specific files...
        eq_(next_steps[0].attrib['href'],
            reverse('devhub.versions.edit', kwargs=dict(
                                addon_id=addon.slug,
                                version_id=addon.current_version.id)))

        # edit listing of freshly submitted add-on...
        eq_(next_steps[1].attrib['href'],
            reverse('devhub.addons.edit',
                    kwargs=dict(addon_id=addon.slug)))

    def test_finish_addon_for_prelim_review(self):
        addon = Addon.objects.get(pk=3615)
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()

        response = self.client.get(reverse('devhub.submit.7', args=['a3615']))
        eq_(response.status_code, 200)
        doc = pq(response.content)
        exp = 'Your add-on has been submitted to the Preliminary Review queue'
        intro = doc('.addon-submission-process p').text()
        assert exp in intro, ('Unexpected intro: %s' % intro.strip())

    def test_finish_addon_for_full_review(self):
        addon = Addon.objects.get(pk=3615)
        addon.status = amo.STATUS_NOMINATED
        addon.save()

        response = self.client.get(reverse('devhub.submit.7', args=['a3615']))
        eq_(response.status_code, 200)
        doc = pq(response.content)
        exp = 'Your add-on has been submitted to the Full Review queue'
        intro = doc('.addon-submission-process p').text()
        assert exp in intro, ('Unexpected intro: %s' % intro.strip())

    def test_incomplete_addon_no_versions(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(status=amo.STATUS_NULL)
        addon.versions.all().delete()
        r = self.client.get(reverse('devhub.submit.7', args=['a3615']),
                                   follow=True)
        self.assertRedirects(r, reverse('devhub.versions', args=['a3615']))

    def test_link_to_activityfeed(self):
        addon = Addon.objects.get(pk=3615)
        r = self.client.get(reverse('devhub.submit.7', args=['a3615']),
                                   follow=True)
        doc = pq(r.content)
        eq_(doc('.done-next-steps a').eq(2).attr('href'),
            reverse('devhub.feed', args=[addon.slug]))

    def test_display_non_ascii_url(self):
        addon = Addon.objects.get(pk=3615)
        u = 'フォクすけといっしょ'
        addon.update(slug=u)
        r = self.client.get(reverse('devhub.submit.7', args=[u]))
        eq_(r.status_code, 200)
        # The meta charset will always be utf-8.
        doc = pq(r.content.decode('utf-8'))
        eq_(doc('#submitted-addon-url').text(),
            u'%s/en-US/firefox/addon/%s/' % (
                settings.SITE_URL, u.decode('utf8')))


class TestResumeStep(TestSubmitBase):

    def setUp(self):
        super(TestResumeStep, self).setUp()
        self.url = reverse('devhub.submit.resume', args=['a3615'])

    def test_no_step_redirect(self):
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, reverse('devhub.submit.7', args=['a3615']),
                             302)

    def test_step_redirects(self):
        SubmitStep.objects.create(addon_id=3615, step=1)
        for i in xrange(3, 7):
            SubmitStep.objects.filter(addon=self.get_addon()).update(step=i)
            r = self.client.get(self.url, follow=True)
            self.assertRedirects(r, reverse('devhub.submit.%s' % i,
                                            args=['a3615']))

    def test_redirect_from_other_pages(self):
        SubmitStep.objects.create(addon_id=3615, step=4)
        r = self.client.get(reverse('devhub.addons.edit', args=['a3615']),
                            follow=True)
        self.assertRedirects(r, reverse('devhub.submit.4', args=['a3615']))


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
                                    args=['a3615']))
        eq_(r.status_code, 200)

    def test_skip_step_6(self):
        # We get bounced back to step 3.
        SubmitStep.objects.create(addon_id=3615, step=3)
        r = self.client.get(reverse('devhub.submit.6',
                                    args=['a3615']), follow=True)
        self.assertRedirects(r, reverse('devhub.submit.3', args=['a3615']))

    def test_all_done(self):
        # There's no SubmitStep, so we must be done.
        r = self.client.get(reverse('devhub.submit.6',
                                    args=['a3615']), follow=True)
        self.assertRedirects(r, reverse('devhub.submit.7', args=['a3615']))

    def test_menu_step_1(self):
        doc = pq(self.client.get(reverse('devhub.submit.1')).content)
        self.assert_linked(doc, [1])
        self.assert_highlight(doc, 1)

    def test_menu_step_2(self):
        self.client.post(reverse('devhub.submit.1'))
        doc = pq(self.client.get(reverse('devhub.submit.2')).content)
        self.assert_linked(doc, [1, 2])
        self.assert_highlight(doc, 2)

    def test_menu_step_3(self):
        SubmitStep.objects.create(addon_id=3615, step=3)
        url = reverse('devhub.submit.3', args=['a3615'])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [3])
        self.assert_highlight(doc, 3)

    def test_menu_step_3_from_6(self):
        SubmitStep.objects.create(addon_id=3615, step=6)
        url = reverse('devhub.submit.3', args=['a3615'])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [3, 4, 5, 6])
        self.assert_highlight(doc, 3)

    def test_menu_step_6(self):
        SubmitStep.objects.create(addon_id=3615, step=6)
        url = reverse('devhub.submit.6', args=['a3615'])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [3, 4, 5, 6])
        self.assert_highlight(doc, 6)

    def test_menu_step_7(self):
        url = reverse('devhub.submit.7', args=['a3615'])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [])
        self.assert_highlight(doc, 7)


class TestUpload(files.tests.UploadTest):
    fixtures = ['base/apps', 'base/users']

    def setUp(self):
        super(TestUpload, self).setUp()
        self.url = reverse('devhub.upload')

    def post(self):
        # Has to be a binary, non xpi file.
        data = open(get_image_path('animated.png'), 'rb')
        return self.client.post(self.url, {'upload': data})

    def test_create_fileupload(self):
        self.post()

        upload = FileUpload.objects.get(name='animated.png')
        eq_(upload.name, 'animated.png')
        data = open(get_image_path('animated.png'), 'rb').read()
        eq_(open(upload.path).read(), data)

    def test_fileupload_user(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.post()
        user = UserProfile.objects.get(email='regular@mozilla.com')
        eq_(FileUpload.objects.get().user, user)

    def test_fileupload_ascii_post(self):
        path = 'apps/files/fixtures/files/jétpack.xpi'
        data = open(os.path.join(settings.ROOT, path))

        r = self.client.post(self.url, {'upload': data})
        # If this is broke, we'll get a traceback.
        eq_(r.status_code, 302)

    @attr('validator')
    def test_fileupload_validation(self):
        self.post()
        fu = FileUpload.objects.get(name='animated.png')
        assert_no_validation_errors(fu)
        assert fu.validation
        validation = json.loads(fu.validation)

        eq_(validation['success'], False)
        # The current interface depends on this JSON structure:
        eq_(validation['errors'], 2)
        eq_(validation['warnings'], 0)
        assert len(validation['messages'])
        msg = validation['messages'][0]
        assert 'uid' in msg, "Unexpected: %r" % msg
        eq_(msg['type'], u'error')
        eq_(msg['message'], u'The package is not of a recognized type.')
        eq_(msg['description'], u'')

    def test_redirect(self):
        r = self.post()
        upload = FileUpload.objects.get()
        url = reverse('devhub.upload_detail', args=[upload.pk, 'json'])
        self.assertRedirects(r, url)


class TestUploadDetail(files.tests.UploadTest):
    fixtures = ['base/apps', 'base/appversion', 'base/users']

    def post(self):
        # Has to be a binary, non xpi file.
        data = open(get_image_path('animated.png'), 'rb')
        return self.client.post(reverse('devhub.upload'), {'upload': data})

    def validation_ok(self):
        return {
            'errors': 0,
            'success': True,
            'warnings': 0,
            'notices': 0,
            'message_tree': {},
            'messages': [],
            'rejected': False}

    @attr('validator')
    def test_detail_json(self):
        self.post()

        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        eq_(data['url'],
            reverse('devhub.upload_detail', args=[upload.uuid, 'json']))
        eq_(data['full_report_url'],
            reverse('devhub.upload_detail', args=[upload.uuid]))
        # We must have tiers
        assert len(data['validation']['messages'])
        msg = data['validation']['messages'][0]
        eq_(msg['tier'], 1)

    def test_detail_view(self):
        self.post()
        upload = FileUpload.objects.get(name='animated.png')
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('header h2').text(), 'Validation Results for animated.png')
        suite = doc('#addon-validator-suite')
        eq_(suite.attr('data-validateurl'),
            reverse('devhub.upload_detail', args=[upload.uuid, 'json']))

    @mock.patch('devhub.tasks._validator')
    def test_multi_app_addon_cannot_have_platforms(self, v):
        v.return_value = json.dumps(self.validation_ok())
        addon = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                             'addons', 'mobile-2.9.10-fx+fn.xpi')
        with open(addon, 'rb') as f:
            r = self.client.post(reverse('devhub.upload'),
                                 {'upload': f})
        eq_(r.status_code, 302)
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['new_platform_choices'], [
                {'text': unicode(amo.PLATFORM_ALL.name), 'checked': True,
                 'value': amo.PLATFORM_ALL.id}])

    @mock.patch('devhub.tasks._validator')
    def test_new_platform_choices_for_mobile(self, v):
        v.return_value = json.dumps(self.validation_ok())
        addon = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                             'addons', 'mobile-0.1-fn.xpi')
        with open(addon, 'rb') as f:
            r = self.client.post(reverse('devhub.upload'),
                                 {'upload': f})
        eq_(r.status_code, 302)
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['new_platform_choices'], [
                {'text': unicode(amo.PLATFORM_ALL.name), 'checked': True,
                 'value': amo.PLATFORM_ALL.id},
                {'text': unicode(amo.PLATFORM_MAEMO.name),
                 'value': amo.PLATFORM_MAEMO.id},
                {'text': unicode(amo.PLATFORM_ANDROID.name),
                 'value': amo.PLATFORM_ANDROID.id}])

    @mock.patch('devhub.tasks._validator')
    def test_search_tool_bypasses_platform_check(self, v):
        v.return_value = json.dumps(self.validation_ok())
        addon = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                             'addons', 'searchgeek-20090701.xml')
        with open(addon, 'rb') as f:
            r = self.client.post(reverse('devhub.upload'),
                                 {'upload': f})
        eq_(r.status_code, 302)
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['new_platform_choices'], None)

    @mock.patch('devhub.tasks._validator')
    def test_unparsable_xpi(self, v):
        v.return_value = json.dumps(self.validation_ok())
        addon = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                             'addons', 'unopenable.xpi')
        with open(addon, 'rb') as f:
            r = self.client.post(reverse('devhub.upload'),
                                 {'upload': f})
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['new_platform_choices'], None)


class TestUploadValidation(files.tests.UploadTest):
    fixtures = ['base/apps', 'base/users',
                'devhub/invalid-id-uploaded-xpi.json']

    def test_no_html_in_messages(self):
        upload = FileUpload.objects.get(name='invalid-id-20101206.xpi')
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        msg = data['validation']['messages'][0]
        eq_(msg['message'], 'The value of &lt;em:id&gt; is invalid.')
        eq_(sorted(msg['context']),
            [[u'&lt;foo/&gt;'], u'&lt;em:description&gt;...'])


class TestFileValidation(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users',
                'devhub/addon-validation-1', 'base/platforms']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.file_validation = FileValidation.objects.get(pk=1)
        self.file = self.file_validation.file
        self.addon = self.file.version.addon

    def test_version_list(self):
        r = self.client.get(reverse('devhub.versions',
                            args=[self.addon.slug]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('td.file-validation a').text(),
            '0 errors, 0 warnings')
        eq_(doc('td.file-validation a').attr('href'),
            reverse('devhub.file_validation',
                    args=[self.addon.slug, self.file.id]))

    def test_results_page(self):
        r = self.client.get(reverse('devhub.file_validation',
                                    args=[self.addon.slug, self.file.id]),
                                    follow=True)
        eq_(r.status_code, 200)
        eq_(r.context['addon'], self.addon)
        doc = pq(r.content)
        eq_(doc('header h2').text(),
            u'Validation Results for searchaddon11102010-20101217.xml')
        eq_(doc('#addon-validator-suite').attr('data-validateurl'),
            reverse('devhub.json_file_validation',
                    args=[self.addon.slug, self.file.id]))

    def test_only_dev_can_see_results(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('devhub.file_validation',
                                    args=[self.addon.slug, self.file.id]),
                                    follow=True)
        eq_(r.status_code, 403)

    def test_only_dev_can_see_json_results(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.post(reverse('devhub.json_file_validation',
                                    args=[self.addon.slug, self.file.id]),
                                    follow=True)
        eq_(r.status_code, 403)

    def test_editor_can_see_results(self):
        self.client.logout()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('devhub.file_validation',
                                    args=[self.addon.slug, self.file.id]),
                                    follow=True)
        eq_(r.status_code, 200)

    def test_editor_can_see_json_results(self):
        self.client.logout()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        r = self.client.post(reverse('devhub.json_file_validation',
                                    args=[self.addon.slug, self.file.id]),
                                    follow=True)
        eq_(r.status_code, 200)

    def test_no_html_in_messages(self):
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                                     follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        msg = data['validation']['messages'][0]
        eq_(msg['message'], 'The value of &lt;em:id&gt; is invalid.')
        eq_(sorted(msg['context']),
            [[u'&lt;foo/&gt;'], u'&lt;em:description&gt;...'])


class TestValidateFile(files.tests.UploadTest):
    fixtures = ['base/apps', 'base/users',
                'devhub/addon-file-100456', 'base/platforms']

    def setUp(self):
        super(TestValidateFile, self).setUp()
        assert self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.file = File.objects.get(pk=100456)
        # Move the file into place as if it were a real file
        os.makedirs(os.path.dirname(self.file.file_path))
        shutil.copyfile(self.file_path('invalid-id-20101206.xpi'),
                        self.file.file_path)
        self.addon = self.file.version.addon

    @attr('validator')
    def test_lazy_validate(self):
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                                     follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        msg = data['validation']['messages'][0]
        eq_(msg['message'], 'The value of &lt;em:id&gt; is invalid.')

    @mock.patch('devhub.tasks._validator')
    def test_validator_errors(self, v):
        v.side_effect = ValueError('catastrophic failure in amo-validator')
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                                     follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['validation'], '')
        assert data['error'].endswith(
                    "ValueError: catastrophic failure in amo-validator\n"), (
                        'Unexpected error: ...%s' % data['error'][-50:-1])


def assert_json_error(request, field, msg):
    eq_(request.status_code, 400)
    eq_(request['Content-Type'], 'application/json')
    field = '__all__' if field is None else field
    content = json.loads(request.content)
    assert field in content, '%r not in %r' % (field, content)
    eq_(content[field], [msg])


def assert_json_field(request, field, msg):
    eq_(request.status_code, 200)
    eq_(request['Content-Type'], 'application/json')
    content = json.loads(request.content)
    assert field in content, '%r not in %r' % (field, content)
    eq_(content[field], msg)


class UploadTest(files.tests.UploadTest, test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        super(UploadTest, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.addon.update(guid='guid@xpi')
        if not Platform.objects.filter(id=amo.PLATFORM_MAC.id):
            Platform.objects.create(id=amo.PLATFORM_MAC.id)
        assert self.client.login(username='del@icio.us', password='password')


class TestVersionAddFile(UploadTest):
    fixtures = ['base/apps', 'base/users',
                'base/addon_3615', 'base/platforms']

    def setUp(self):
        super(TestVersionAddFile, self).setUp()
        self.version.update(version='0.1')
        self.url = reverse('devhub.versions.add_file',
                           args=[self.addon.slug, self.version.id])

        files = self.version.files.all()[0]
        files.platform_id = amo.PLATFORM_LINUX.id
        files.save()

    def post(self, platform=amo.PLATFORM_MAC):
        return self.client.post(self.url, dict(upload=self.upload.pk,
                                               platform=platform.id))

    def test_guid_matches(self):
        self.addon.update(guid='something.different')
        r = self.post()
        assert_json_error(r, None, "UUID doesn't match add-on.")

    def test_version_matches(self):
        self.version.update(version='2.0')
        r = self.post()
        assert_json_error(r, None, "Version doesn't match")

    def test_platform_limits(self):
        r = self.post(platform=amo.PLATFORM_BSD)
        assert_json_error(r, 'platform',
                               'Select a valid choice. That choice is not '
                               'one of the available choices.')

    def test_platform_choices(self):
        url = reverse('devhub.versions.edit',
                      args=[self.addon.slug, self.version.id])
        r = self.client.get(url)
        form = r.context['new_file_form']
        platform = self.version.files.get().platform_id
        choices = form.fields['platform'].choices
        # User cannot upload existing platforms:
        assert platform not in dict(choices), choices
        # User cannot upload platform=ALL when platform files exist.
        assert amo.PLATFORM_ALL.id not in dict(choices), choices

    def test_platform_choices_when_no_files(self):
        all_choices = amo.SUPPORTED_PLATFORMS.values()
        self.version.files.all().delete()
        url = reverse('devhub.versions.edit',
                      args=[self.addon.slug, self.version.id])
        r = self.client.get(url)
        form = r.context['new_file_form']
        eq_(sorted(dict(form.fields['platform'].choices).keys()),
            sorted([p.id for p in all_choices]))

    def test_type_matches(self):
        self.addon.update(type=amo.ADDON_THEME)
        r = self.post()
        assert_json_error(r, None, "<em:type> doesn't match add-on")

    def test_file_platform(self):
        # Check that we're creating a new file with the requested platform.
        qs = self.version.files
        eq_(len(qs.all()), 1)
        assert not qs.filter(platform=amo.PLATFORM_MAC.id)
        self.post()
        eq_(len(qs.all()), 2)
        assert qs.get(platform=amo.PLATFORM_MAC.id)

    def test_upload_not_found(self):
        r = self.client.post(self.url, dict(upload='xxx',
                                            platform=amo.PLATFORM_MAC.id))
        assert_json_error(r, 'upload',
                               'There was an error with your upload. '
                               'Please try again.')

    @mock.patch('versions.models.Version.is_allowed_upload')
    def test_cant_upload(self, allowed):
        """Test that if is_allowed_upload fails, the upload will fail."""
        allowed.return_value = False
        res = self.post()
        assert_json_error(res, '__all__',
                          'You cannot upload any more files for this version.')

    def test_success_html(self):
        r = self.post()
        eq_(r.status_code, 200)
        new_file = self.version.files.get(platform=amo.PLATFORM_MAC.id)
        eq_(r.context['form'].instance, new_file)


class TestAddVersion(UploadTest):

    def post(self, platforms=[amo.PLATFORM_MAC]):
        return self.client.post(self.url, dict(upload=self.upload.pk,
                                               platforms=[p.id for p in
                                                          platforms]))

    def setUp(self):
        super(TestAddVersion, self).setUp()
        self.url = reverse('devhub.versions.add', args=[self.addon.slug])

    def test_unique_version_num(self):
        self.version.update(version='0.1')
        r = self.post()
        assert_json_error(r, None, 'Version 0.1 already exists')

    def test_success(self):
        r = self.post()
        version = self.addon.versions.get(version='0.1')
        assert_json_field(r, 'url', reverse('devhub.versions.edit',
                                        args=[self.addon.slug, version.id]))

    def test_public(self):
        self.post()
        fle = File.objects.all().order_by("-created")[0]
        eq_(fle.status, amo.STATUS_PUBLIC)

    def test_not_public(self):
        self.addon.update(trusted=False)
        self.post()
        fle = File.objects.all().order_by("-created")[0]
        assert_not_equal(fle.status, amo.STATUS_PUBLIC)

    def test_multiple_platforms(self):
        r = self.post(platforms=[amo.PLATFORM_MAC,
                                 amo.PLATFORM_LINUX])
        eq_(r.status_code, 200)
        version = self.addon.versions.get(version='0.1')
        eq_(len(version.all_files), 2)


class TestVersionXSS(UploadTest):

    def test_unique_version_num(self):
        self.version.update(
                version='<script>alert("Happy XSS-Xmas");</script>')
        r = self.client.get(reverse('devhub.addons'))
        eq_(r.status_code, 200)
        assert '<script>alert' not in r.content
        assert '&lt;script&gt;alert' in r.content


class TestCreateAddon(files.tests.UploadTest, test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/platforms']

    def setUp(self):
        super(TestCreateAddon, self).setUp()
        self._redis = mock_redis()
        self.upload = self.get_upload('extension.xpi')
        self.url = reverse('devhub.submit.2')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.client.post(reverse('devhub.submit.1'))

    def tearDown(self):
        reset_redis(self._redis)

    def post(self, platforms=[amo.PLATFORM_ALL], expect_errors=False):
        r = self.client.post(self.url,
                        dict(upload=self.upload.pk,
                             platforms=[p.id for p in platforms]),
                        follow=True)
        eq_(r.status_code, 200)
        if not expect_errors:
            # Show any unexpected form errors.
            if r.context and 'new_addon_form' in r.context:
                eq_(r.context['new_addon_form'].errors.as_text(), '')
        return r

    def assert_json_error(self, *args):
        UploadTest().assert_json_error(self, *args)

    def test_unique_name(self):
        ReverseNameLookup.add('xpi name', 34)
        r = self.post(expect_errors=True)
        eq_(r.context['new_addon_form'].non_field_errors(),
            ['This add-on name is already in use. '
             'Please choose another.'])

    def test_success(self):
        eq_(Addon.objects.count(), 0)
        r = self.post()
        addon = Addon.objects.get()
        self.assertRedirects(r, reverse('devhub.submit.3',
                                        args=[addon.slug]))
        log_items = ActivityLog.objects.for_addons(addon)
        assert log_items.filter(action=amo.LOG.CREATE_ADDON.id), \
                'New add-on creation never logged.'

    def test_missing_platforms(self):
        r = self.client.post(self.url, dict(upload=self.upload.pk))
        eq_(r.status_code, 200)
        eq_(r.context['new_addon_form'].errors.as_text(),
            u'* platforms\n  * This field is required.')
        doc = pq(r.content)
        eq_(doc('.platform ul.errorlist').text(),
            'This field is required.')

    def test_one_xpi_for_multiple_platforms(self):
        eq_(Addon.objects.count(), 0)
        r = self.post(platforms=[amo.PLATFORM_MAC,
                                 amo.PLATFORM_LINUX])
        addon = Addon.objects.get()
        self.assertRedirects(r, reverse('devhub.submit.3',
                                        args=[addon.slug]))
        eq_(sorted([f.filename for f in addon.current_version.all_files]),
            [u'xpi_name-0.1-linux.xpi', u'xpi_name-0.1-mac.xpi'])


class TestDeleteAddon(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        super(TestDeleteAddon, self).setUp()
        self.url = reverse('devhub.addons.delete', args=['a3615'])
        assert self.client.login(username='del@icio.us', password='password')
        self.addon = Addon.objects.get(id=3615)

    def post(self, *args, **kw):
        r = self.client.post(self.url, dict(*args, **kw))
        eq_(r.status_code, 302)
        return r

    def test_bad_password(self):
        r = self.post(password='turd')
        eq_(r.context['title'],
            'Password was incorrect. Add-on was not deleted.')
        eq_(Addon.objects.count(), 1)

    def test_success(self):
        r = self.post(password='password')
        eq_(r.context['title'], 'Add-on deleted.')
        eq_(Addon.objects.count(), 0)
        self.assertRedirects(r, reverse('devhub.addons'))


class TestRequestReview(test_utils.TestCase):
    fixtures = ['base/users', 'base/platforms']

    def setUp(self):
        self.addon = Addon.objects.create(type=1, name='xxx')
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(version=self.version,
                                        platform_id=amo.PLATFORM_ALL.id)
        self.redirect_url = reverse('devhub.versions', args=[self.addon.slug])
        self.lite_url = reverse('devhub.request-review',
                                args=[self.addon.slug, amo.STATUS_LITE])
        self.public_url = reverse('devhub.request-review',
                                  args=[self.addon.slug, amo.STATUS_PUBLIC])
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def get_addon(self):
        return Addon.objects.get(id=self.addon.id)

    def check(self, old_status, url, new_status):
        self.addon.update(status=old_status)
        r = self.client.post(url)
        self.assertRedirects(r, self.redirect_url)
        eq_(self.get_addon().status, new_status)

    def check_400(self, url):
        r = self.client.post(url)
        eq_(r.status_code, 400)

    def test_404(self):
        bad_url = self.public_url.replace(str(amo.STATUS_PUBLIC), '0')
        eq_(self.client.post(bad_url).status_code, 404)

    def test_public(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.check_400(self.lite_url)
        self.check_400(self.public_url)

    def test_disabled_by_user_to_lite(self):
        self.addon.update(disabled_by_user=True)
        self.check_400(self.lite_url)

    def test_disabled_by_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        self.check_400(self.lite_url)

    def test_lite_to_lite(self):
        self.addon.update(status=amo.STATUS_LITE)
        self.check_400(self.lite_url)

    def test_lite_to_public(self):
        eq_(self.addon.nomination_date, None)
        self.check(amo.STATUS_LITE, self.public_url,
                   amo.STATUS_LITE_AND_NOMINATED)
        self.addon = Addon.objects.get(pk=self.addon.id)
        assert_close_to_now(self.addon.nomination_date)

    def test_purgatory_to_lite(self):
        self.check(amo.STATUS_PURGATORY, self.lite_url, amo.STATUS_UNREVIEWED)

    def test_purgatory_to_public(self):
        eq_(self.addon.nomination_date, None)
        self.check(amo.STATUS_PURGATORY, self.public_url,
                   amo.STATUS_NOMINATED)
        self.addon = Addon.objects.get(pk=self.addon.id)
        assert_close_to_now(self.addon.nomination_date)

    def test_lite_and_nominated_to_public(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.check_400(self.public_url)

    def test_lite_and_nominated(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.check_400(self.lite_url)
        self.check_400(self.public_url)

    def test_renominate_for_full_review(self):
        # When a version is rejected, the addon is disabled.
        # The author must upload a new version and re-nominate.
        self.addon.update(
                # Pretend it was nominated in the past:
                nomination_date=datetime.now() - timedelta(days=30))
        self.check(amo.STATUS_NULL, self.public_url, amo.STATUS_NOMINATED)
        assert_close_to_now(self.get_addon().nomination_date)


class TestRedirects(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.base = reverse('devhub.index')
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def test_edit(self):
        url = self.base + 'addon/edit/3615'
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, reverse('devhub.addons.edit', args=['a3615']),
                             301)

        url = self.base + 'addon/edit/3615/'
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, reverse('devhub.addons.edit', args=['a3615']),
                             301)

    def test_status(self):
        url = self.base + 'addon/status/3615'
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, reverse('devhub.versions', args=['a3615']),
                             301)

    def test_versions(self):
        url = self.base + 'versions/3615'
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, reverse('devhub.versions', args=['a3615']),
                             301)
