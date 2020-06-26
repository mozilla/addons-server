"""Tests for ``devhub.views.ownership`` and ``devhub.views.invitation``."""
from django.conf import settings
from django.core import mail

from pyquery import PyQuery as pq

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import (
    Addon, AddonUser, AddonUserPendingConfirmation
)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, formset, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.devhub.forms import LicenseForm
from olympia.users.models import EmailUserRestriction, UserProfile
from olympia.versions.models import License, Version


class TestOwnership(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestOwnership, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.url = self.addon.get_dev_url('owner')
        assert self.client.login(email='del@icio.us')

    def build_form_data(self, data):
        """Build dict containing data that would be submitted by clients."""
        rval = {}
        license_data = {
            'builtin': self.version.license.builtin,
            'text': str(self.version.license.text)
        } if self.version and self.version.license else {}
        authors_data = [
            {'id': author.id, 'role': author.role, 'listed': author.listed,
             'position': author.position}
            for author in AddonUser.objects.filter(
                addon=self.addon).order_by('position')]
        authors_pending_confirmation_data = [
            {'id': author.id, 'role': author.role, 'listed': author.listed}
            for author in AddonUserPendingConfirmation.objects.filter(
                addon=self.addon).order_by('id')]
        rval.update(
            **license_data,
            **formset(
                *authors_data,
                prefix='user_form',
                initial_count=len(authors_data),
                total_count=len(authors_data),
            ),
            **formset(
                *authors_pending_confirmation_data,
                prefix='authors_pending_confirmation',
                initial_count=len(authors_pending_confirmation_data),
                total_count=len(authors_pending_confirmation_data),
            ),
        )
        rval.update(data)  # Separate .update() call to allow overrides.
        return rval

    def get_version(self):
        return Version.objects.get(id=self.version.id)

    def get_addon(self):
        return Addon.objects.get(id=self.addon.id)


class TestEditPolicy(TestOwnership):

    def test_edit_eula(self):
        old_eula = self.addon.eula
        data = self.build_form_data({'eula': 'new eula', 'has_eula': True})
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        addon = self.get_addon()
        assert str(addon.eula) == 'new eula'
        assert addon.eula.id == old_eula.id

    def test_delete_eula(self):
        assert self.addon.eula
        data = self.build_form_data({'has_eula': False})
        response = self.client.post(self.url, data)
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

    def test_no_license(self):
        data = self.build_form_data({'builtin': ''})
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        license_form = response.context['license_form']
        assert license_form.errors == {'builtin': [u'This field is required.']}

    def test_no_license_required_for_unlisted(self):
        self.make_addon_unlisted(self.addon)
        data = self.build_form_data({'builtin': ''})
        response = self.client.post(self.url, data)
        assert response.status_code == 302

    def test_success_add_builtin(self):
        data = self.build_form_data({'builtin': 1})
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert self.license == self.get_version().license
        assert ActivityLog.objects.filter(
            action=amo.LOG.CHANGE_LICENSE.id).count() == 1

    def test_success_add_builtin_creative_commons(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)  # cc licenses for themes
        data = self.build_form_data({'builtin': 11})
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert self.cc_license == self.get_version().license
        assert ActivityLog.objects.filter(
            action=amo.LOG.CHANGE_LICENSE.id).count() == 1

    def test_success_add_custom(self):
        data = self.build_form_data(
            {'builtin': License.OTHER, 'text': 'text', 'name': 'name'})
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license = self.get_version().license
        assert str(license.text) == 'text'
        assert str(license.name) == 'name'
        assert license.builtin == License.OTHER

    def test_success_edit_custom(self):
        data = self.build_form_data(
            {'builtin': License.OTHER, 'text': 'text', 'name': 'name'})
        response = self.client.post(self.url, data)
        license_one = self.get_version().license

        data = self.build_form_data(
            {'builtin': License.OTHER, 'text': 'woo', 'name': 'name'})
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license_two = self.get_version().license
        assert str(license_two.text) == 'woo'
        assert str(license_two.name) == 'name'
        assert license_two.builtin == License.OTHER
        assert license_two.id == license_one.id

    def test_success_switch_license(self):
        data = self.build_form_data({'builtin': 1})
        response = self.client.post(self.url, data)
        license_one = self.get_version().license

        data = self.build_form_data(
            {'builtin': License.OTHER, 'text': 'text', 'name': 'name'})
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license_two = self.get_version().license
        assert str(license_two.text) == 'text'
        assert str(license_two.name) == 'name'
        assert license_two.builtin == License.OTHER
        assert license_one != license_two

        # Make sure the old license wasn't edited.
        license = License.objects.get(builtin=1)
        assert str(license.name) == 'bsd'

        data = self.build_form_data({'builtin': 1})
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license_three = self.get_version().license
        assert license_three == license_one

    def test_custom_has_text(self):
        data = self.build_form_data(
            {'builtin': License.OTHER, 'name': 'name'})
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'license_form', None,
                             'License text is required when choosing Other.')

    def test_custom_has_name(self):
        data = self.build_form_data(
            {'builtin': License.OTHER, 'text': 'text'})
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        license = self.get_version().license
        assert str(license.text) == 'text'
        assert str(license.name) == 'Custom License'
        assert license.builtin == License.OTHER

    def test_no_version(self):
        # Make sure nothing bad happens if there's no version.
        self.addon.update(_current_version=None)
        Version.objects.all().delete()
        data = self.build_form_data(
            {'builtin': License.OTHER, 'text': 'text'})
        response = self.client.post(self.url, data)
        assert response.status_code == 302

    def test_license_details_links(self):
        # Check that builtin licenses get details links.
        doc = pq(str(LicenseForm(version=self.version)))
        for license in License.objects.builtins():
            radio = 'input.license[value="%s"]' % license.builtin
            assert doc(radio).parent().text() == (
                str(license.name) + ' Details')
            assert doc(radio + '+ a').attr('href') == license.url
        assert doc('input[name=builtin]:last-child').parent().text() == 'Other'

    def test_license_logs(self):
        data = self.build_form_data(
            {'builtin': License.OTHER, 'text': 'text'})
        self.version.addon.update(status=amo.STATUS_APPROVED)
        self.client.post(self.url, data)
        assert ActivityLog.objects.all().count() == 1

        self.version.license = License.objects.all()[1]
        self.version.save()

        data = self.build_form_data(
            {'builtin': License.OTHER, 'text': 'text'})
        self.client.post(self.url, data)
        assert ActivityLog.objects.all().count() == 2


class TestEditAuthor(TestOwnership):

    def test_reorder_authors(self):
        """
        Re-ordering authors should not generate role changes in the
        ActivityLog.
        """
        # First, add someone else manually in second position.
        AddonUser.objects.create(
            addon=self.addon,
            user=UserProfile.objects.get(email='regular@mozilla.com'),
            listed=True,
            role=amo.AUTHOR_ROLE_DEV,
            position=1)
        expected_authors = [
            'del@icio.us', 'regular@mozilla.com',
        ]
        assert list(AddonUser.objects.filter(addon=self.addon).values_list(
            'user__email', flat=True).order_by('position')) == expected_authors

        # Then, submit data for the position change.
        data = self.build_form_data({
            'user_form-0-position': 1,
            'user_form-1-position': 0,
        })
        original_activity_log_count = ActivityLog.objects.all().count()
        response = self.client.post(self.url, data)

        # Check the results.
        expected_authors = [
            'regular@mozilla.com', 'del@icio.us'
        ]
        self.assert3xx(response, self.url, 302)
        assert list(AddonUser.objects.filter(addon=self.addon).values_list(
            'user__email', flat=True).order_by('position')) == expected_authors
        assert ActivityLog.objects.all().count() == original_activity_log_count

    def test_success_add_user(self):
        additional_data = formset(
            {
                'user': 'regular@mozilla.com',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True
            },
            prefix='authors_pending_confirmation',
            total_count=1,
            initial_count=0)
        data = self.build_form_data(additional_data)
        assert not ActivityLog.objects.filter(
            action=amo.LOG.ADD_USER_WITH_ROLE.id).exists()
        assert len(mail.outbox) == 0

        response = self.client.post(self.url, data)
        self.assert3xx(response, self.url, 302)

        # New author is pending confirmation, hasn't been added to the
        # actual author list yet.
        expected_authors = ['del@icio.us']
        assert list(AddonUser.objects.filter(addon=self.addon).values_list(
            'user__email', flat=True).order_by('position')) == expected_authors
        expected_pending = ['regular@mozilla.com']
        assert list(AddonUserPendingConfirmation.objects.filter(
            addon=self.addon).values_list(
            'user__email', flat=True)) == expected_pending

        # A new ActivityLog has been added for this action.
        assert ActivityLog.objects.filter(
            action=amo.LOG.ADD_USER_WITH_ROLE.id).exists()

        # An email has been sent to the authors to warn them.
        invitation_url = absolutify(reverse(
            'devhub.addons.invitation', args=(self.addon.slug,)))
        assert len(mail.outbox) == 2
        author_added_email = mail.outbox[0]
        assert author_added_email.subject == (
            'An author has been added to your add-on')
        assert 'del@icio.us' in author_added_email.to  # The original author.
        author_confirmation_email = mail.outbox[1]
        assert author_confirmation_email.subject == (
            'Author invitation for Delicious Bookmarks')
        assert 'regular@mozilla.com' in author_confirmation_email.to
        assert invitation_url in author_confirmation_email.body
        assert settings.DOMAIN in author_confirmation_email.body

    def test_cant_add_if_display_name_is_none(self):
        regular = UserProfile.objects.get(email='regular@mozilla.com')
        regular.update(display_name=None)
        additional_data = formset(
            {
                'user': 'regular@mozilla.com',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True
            },
            prefix='authors_pending_confirmation',
            total_count=1,
            initial_count=0)
        data = self.build_form_data(additional_data)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        form = response.context['authors_pending_confirmation_form']
        assert not form.is_valid()
        assert form.errors == [
            {
                'user': ['The account needs a display name before it can be '
                         'added as an author.']
            }
        ]

    def test_cant_add_if_display_name_is_not_ok_for_a_developer(self):
        regular = UserProfile.objects.get(email='regular@mozilla.com')
        regular.update(display_name='1')
        additional_data = formset(
            {
                'user': 'regular@mozilla.com',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True
            },
            prefix='authors_pending_confirmation',
            total_count=1,
            initial_count=0)
        data = self.build_form_data(additional_data)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        form = response.context['authors_pending_confirmation_form']
        assert not form.is_valid()
        assert form.errors == [
            {
                'user': ['The account needs a display name before it can be '
                         'added as an author.']
            }
        ]

    def test_impossible_to_add_to_authors_directly(self):
        additional_data = formset(
            {
                'id': AddonUser.objects.get().pk,
                'user': 'del@icico.us',
                'role': amo.AUTHOR_ROLE_OWNER,
                'listed': True,
                'position': 0,
            },
            {
                'user': 'regular@mozilla.com',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True,
                'position': 1,
            },
            prefix='user_form',  # Add to the actual list of users directly.
            total_count=2,
            initial_count=1)
        data = self.build_form_data(additional_data)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        form = response.context['user_form']
        assert not form.is_valid()

        # This form tampering shouldn't have worked, the new user should not
        # have been added anywhere.
        expected_authors = ['del@icio.us']
        assert list(AddonUser.objects.filter(addon=self.addon).values_list(
            'user__email', flat=True).order_by('position')) == expected_authors
        expected_pending = []
        assert list(AddonUserPendingConfirmation.objects.filter(
            addon=self.addon).values_list(
            'user__email', flat=True)) == expected_pending

    def test_failure_add_non_existing_user(self):
        additional_data = formset(
            {
                'user': 'nonexistinguser@mozilla.com',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True
            },
            prefix='authors_pending_confirmation',
            total_count=1,
            initial_count=0)
        data = self.build_form_data(additional_data)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        form = response.context['authors_pending_confirmation_form']
        assert form.errors == [
            {
                'user': ['No user with that email.']
            }
        ]

    def test_failure_add_restricted_user(self):
        EmailUserRestriction.objects.create(
            email_pattern='regular@mozilla.com')
        additional_data = formset(
            {
                'user': 'regular@mozilla.com',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True
            },
            prefix='authors_pending_confirmation',
            total_count=1,
            initial_count=0)
        data = self.build_form_data(additional_data)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        form = response.context['authors_pending_confirmation_form']
        assert form.errors == [
            {
                'user': ['The email address used for your account is not '
                         'allowed for add-on submission.']
            }
        ]

    def test_cant_change_existing_author(self):
        # Make sure we can't directly edit the user email once an author has
        # been saved (forces changes to go through the confirmation flow).
        data = self.build_form_data(
            {'user_form-0-user': 'regular@mozilla.com'})
        response = self.client.post(self.url, data)
        # Form is considered valid because 'user' field is disabled, django
        # just ignores the posted data and uses the original user.
        self.assert3xx(response, self.url, 302)
        assert AddonUser.objects.filter(addon=self.addon).count() == 1
        assert AddonUser.objects.filter(
            addon=self.addon).get().user.email == 'del@icio.us'  # Not changed.

    def test_success_edit_user(self):
        # Try editing things about an author, since the one that is initially
        # present is the only owner & only listed we add another to be allowed
        # to edit in the first place.
        # (see also test_must_have_listed() and test_must_have_owner() below)
        second_author = AddonUser.objects.create(
            addon=self.addon,
            user=UserProfile.objects.get(email='regular@mozilla.com'),
            listed=False,
            role=amo.AUTHOR_ROLE_DEV,
            position=1)

        # Edit the user we just added.
        data = self.build_form_data({
            'user_form-1-listed': False,
            'user_form-1-role': amo.AUTHOR_ROLE_OWNER,
        })
        response = self.client.post(self.url, data)
        self.assert3xx(response, self.url, 302)
        second_author.reload()
        assert second_author.listed is False
        assert second_author.role == amo.AUTHOR_ROLE_OWNER

        # An email has been sent to the authors to warn them.
        author_edit = mail.outbox[0]
        assert author_edit.subject == (
            'An author role has been changed on your add-on'
        )
        # Make sure all the authors are aware of the addition.
        assert 'del@icio.us' in author_edit.to  # The original author.
        assert 'regular@mozilla.com' in author_edit.to  # The edited one.

    def test_add_user_twice_in_same_post(self):
        additional_data = formset(
            {
                'user': 'regular@mozilla.com',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True
            },
            {
                'user': 'regular@mozilla.com',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True
            },
            prefix='authors_pending_confirmation',
            total_count=2,
            initial_count=0)
        data = self.build_form_data(additional_data)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        form = response.context['authors_pending_confirmation_form']
        assert form.non_form_errors() == (
            ['An author can only be present once.']
        )

    def test_add_user_that_was_already_invited(self):
        AddonUserPendingConfirmation.objects.create(
            addon=self.addon,
            user=UserProfile.objects.get(email='regular@mozilla.com'),
            role=amo.AUTHOR_ROLE_DEV,
            listed=True,
        )
        additional_data = formset(
            {
                'id': AddonUserPendingConfirmation.objects.get().pk,
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True,
            },
            {
                'user': 'regular@mozilla.com',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True,
            },
            prefix='authors_pending_confirmation',
            total_count=2,
            initial_count=1)
        data = self.build_form_data(additional_data)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        form = response.context['authors_pending_confirmation_form']
        assert form.non_form_errors() == (
            ['An author can only be present once.']
        )

    def test_add_user_that_was_already_an_author(self):
        additional_data = formset(
            {
                'user': 'del@icio.us',
                'role': amo.AUTHOR_ROLE_DEV,
                'listed': True,
            },
            prefix='authors_pending_confirmation',
            total_count=1,
            initial_count=0)
        data = self.build_form_data(additional_data)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        form = response.context['authors_pending_confirmation_form']
        assert form.errors == [
            # This time the error can be attached directly to the field, so
            # it's not in non_form_errors().
            {'user': ['An author can only be present once.']}
        ]

    def test_edit_user_pending_confirmation(self):
        non_confirmed_author = AddonUserPendingConfirmation.objects.create(
            addon=self.addon,
            user=UserProfile.objects.get(email='regular@mozilla.com'),
            role=amo.AUTHOR_ROLE_DEV,
            listed=True,
        )
        data = self.build_form_data({
            'authors_pending_confirmation-0-listed': False,
            'authors_pending_confirmation-0-role': amo.AUTHOR_ROLE_OWNER,
        })
        response = self.client.post(self.url, data)
        self.assert3xx(response, self.url, 302)
        non_confirmed_author.reload()
        assert non_confirmed_author.listed is False
        assert non_confirmed_author.role == amo.AUTHOR_ROLE_OWNER

        # An email has been sent to the authors to warn them.
        author_edit = mail.outbox[0]
        assert author_edit.subject == (
            'An author role has been changed on your add-on'
        )
        # Make sure all the authors are aware of the addition.
        assert 'del@icio.us' in author_edit.to  # The original author.
        assert 'regular@mozilla.com' in author_edit.to  # The edited one.

    def test_delete_user_pending_confirmation(self):
        AddonUserPendingConfirmation.objects.create(
            addon=self.addon,
            user=UserProfile.objects.get(email='regular@mozilla.com'),
            role=amo.AUTHOR_ROLE_DEV,
            listed=True,
        )
        data = self.build_form_data({
            'authors_pending_confirmation-0-DELETE': True,
        })
        response = self.client.post(self.url, data)
        assert response.status_code == 302

        assert not AddonUserPendingConfirmation.objects.filter(
            addon=self.addon).exists()

        # An email has been sent to the authors to warn them.
        author_delete = mail.outbox[0]
        assert author_delete.subject == ('An author has been removed from your'
                                         ' add-on')
        # Make sure all the authors are aware of the addition.
        assert 'del@icio.us' in author_delete.to  # The original author.
        assert 'regular@mozilla.com' in author_delete.to  # The removed one.

    def test_delete_user(self):
        AddonUser.objects.create(
            addon=self.addon,
            user=UserProfile.objects.get(email='regular@mozilla.com'),
            role=amo.AUTHOR_ROLE_DEV,
            listed=True,
            position=1,
        )
        data = self.build_form_data({
            'user_form-1-DELETE': True,
        })
        response = self.client.post(self.url, data)
        assert response.status_code == 302

        assert not AddonUserPendingConfirmation.objects.filter(
            addon=self.addon).exists()

        # An email has been sent to the authors to warn them.
        author_delete = mail.outbox[0]
        assert author_delete.subject == ('An author has been removed from your'
                                         ' add-on')
        # Make sure all the authors are aware of the addition.
        assert 'del@icio.us' in author_delete.to  # The original author.
        assert 'regular@mozilla.com' in author_delete.to  # The removed one.

    def test_only_owner_can_edit(self):
        AddonUser.objects.create(
            addon=self.addon,
            user=UserProfile.objects.get(email='regular@mozilla.com'),
            role=amo.AUTHOR_ROLE_DEV,
            listed=True,
            position=1,
        )
        self.client.login(email='regular@mozilla.com')
        data = self.build_form_data({})
        response = self.client.post(self.url, data, follow=True)
        assert response.status_code == 403

    def test_owners_pending_confirmation_cant_edit_yet(self):
        AddonUserPendingConfirmation.objects.create(
            addon=self.addon,
            user=UserProfile.objects.get(email='regular@mozilla.com'),
            role=amo.AUTHOR_ROLE_OWNER,
            listed=True,
        )
        self.client.login(email='regular@mozilla.com')
        data = self.build_form_data({})
        response = self.client.post(self.url, data, follow=True)
        assert response.status_code == 403

    def test_must_have_listed(self):
        data = self.build_form_data({
            'user_form-0-listed': False
        })
        response = self.client.post(self.url, data)
        assert response.context['user_form'].non_form_errors() == (
            ['At least one author must be listed.'])

    def test_must_have_owner(self):
        data = self.build_form_data({
            'user_form-0-role': amo.AUTHOR_ROLE_DEV
        })
        response = self.client.post(self.url, data)
        assert response.context['user_form'].non_form_errors() == (
            ['Must have at least one owner.'])

    def test_must_have_owner_delete(self):
        AddonUser.objects.create(
            addon=self.addon,
            user=UserProfile.objects.get(email='regular@mozilla.com'),
            role=amo.AUTHOR_ROLE_DEV,
            listed=True,
            position=1,
        )
        data = self.build_form_data({
            'user_form-0-DELETE': True
        })
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
        self.version.update(license=self.cc_license)


class TestAuthorInvitation(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        self.user = user_factory()
        self.invitation = AddonUserPendingConfirmation.objects.create(
            addon=self.addon, user=self.user, role=amo.AUTHOR_ROLE_OWNER,
            listed=True)
        self.url = reverse('devhub.addons.invitation', args=(self.addon.slug,))
        self.client.login(email=self.user.email)

    def test_non_existent_addon(self):
        self.url = reverse('devhub.addons.invitation', args=('nopenopenope',))
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        assert response.status_code == 302

    def test_not_invited(self):
        self.invitation.delete()
        response = self.client.get(self.url, follow=True)
        self.assert3xx(
            response, self.addon.get_dev_url(),
            status_code=302, target_status_code=403)

    def test_post_not_invited(self):
        self.invitation.delete()
        response = self.client.post(self.url, {'accept': 'yes'}, follow=True)
        self.assert3xx(
            response, self.addon.get_dev_url(),
            status_code=302, target_status_code=403)

    def test_invited(self):
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_invited_by_pk(self):
        self.url = reverse('devhub.addons.invitation', args=(self.addon.pk,))
        self.test_invited()

    def test_post_accept(self):
        assert not AddonUser.objects.filter(
            addon=self.addon, user=self.user).exists()

        response = self.client.post(self.url, {'accept': 'yes'})
        self.assert3xx(response, self.addon.get_dev_url(), status_code=302)
        author = AddonUser.objects.get(addon=self.addon, user=self.user)
        assert author.role == self.invitation.role
        assert author.listed == self.invitation.listed
        assert not AddonUserPendingConfirmation.objects.filter(
            pk=self.invitation.pk).exists()
        return author

    def test_post_accept_deleted_before(self):
        deleted_addonuser = AddonUser.objects.create(
            addon=self.addon, user=self.user, role=amo.AUTHOR_ROLE_DELETED)
        assert not AddonUser.objects.filter(
            addon=self.addon, user=self.user).exists()
        assert AddonUser.unfiltered.filter(
            addon=self.addon, user=self.user).exists()

        response = self.client.post(self.url, {'accept': 'yes'})
        self.assert3xx(response, self.addon.get_dev_url(), status_code=302)
        author = AddonUser.objects.get(addon=self.addon, user=self.user)
        assert author == deleted_addonuser
        assert author.role == self.invitation.role
        assert author.listed == self.invitation.listed
        assert not AddonUserPendingConfirmation.objects.filter(
            pk=self.invitation.pk).exists()
        return author

    def test_post_accept_last_position(self):
        self.invitation.update(role=amo.AUTHOR_ROLE_DEV, listed=False)
        AddonUser.objects.create(
            addon=self.addon, user=user_factory(), position=42)
        author = self.test_post_accept()
        assert author.position == 43

    def test_post_refuse(self):
        response = self.client.post(self.url, {'accept': 'no'})
        self.assert3xx(response, reverse('devhub.addons'), status_code=302)
        assert not AddonUserPendingConfirmation.objects.filter(
            pk=self.invitation.pk).exists()

    def test_invitation_unlisted(self):
        self.make_addon_unlisted(self.addon)
        self.test_invited()
        self.test_post_accept()
