from cake.models import Session
from test_utils import TestCase
from .acl import match_rules


def test_match_rules():
    """
    Unit tests for the match_rules method.
    """

    rules = ('*:*',
        'Editors:*,Admin:EditAnyAddon,Admin:flagged,Admin:addons,'
        'Admin:EditAnyCollection',
        'Tests:*,Admin:serverstatus,Admin:users',
        'Admin:EditAnyAddon,Admin:EditAnyLocale,Editors:*,'
        'Admin:lists,Admin:applications,Admin:addons,Localizers:*',
        'Admin:EditAnyAddon',
        'Admin:ViewAnyStats,Admin:ViewAnyCollectionStats',
        'Admin:ViewAnyStats',
        'Editors:*,Admin:features',
        'Admin:Statistics',
        'Admin:Features,Editors:*',
        'Admin:%',
        'Admin:*',
        'Admin:Foo',
        'Admin:Bar',
        )

    for rule in rules:
        assert match_rules(rule, 'Admin', '%'), "%s != Admin:%%" % rule

    rules = ('Doctors:*',)

    for rule in rules:
        assert not match_rules(rule, 'Admin', '%'), \
            "%s == Admin:%% and shouldn't" % rule


class ACLTestCase(TestCase):
    """
    Test some basic ACLs by going to various locked pages on AMO.
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
