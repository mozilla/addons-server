from django.utils.encoding import force_text
from django.utils.http import urlsafe_base64_encode

from six import binary_type

from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.users.models import UserProfile


class UserFormBase(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(UserFormBase, self).setUp()
        self.user = self.user_profile = UserProfile.objects.get(id='4043307')
        # need to keep this force_text because pre django2.2
        # urlsafe_base64_encode returns a bytestring and a string after
        self.uidb64 = force_text(
            urlsafe_base64_encode(binary_type(self.user.id)))


class TestDeniedNameAdminAddForm(UserFormBase):

    def test_no_usernames(self):
        self.client.login(email='testo@example.com')
        url = reverse('admin:users_deniedname_add')
        data = {'names': "\n\n", }
        r = self.client.post(url, data)
        self.assertFormError(r, 'form', 'names', u'This field is required.')

    def test_add(self):
        self.client.login(email='testo@example.com')
        url = reverse('admin:users_deniedname_add')
        data = {'names': "IE6Fan\nfubar\n\n", }
        r = self.client.post(url, data)
        msg = '1 new values added to the deny list. '
        msg += '1 duplicates were ignored.'
        self.assertContains(r, msg)
        self.assertNotContains(r, 'fubar')
