from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode

from mock import Mock, patch
from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.users.models import UserProfile
from olympia.users.forms import AdminUserEditForm, UserEditForm


class UserFormBase(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(UserFormBase, self).setUp()
        self.user = self.user_profile = UserProfile.objects.get(id='4043307')
        self.uidb64 = urlsafe_base64_encode(str(self.user.id))
        self.token = default_token_generator.make_token(self.user)


class TestUserDeleteForm(UserFormBase):

    def test_bad_email(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        data = {'email': 'wrong@example.com', 'confirm': True}
        r = self.client.post('/en-US/firefox/users/delete', data)
        msg = "Email must be jbalogh@mozilla.com."
        self.assertFormError(r, 'form', 'email', msg)

    def test_not_confirmed(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        data = {'email': 'jbalogh@mozilla.com'}
        r = self.client.post('/en-US/firefox/users/delete', data)
        self.assertFormError(r, 'form', 'confirm', 'This field is required.')

    def test_success(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        data = {'email': 'jbalogh@mozilla.com', 'confirm': True}
        self.client.post('/en-US/firefox/users/delete', data, follow=True)
        # TODO XXX: Bug 593055
        # self.assertContains(r, "Profile Deleted")
        u = UserProfile.objects.get(id=4043307)
        assert u.deleted
        assert u.email is None

    @patch('olympia.users.models.UserProfile.is_developer')
    def test_developer_attempt(self, f):
        """A developer's attempt to delete one's self must be thwarted."""
        f.return_value = True
        self.client.login(username='jbalogh@mozilla.com', password='password')
        data = {'email': 'jbalogh@mozilla.com', 'confirm': True}
        r = self.client.post('/en-US/firefox/users/delete', data, follow=True)
        self.assertContains(r, 'You cannot delete your account')


class TestUserEditForm(UserFormBase):

    def setUp(self):
        super(TestUserEditForm, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.url = reverse('users.edit')

    def test_no_username_or_display_name(self):
        assert not self.user.has_anonymous_username()
        data = {'username': '',
                'email': 'jbalogh@mozilla.com',
                'lang': 'pt-BR'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().has_anonymous_username()

    def test_change_username(self):
        assert self.user.username != 'new-username'
        data = {'username': 'new-username',
                'email': 'jbalogh@mozilla.com',
                'lang': 'fr'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().username == 'new-username'

    def test_no_username_anonymous_does_not_change(self):
        """Test that username isn't required with auto-generated usernames and
        the auto-generated value does not change."""
        username = self.user.anonymize_username()
        self.user.save()
        data = {'username': '',
                'email': 'jbalogh@mozilla.com',
                'lang': 'en-US'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().username == username

    def test_fxa_id_cannot_be_set(self):
        assert self.user.fxa_id is None
        data = {'username': 'blah',
                'email': 'jbalogh@mozilla.com',
                'fxa_id': 'yo',
                'lang': 'en-US'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().fxa_id is None

    def test_no_real_name(self):
        data = {'username': 'blah',
                'email': 'jbalogh@mozilla.com',
                'lang': 'en-US'}
        r = self.client.post(self.url, data, follow=True)
        self.assertContains(r, 'Profile Updated')

    def test_cannot_set_password(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh@mozilla.com',
                'oldpassword': 'password',
                'password': 'longer123',
                'password2': 'longer123',
                'lang': 'en-US'}
        assert self.user.check_password('password')
        r = self.client.post(self.url, data, follow=True)
        self.assertContains(r, 'Profile Updated')
        self.user.reload()
        assert self.user.check_password('password')
        assert not self.user.check_password('longer123')

    def test_long_data(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh@mozilla.com',
                'oldpassword': 'password',
                'password': 'new',
                'password2': 'new',
                'lang': 'en-US'}
        for field, length in (('username', 50), ('display_name', 50),
                              ('location', 100), ('occupation', 100)):
            data[field] = 'x' * (length + 1)
            r = self.client.post(self.url, data, follow=True)
            err = u'Ensure this value has at most %s characters (it has %s).'
            self.assertFormError(r, 'form', field, err % (length, length + 1))

    @patch('olympia.amo.models.ModelBase.update')
    def test_photo_modified(self, update_mock):
        dummy = Mock()
        dummy.user = self.user

        data = {'username': self.user_profile.username,
                'email': self.user_profile.email,
                'lang': 'en-US'}
        files = {'photo': get_uploaded_file('transparent.png')}
        form = UserEditForm(data, files=files, instance=self.user_profile,
                            request=dummy)
        assert form.is_valid()
        form.save()
        assert update_mock.called

    def test_lang_initial(self):
        """If no lang is set on the user, initial value is current locale."""
        # Lang is already set: don't change it.
        res = self.client.get(self.url)
        form = res.context['form']
        assert form.initial['lang'] == 'en-US'

        with self.activate('fr'):
            res = self.client.get(reverse('users.edit'))
            form = res.context['form']
            assert form.initial['lang'] == 'en-US'

        # Lang isn't set yet: initial value is set to the current locale.
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        user.lang = None
        user.save()

        res = self.client.get(self.url)
        form = res.context['form']
        assert form.initial['lang'] == 'en-US'

        with self.activate('fr'):
            res = self.client.get(reverse('users.edit'))
            form = res.context['form']
            assert form.initial['lang'] == 'fr'

    def test_cannot_change_email(self):
        self.user.update(fxa_id='1a2b3c', email='me@example.com')
        form = UserEditForm(
            {'email': 'noway@example.com', 'lang': 'de'}, instance=self.user)
        assert form.is_valid()
        form.save()
        assert self.user.reload().email == 'me@example.com'


class TestAdminUserEditForm(UserFormBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAdminUserEditForm, self).setUp()
        self.client.login(username='admin@mozilla.com', password='password')
        self.url = reverse('users.admin_edit', args=[self.user.id])

    def test_delete_link(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        assert pq(r.content)('a.delete').attr('href') == (
            reverse('admin:users_userprofile_delete', args=[self.user.id]))

    def test_can_change_email(self):
        assert self.user.email != 'nobody@mozilla.org'
        form = AdminUserEditForm({
            'email': 'nobody@mozilla.org',
            'lang': 'fr',
            'admin_log': 'Change email',
        }, instance=self.user)
        assert form.is_valid(), form.errors
        form.save()
        self.user.reload()
        assert self.user.email == 'nobody@mozilla.org'


class TestBlacklistedNameAdminAddForm(UserFormBase):

    def test_no_usernames(self):
        self.client.login(username='testo@example.com', password='password')
        url = reverse('admin:users_blacklistedname_add')
        data = {'names': "\n\n", }
        r = self.client.post(url, data)
        msg = 'Please enter at least one name to blacklist.'
        self.assertFormError(r, 'form', 'names', msg)

    def test_add(self):
        self.client.login(username='testo@example.com', password='password')
        url = reverse('admin:users_blacklistedname_add')
        data = {'names': "IE6Fan\nfubar\n\n", }
        r = self.client.post(url, data)
        msg = '1 new values added to the blacklist. '
        msg += '1 duplicates were ignored.'
        self.assertContains(r, msg)
        self.assertNotContains(r, 'fubar')
