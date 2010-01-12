from cake.models import Session
from test_utils import TestCase


class ACLTestCase(TestCase):
    """
    Test some basic ACLs by going to various locked pages on AMO
    """

    fixtures = ['access/login.json']

    def test_admin_login_anon(self):
        """
        Login form for anonymous user on the admin page.
        """
        c = self.client
        response = c.get('/en-US/admin/models/')
        self.assertContains(response, 'login-form')

    def test_admin_login_adminuser(self):
        """
        No form should be present for an admin
        """
        c = self.client
        session = Session.objects.get(pk='1234')
        c.login(session=session)
        response = c.get('/en-US/admin/models/')
        assert response.context['user'].is_authenticated()
        self.assertNotContains(response, 'login-form')

    def test_admin_login(self):
        """
        Non admin user should see a login form.
        """

        c = self.client
        session = Session.objects.get(pk='4567')
        c.login(session=session)
        response = c.get('/en-US/admin/models/')
        self.assertContains(response, 'login-form')
