from datetime import datetime
import json

from django.conf import settings

from mock import Mock, patch
from nose.tools import eq_, ok_

from access.models import Group, GroupUser
from addons.models import AddonUser
from amo.tests import app_factory, TestCase
from test_utils import RequestFactory
from users.models import UserProfile

from mkt.api import authentication
from mkt.api.authentication import errors
from mkt.api.models import Access, generate
from mkt.api.tests.test_oauth import OAuthClient
from mkt.site.fixtures import fixture


class OwnerAuthorization(TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.profile = UserProfile.objects.get(pk=2519)
        self.user = self.profile.user

    def request(self, user=None):
        return Mock(amo_user=user, groups=user.groups.all() if user else None)

    def obj(self, user=None):
        return Mock(user=user)


class TestOwnerAuthorization(OwnerAuthorization):

    def setUp(self):
        super(TestOwnerAuthorization, self).setUp()
        self.auth = authentication.OwnerAuthorization()

    def test_user(self):
        ok_(self.auth.check_owner(self.request(self.profile),
                                  self.obj(self.user)))

    def test_not_user(self):
        ok_(not self.auth.check_owner(self.request(self.profile),
                                      self.obj()))

    def test_diff_user(self):
        user = Mock()
        user.pk = self.user.pk + 1
        ok_(not self.auth.check_owner(self.request(self.profile),
                                      self.obj(user)))

    def test_no_object(self):
        ok_(self.auth.is_authorized(None))

    def test_no_user(self):
        ok_(not self.auth.is_authorized(self.request(None), True))


class TestAppOwnerAuthorization(OwnerAuthorization):

    def setUp(self):
        super(TestAppOwnerAuthorization, self).setUp()
        self.auth = authentication.AppOwnerAuthorization()
        self.app = app_factory()

    def test_owner(self):
        AddonUser.objects.create(addon=self.app, user=self.profile)
        ok_(self.auth.check_owner(self.request(self.profile),
                                  self.app))

    def test_not_owner(self):
        ok_(not self.auth.check_owner(self.request(self.profile),
                                      self.app))


class TestPermissionAuthorization(OwnerAuthorization):

    def setUp(self):
        super(TestPermissionAuthorization, self).setUp()
        self.auth = authentication.PermissionAuthorization('Drinkers', 'Beer')
        self.app = app_factory()

    def test_has_role(self):
        self.grant_permission(self.profile, 'Drinkers:Beer')
        ok_(self.auth.is_authorized(self.request(self.profile), self.app))

    def test_not_has_role(self):
        self.grant_permission(self.profile, 'Drinkers:Scotch')
        ok_(not self.auth.is_authorized(self.request(self.profile), self.app))


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestMarketplaceAuthentication(TestCase):
    fixtures = fixture('user_2519', 'group_admin', 'group_editor')

    def setUp(self):
        self.api_name = 'foo'
        self.auth = authentication.MarketplaceAuthentication()
        self.profile = UserProfile.objects.get(pk=2519)
        self.profile.update(read_dev_agreement=datetime.today())
        self.access = Access.objects.create(key='foo', secret=generate(),
                                            user=self.profile.user)

    def call(self, client=None):
        url = ('api_dispatch_list', {'resource_name': 'app'})
        client = client or OAuthClient(self.access)
        url = client.get_absolute_url(url)
        return RequestFactory().get(url,
                 HTTP_HOST='api',
                 HTTP_AUTHORIZATION=client.header('GET', url))

    def test_accepted(self):
        ok_(self.auth.is_authenticated(self.call()))

    def test_no_agreement(self):
        self.profile.update(read_dev_agreement=None)
        res = self.auth.is_authenticated(self.call())
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'], errors['terms'])

    def test_request_token_fake(self):
        c = Mock()
        c.key = self.access.key
        c.secret = 'mom'
        res = self.auth.is_authenticated(self.call(client=OAuthClient(c)))
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'], errors['headers'])

    def add_group_user(self, user, *names):
        for name in names:
            group = Group.objects.get(name=name)
            GroupUser.objects.create(user=self.profile, group=group)

    def test_request_admin(self):
        self.add_group_user(self.profile, 'Admins')
        res = self.auth.is_authenticated(self.call())
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'], errors['roles'])

    def test_request_has_role(self):
        self.add_group_user(self.profile, 'App Reviewers')
        ok_(self.auth.is_authenticated(self.call()))


class TestOptionalAuthentication(TestCase):

    def setUp(self):
        self.auth = authentication.OptionalAuthentication()

    def test_none(self):
        req = RequestFactory().get('/')
        ok_(self.auth.is_authenticated(req))

    def test_something(self):
        req = RequestFactory().get('/', HTTP_AUTHORIZATION='No!')
        ok_(not self.auth.is_authenticated(req))
