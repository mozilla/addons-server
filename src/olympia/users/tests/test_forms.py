from django.utils.http import urlsafe_base64_encode
from django.core.files.uploadedfile import SimpleUploadedFile

from mock import Mock, patch, MagicMock
from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase, addon_factory, create_switch
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.amo.urlresolvers import reverse
from olympia.users.forms import AdminUserEditForm, UserEditForm
from olympia.users.models import UserProfile


class UserFormBase(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(UserFormBase, self).setUp()
        self.user = self.user_profile = UserProfile.objects.get(id='4043307')
        self.uidb64 = urlsafe_base64_encode(str(self.user.id))


class TestUserDeleteForm(UserFormBase):

    def test_bad_email(self):
        self.client.login(email='jbalogh@mozilla.com')
        data = {'email': 'wrong@example.com', 'confirm': True}
        r = self.client.post('/en-US/firefox/users/delete', data)
        msg = "Email must be jbalogh@mozilla.com."
        self.assertFormError(r, 'form', 'email', msg)

    def test_not_confirmed(self):
        self.client.login(email='jbalogh@mozilla.com')
        data = {'email': 'jbalogh@mozilla.com'}
        r = self.client.post('/en-US/firefox/users/delete', data)
        self.assertFormError(r, 'form', 'confirm', 'This field is required.')

    def test_success(self):
        self.client.login(email='jbalogh@mozilla.com')
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
        self.client.login(email='jbalogh@mozilla.com')
        data = {'email': 'jbalogh@mozilla.com', 'confirm': True}
        r = self.client.post('/en-US/firefox/users/delete', data, follow=True)
        self.assertContains(r, 'You cannot delete your account')


class TestUserEditForm(UserFormBase):

    def setUp(self):
        super(TestUserEditForm, self).setUp()
        self.client.login(email='jbalogh@mozilla.com')
        self.url = reverse('users.edit')

    def test_no_username_or_display_name(self):
        assert not self.user.has_anonymous_username
        data = {'username': '',
                'email': 'jbalogh@mozilla.com'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().has_anonymous_username

    def test_change_username(self):
        assert self.user.username != 'new-username'
        data = {'username': 'new-username',
                'email': 'jbalogh@mozilla.com'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().username == 'new-username'

    def test_cannot_change_display_name_to_denied_ones(self):
        assert self.user.display_name != 'Mozilla'
        data = {'username': 'new-username',
                'display_name': 'IE6Fan',
                'email': 'jbalogh@mozilla.com'}
        response = self.client.post(self.url, data)
        msg = "This display name cannot be used."
        self.assertFormError(response, 'form', 'display_name', msg)
        assert self.user.reload().display_name != 'IE6Fan'

    def test_no_username_anonymous_does_not_change(self):
        """Test that username isn't required with auto-generated usernames and
        the auto-generated value does not change."""
        username = self.user.anonymize_username()
        self.user.save()
        data = {'username': '',
                'email': 'jbalogh@mozilla.com'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().username == username

    def test_fxa_id_cannot_be_set(self):
        assert self.user.fxa_id is None
        data = {'username': 'blah',
                'email': 'jbalogh@mozilla.com',
                'fxa_id': 'yo'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().fxa_id is None

    def test_no_real_name(self):
        data = {'username': 'blah',
                'email': 'jbalogh@mozilla.com'}
        r = self.client.post(self.url, data, follow=True)
        self.assertContains(r, 'Profile Updated')

    def test_long_data(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh@mozilla.com'}
        for field, length in (('username', 50), ('display_name', 50),
                              ('location', 100), ('occupation', 100)):
            data[field] = 'x' * (length + 1)
            r = self.client.post(self.url, data, follow=True)
            err = u'Ensure this value has at most %s characters (it has %s).'
            self.assertFormError(r, 'form', field, err % (length, length + 1))

    @patch('olympia.amo.models.ModelBase.update')
    def test_photo_modified(self, update_mock):
        request = Mock()
        request.user = self.user
        data = {'username': self.user_profile.username,
                'email': self.user_profile.email}
        files = {'photo': get_uploaded_file('transparent.png')}
        form = UserEditForm(data, files=files, instance=self.user_profile,
                            request=request)
        assert form.is_valid()
        form.save()
        assert update_mock.called

    def test_photo_invalid_though_content_type_is_correct(self):
        request = Mock()
        request.user = self.user
        data = {'username': self.user_profile.username,
                'email': self.user_profile.email}
        files = {'photo': get_uploaded_file('non-image.png')}
        form = UserEditForm(data, files=files, instance=self.user_profile,
                            request=request)

        assert not form.is_valid()
        assert form.errors == {'photo': [u'Images must be either PNG or JPG.']}

    def test_photo_invalid_gif(self):
        request = Mock()
        request.user = self.user
        data = {'username': self.user_profile.username,
                'email': self.user_profile.email}
        files = {'photo': get_uploaded_file('animated.gif')}
        form = UserEditForm(data, files=files, instance=self.user_profile,
                            request=request)

        assert not form.is_valid()
        assert form.errors == {'photo': [u'Images must be either PNG or JPG.']}

    def test_photo_invalid_animated(self):
        request = Mock()
        request.user = self.user
        data = {'username': self.user_profile.username,
                'email': self.user_profile.email}
        files = {'photo': get_uploaded_file('animated.png')}
        form = UserEditForm(data, files=files, instance=self.user_profile,
                            request=request)

        assert not form.is_valid()
        assert form.errors == {'photo': [u'Images cannot be animated.']}

    @patch('olympia.amo.utils.ImageCheck.is_image')
    @patch('olympia.amo.utils.ImageCheck.is_animated')
    def test_photo_too_big(self, mock_is_image_check, mock_is_animated_check):
        # Mock the ImageCheck object to pass checks on the uploaded image
        mock_is_image_check.return_value = True
        mock_is_image_check.return_value = False
        mock_is_animated_check.returned_value = False

        request = Mock()
        request.user = self.user
        data = {'username': self.user_profile.username,
                'email': self.user_profile.email}
        files = {'photo': get_uploaded_file('transparent.png')}
        form = UserEditForm(data, files=files, instance=self.user_profile,
                            request=request)

        # Creating the mock object instead of the uploaded file,
        # with a specific size over the limit
        upload_mock = MagicMock(spec=SimpleUploadedFile)
        upload_mock._name = 'transparent.png'
        upload_mock.size = 4 * 1024 * 1024 + 1
        upload_mock.content_type = 'image/png'

        # Injecting the mock object
        form.files['photo'] = upload_mock

        assert not form.is_valid()
        mock_is_image_check.assert_called()
        mock_is_animated_check.assert_called()
        assert form.errors == {
            'photo': [u'Please use images smaller than 4MB.']
        }

    def test_cannot_change_email(self):
        self.user.update(fxa_id='1a2b3c', email='me@example.com')
        form = UserEditForm(
            {'email': 'noway@example.com'}, instance=self.user)
        assert form.is_valid()
        form.save()
        assert self.user.reload().email == 'me@example.com'

    def test_only_show_notifications_user_has_permission_to(self):
        create_switch('activate-basket-sync')

        with patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok', 'token': '123', 'newsletters': []}

            form = UserEditForm({}, instance=self.user)

        request_call.assert_called_with(
            'get', 'lookup-user',
            headers={'x-api-key': 'testkey'},
            params={'email': u'jbalogh@mozilla.com'})

        # It needs a developer account to subscribe to a newsletter
        # So the `announcements` notification is not among the valid choices
        # This isn't really user visible since the user doesn't have
        # the ability to choose newsletters he doesn't have permissions
        # to see.
        assert len(form.fields['notifications'].choices) == 2
        assert form.fields['notifications'].choices[0][0] == 3
        assert form.fields['notifications'].choices[1][0] == 4

        addon_factory(users=[self.user])

        # Clear cache
        del self.user.is_developer

        form = UserEditForm({}, instance=self.user)
        assert len(form.fields['notifications'].choices) == 10
        assert [x[0] for x in form.fields['notifications'].choices] == [
            3, 4, 5, 6, 7, 9, 10, 11, 12, 8
        ]

    def test_basket_unsubscribe_newsletter(self):
        create_switch('activate-basket-sync')

        with patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok', 'token': '123',
                'newsletters': ['announcements']}

            form = UserEditForm({}, instance=self.user)

        request_call.assert_called_with(
            'get', 'lookup-user',
            headers={'x-api-key': 'testkey'},
            params={'email': u'jbalogh@mozilla.com'})

        with patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok', 'token': '123',
                'newsletters': []}
            assert form.is_valid()
            form.save()

        request_call.assert_called_with(
            'post', 'unsubscribe',
            data={
                'newsletters': 'about-addons',
                'email': u'jbalogh@mozilla.com'},
            token='123')

    def test_basket_subscribe_newsletter(self):
        create_switch('activate-basket-sync')

        addon_factory(users=[self.user])

        with patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok', 'token': '123',
                'newsletters': []}

            # 8 is the `announcements` notification, or about-addons newsletter
            form = UserEditForm(
                {'notifications': [3, 4, 8]},
                instance=self.user)

        request_call.assert_called_with(
            'get', 'lookup-user',
            headers={'x-api-key': 'testkey'},
            params={'email': u'jbalogh@mozilla.com'})

        with patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok', 'token': '123',
                'newsletters': ['about-addons']}

            assert form.is_valid()
            form.save()

        request_call.assert_called_with(
            'post', 'subscribe',
            headers={},
            data={
                'newsletters': 'about-addons',
                'email': u'jbalogh@mozilla.com'})

    def test_basket_sync_behind_flag(self):

        with patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok', 'token': '123',
                'newsletters': ['announcements']}

            UserEditForm({}, instance=self.user)

        assert request_call.call_count == 0


class TestAdminUserEditForm(UserFormBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAdminUserEditForm, self).setUp()
        self.client.login(email='admin@mozilla.com')
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
            'admin_log': 'Change email',
        }, instance=self.user)
        assert form.is_valid(), form.errors
        form.save()
        self.user.reload()
        assert self.user.email == 'nobody@mozilla.org'


class TestDeniedNameAdminAddForm(UserFormBase):

    def test_no_usernames(self):
        self.client.login(email='testo@example.com')
        url = reverse('admin:users_deniedname_add')
        data = {'names': "\n\n", }
        r = self.client.post(url, data)
        msg = 'Please enter at least one name to be denied.'
        self.assertFormError(r, 'form', 'names', msg)

    def test_add(self):
        self.client.login(email='testo@example.com')
        url = reverse('admin:users_deniedname_add')
        data = {'names': "IE6Fan\nfubar\n\n", }
        r = self.client.post(url, data)
        msg = '1 new values added to the deny list. '
        msg += '1 duplicates were ignored.'
        self.assertContains(r, msg)
        self.assertNotContains(r, 'fubar')
