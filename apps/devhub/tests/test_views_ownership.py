"""Tests related to the ``devhub.addons.owner`` view."""
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from amo.tests import formset
from addons.models import Addon, AddonUser
from devhub.forms import LicenseForm
from devhub.models import ActivityLog
from versions.models import License, Version


class TestOwnership(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.url = self.addon.get_dev_url('owner')
        assert self.client.login(username='del@icio.us', password='password')

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

    def test_edit_eula_locale(self):
        self.addon.eula = {'de': 'some eula', 'en-US': ''}
        self.addon.save()
        res = self.client.get(self.url.replace('en-US', 'it'))
        doc = pq(res.content)
        eq_(doc('#id_has_eula').attr('checked'), 'checked')


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
        doc = pq(unicode(LicenseForm(addon=self.version.addon)))
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

    def test_reorder_authors(self):
        """
        Re-ordering authors should not generate role changes in the
        ActivityLog.
        """
        # flip form-0-position
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=0)
        data = self.formset(f.initial, u, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u1 = f.initial
        u1['position'] = 1
        f = self.client.get(self.url).context['user_form'].initial_forms[1]
        u2 = f.initial
        data = self.formset(u1, u2)

        orig = ActivityLog.objects.all().count()
        r = self.client.post(self.url, data)
        self.assertRedirects(r, self.url, 302)
        eq_(ActivityLog.objects.all().count(), orig)

    def test_success_add_user(self):
        q = (AddonUser.objects.no_cache().filter(addon=3615)
             .values_list('user', flat=True))
        eq_(list(q.all()), [55021])

        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=0)
        data = self.formset(f.initial, u, initial_count=1)
        r = self.client.post(self.url, data)
        self.assertRedirects(r, self.url, 302)
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
        self.assertRedirects(r, self.url, 302)
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

    def test_switch_owner(self):
        # See if we can transfer ownership in one POST.
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['user'] = 'regular@mozilla.com'
        data = self.formset(f.initial, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(999, AddonUser.objects.get(addon=3615).user_id)
        eq_(ActivityLog.objects.filter(
            action=amo.LOG.ADD_USER_WITH_ROLE.id).count(), 1)
        eq_(ActivityLog.objects.filter(
            action=amo.LOG.REMOVE_USER_WITH_ROLE.id).count(), 1)

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
