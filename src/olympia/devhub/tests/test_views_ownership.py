"""Tests related to the ``devhub.addons.owner`` view."""
from django.core import mail

from pyquery import PyQuery as pq

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import TestCase, formset
from olympia.devhub.forms import LicenseForm
from olympia.versions.models import License, Version


class TestOwnership(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestOwnership, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.url = self.addon.get_dev_url('owner')
        assert self.client.login(email='del@icio.us')

    def formset(self, *args, **kw):
        defaults = {'builtin': License.OTHER, 'text': 'filler'}
        defaults.update(kw)
        return formset(*args, **defaults)

    def get_version(self):
        return Version.objects.get(id=self.version.id)

    def get_addon(self):
        return Addon.objects.get(id=self.addon.id)


class TestEditPolicy(TestOwnership):

    def formset(self, *args, **kw):
        init = self.client.get(self.url).context['user_form'].initial_forms
        args = args + tuple(f.initial for f in init)
        return super(TestEditPolicy, self).formset(*args, **kw)

    def test_edit_eula(self):
        old_eula = self.addon.eula
        data = self.formset(eula='new eula', has_eula=True)
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        addon = self.get_addon()
        assert unicode(addon.eula) == 'new eula'
        assert addon.eula.id == old_eula.id

    def test_delete_eula(self):
        assert self.addon.eula
        response = self.client.post(self.url, self.formset(has_eula=False))
        assert response.status_code == 302
        assert self.get_addon().eula is None

    def test_edit_eula_locale(self):
        self.addon.eula = {'de': 'some eula', 'en-US': ''}
        self.addon.save()
        res = self.client.get(self.url.replace('en-US', 'it'))
        doc = pq(res.content)
        assert doc('#id_has_eula').attr('checked') == 'checked'

    def test_no_policy_form_for_static_themes(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'policy_form' not in response.context


class TestEditLicense(TestOwnership):

    def setUp(self):
        super(TestEditLicense, self).setUp()
        self.version.license = None
        self.version.save()
        self.license = License.objects.create(builtin=1, name='bsd',
                                              url='license.url', on_form=True)
        self.cc_license = License.objects.create(
            builtin=11, name='copyright', url='license.url',
            creative_commons=True, on_form=True)

    def formset(self, *args, **kw):
        init = self.client.get(self.url).context['user_form'].initial_forms
        args = args + tuple(f.initial for f in init)
        kw['initial_count'] = len(init)
        data = super(TestEditLicense, self).formset(*args, **kw)
        if 'text' not in kw:
            del data['text']
        return data

    def test_no_license(self):
        data = self.formset(builtin='')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        license_form = response.context['license_form']
        assert license_form.errors == {'builtin': [u'This field is required.']}

    def test_no_license_required_for_unlisted(self):
        self.make_addon_unlisted(self.addon)
        data = self.formset(builtin='')
        response = self.client.post(self.url, data)
        assert response.status_code == 302

    def test_success_add_builtin(self):
        data = self.formset(builtin=1)
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert self.license == self.get_version().license
        assert ActivityLog.objects.filter(
            action=amo.LOG.CHANGE_LICENSE.id).count() == 1

    def test_success_add_builtin_creative_commons(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)  # cc licenses for themes
        data = self.formset(builtin=11)
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert self.cc_license == self.get_version().license
        assert ActivityLog.objects.filter(
            action=amo.LOG.CHANGE_LICENSE.id).count() == 1

    def test_success_add_custom(self):
        data = self.formset(builtin=License.OTHER, text='text', name='name')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license = self.get_version().license
        assert unicode(license.text) == 'text'
        assert unicode(license.name) == 'name'
        assert license.builtin == License.OTHER

    def test_success_edit_custom(self):
        data = self.formset(builtin=License.OTHER, text='text', name='name')
        response = self.client.post(self.url, data)
        license_one = self.get_version().license

        data = self.formset(builtin=License.OTHER, text='woo', name='name')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license_two = self.get_version().license
        assert unicode(license_two.text) == 'woo'
        assert unicode(license_two.name) == 'name'
        assert license_two.builtin == License.OTHER
        assert license_two.id == license_one.id

    def test_success_switch_license(self):
        data = self.formset(builtin=1)
        response = self.client.post(self.url, data)
        license_one = self.get_version().license

        data = self.formset(builtin=License.OTHER, text='text', name='name')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license_two = self.get_version().license
        assert unicode(license_two.text) == 'text'
        assert unicode(license_two.name) == 'name'
        assert license_two.builtin == License.OTHER
        assert license_one != license_two

        # Make sure the old license wasn't edited.
        license = License.objects.get(builtin=1)
        assert unicode(license.name) == 'bsd'

        data = self.formset(builtin=1)
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license_three = self.get_version().license
        assert license_three == license_one

    def test_custom_has_text(self):
        data = self.formset(builtin=License.OTHER, name='name')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'license_form', None,
                             'License text is required when choosing Other.')

    def test_custom_has_name(self):
        data = self.formset(builtin=License.OTHER, text='text')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license = self.get_version().license
        assert unicode(license.text) == 'text'
        assert unicode(license.name) == 'Custom License'
        assert license.builtin == License.OTHER

    def test_no_version(self):
        # Make sure nothing bad happens if there's no version.
        self.addon.update(_current_version=None)
        Version.objects.all().delete()
        data = self.formset(builtin=License.OTHER, text='text')
        response = self.client.post(self.url, data)
        assert response.status_code == 302

    def test_license_details_links(self):
        # Check that builtin licenses get details links.
        doc = pq(unicode(LicenseForm(version=self.version)))
        for license in License.objects.builtins():
            radio = 'input.license[value="%s"]' % license.builtin
            assert doc(radio).parent().text() == (
                unicode(license.name) + ' Details')
            assert doc(radio + '+ a').attr('href') == license.url
        assert doc('input[name=builtin]:last-child').parent().text() == 'Other'

    def test_license_logs(self):
        data = self.formset(builtin=License.OTHER, text='text')
        self.version.addon.update(status=amo.STATUS_PUBLIC)
        self.client.post(self.url, data)
        assert ActivityLog.objects.all().count() == 1

        self.version.license = License.objects.all()[1]
        self.version.save()

        data = self.formset(builtin=License.OTHER, text='text')
        self.client.post(self.url, data)
        assert ActivityLog.objects.all().count() == 2


class TestEditAuthor(TestOwnership):

    def test_reorder_authors(self):
        """
        Re-ordering authors should not generate role changes in the
        ActivityLog.
        """
        # flip form-0-position
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        user_data = {
            'user': 'regular@mozilla.com',
            'listed': True,
            'role': amo.AUTHOR_ROLE_DEV,
            'position': 0
        }
        data = self.formset(form.initial, user_data, initial_count=1)
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        u1 = form.initial
        u1['position'] = 1
        form = self.client.get(self.url).context['user_form'].initial_forms[1]
        u2 = form.initial
        data = self.formset(u1, u2)

        orig = ActivityLog.objects.all().count()
        response = self.client.post(self.url, data)
        self.assert3xx(response, self.url, 302)
        assert ActivityLog.objects.all().count() == orig

    def test_success_add_user(self):
        qs = (AddonUser.objects.filter(addon=3615)
              .values_list('user', flat=True))
        assert list(qs.all()) == [55021]

        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        user_data = {
            'user': 'regular@mozilla.com',
            'listed': True,
            'role': amo.AUTHOR_ROLE_DEV,
            'position': 0
        }
        data = self.formset(form.initial, user_data, initial_count=1)
        response = self.client.post(self.url, data)
        self.assert3xx(response, self.url, 302)
        assert list(qs.all()) == [55021, 999]

        # An email has been sent to the authors to warn them.
        author_added = mail.outbox[0]
        assert author_added.subject == ('An author has been added to your '
                                        'add-on')
        # Make sure all the authors are aware of the addition.
        assert 'del@icio.us' in author_added.to  # The original author.
        assert 'regular@mozilla.com' in author_added.to  # The new one.

    def test_success_edit_user(self):
        # Add an author b/c we can't edit anything about the current one.
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        user_data = {
            'user': 'regular@mozilla.com',
            'listed': True,
            'role': amo.AUTHOR_ROLE_DEV,
            'position': 1
        }
        data = self.formset(form.initial, user_data, initial_count=1)
        self.client.post(self.url, data)
        assert AddonUser.objects.get(addon=3615, user=999).listed

        # Edit the user we just added.
        user_form = self.client.get(self.url).context['user_form']
        one, two = user_form.initial_forms
        del two.initial['listed']
        empty = {
            'user': '',
            'listed': True,
            'role': 5,
            'position': 0
        }
        data = self.formset(one.initial, two.initial, empty, initial_count=2)
        response = self.client.post(self.url, data)
        self.assert3xx(response, self.url, 302)
        assert not AddonUser.objects.get(addon=3615, user=999).listed

    def test_change_user_role(self):
        # Add an author b/c we can't edit anything about the current one.
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        user_data = {
            'user': 'regular@mozilla.com',
            'listed': True,
            'role': amo.AUTHOR_ROLE_DEV,
            'position': 1
        }
        data = self.formset(form.initial, user_data, initial_count=1)
        self.client.post(self.url, data)
        assert AddonUser.objects.get(addon=3615, user=999).listed

        # Edit the user we just added.
        user_form = self.client.get(self.url).context['user_form']
        one, two = user_form.initial_forms
        two.initial['role'] = amo.AUTHOR_ROLE_OWNER
        empty = {
            'user': '',
            'listed': True,
            'role': amo.AUTHOR_ROLE_OWNER,
            'position': 0
        }
        data = self.formset(one.initial, two.initial, empty, initial_count=2)
        response = self.client.post(self.url, data)
        self.assert3xx(response, self.url, 302)

        # An email has been sent to the authors to warn them.
        author_edit = mail.outbox[1]  # First mail was for the addition.
        assert author_edit.subject == ('An author has a role changed on your '
                                       'add-on')
        # Make sure all the authors are aware of the addition.
        assert 'del@icio.us' in author_edit.to  # The original author.
        assert 'regular@mozilla.com' in author_edit.to  # The edited one.

    def test_add_user_twice(self):
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        user_data = {
            'user': 'regular@mozilla.com',
            'listed': True,
            'role': amo.AUTHOR_ROLE_DEV,
            'position': 1
        }
        data = self.formset(
            form.initial, user_data, user_data, initial_count=1)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        assert response.context['user_form'].non_form_errors() == (
            ['An author can only be listed once.'])

    def test_success_delete_user(self):
        # Add a new user so we have one to delete.
        user_data = {
            'user': 'regular@mozilla.com',
            'listed': True,
            'role': amo.AUTHOR_ROLE_OWNER,
            'position': 1
        }
        data = self.formset(user_data, initial_count=0)
        self.client.post(self.url, data)

        one, two = self.client.get(self.url).context['user_form'].initial_forms
        one.initial['DELETE'] = True
        data = self.formset(one.initial, two.initial, initial_count=2)
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert 999 == AddonUser.objects.get(addon=3615).user_id

        # An email has been sent to the authors to warn them.
        author_delete = mail.outbox[1]  # First mail was for the addition.
        assert author_delete.subject == ('An author has been removed from your'
                                         ' add-on')
        # Make sure all the authors are aware of the addition.
        assert 'del@icio.us' in author_delete.to  # The original author.
        assert 'regular@mozilla.com' in author_delete.to  # The removed one.

    def test_switch_owner(self):
        # See if we can transfer ownership in one POST.
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        form.initial['user'] = 'regular@mozilla.com'
        data = self.formset(form.initial, initial_count=1)
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert 999 == AddonUser.objects.get(addon=3615).user_id
        assert ActivityLog.objects.filter(
            action=amo.LOG.ADD_USER_WITH_ROLE.id).count() == 1
        assert ActivityLog.objects.filter(
            action=amo.LOG.REMOVE_USER_WITH_ROLE.id).count() == 1

    def test_only_owner_can_edit(self):
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        user_data = {
            'user': 'regular@mozilla.com',
            'listed': True,
            'role': amo.AUTHOR_ROLE_DEV,
            'position': 0
        }
        data = self.formset(form.initial, user_data, initial_count=1)
        self.client.post(self.url, data)

        self.client.login(email='regular@mozilla.com')
        self.client.post(self.url, data, follow=True)

        # Try deleting the other AddonUser
        one, two = self.client.get(self.url).context['user_form'].initial_forms
        one.initial['DELETE'] = True
        data = self.formset(one.initial, two.initial, initial_count=2)
        response = self.client.post(self.url, data, follow=True)
        assert response.status_code == 403
        assert AddonUser.objects.filter(addon=3615).count() == 2

    def test_must_have_listed(self):
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        form.initial['listed'] = False
        data = self.formset(form.initial, initial_count=1)
        response = self.client.post(self.url, data)
        assert response.context['user_form'].non_form_errors() == (
            ['At least one author must be listed.'])

    def test_must_have_owner(self):
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        form.initial['role'] = amo.AUTHOR_ROLE_DEV
        data = self.formset(form.initial, initial_count=1)
        response = self.client.post(self.url, data)
        assert response.context['user_form'].non_form_errors() == (
            ['Must have at least one owner.'])

    def test_must_have_owner_delete(self):
        form = self.client.get(self.url).context['user_form'].initial_forms[0]
        form.initial['DELETE'] = True
        data = self.formset(form.initial, initial_count=1)
        response = self.client.post(self.url, data)
        assert response.context['user_form'].non_form_errors() == (
            ['Must have at least one owner.'])


class TestEditAuthorStaticTheme(TestEditAuthor):
    def setUp(self):
        super(TestEditAuthorStaticTheme, self).setUp()
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.cc_license = License.objects.create(
            builtin=11, url='license.url',
            creative_commons=True, on_form=True)

    def formset(self, *args, **kw):
        defaults = {'builtin': 11}
        defaults.update(kw)
        return formset(*args, **defaults)

    def test_reorder_authors(self):
        self.get_version().update(license=self.cc_license)
        super(TestEditAuthorStaticTheme, self).test_reorder_authors()
