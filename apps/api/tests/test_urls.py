from mock import Mock
from nose.tools import eq_
from test_utils import RequestFactory

from django.contrib.auth.models import AnonymousUser

from amo.tests import TestCase
from amo.urlresolvers import reverse
from users.models import UserProfile

from ..urls import SwitchToDRF


class TestDRFSwitch(TestCase):
    fixtures = ['base/addon_3615',]

    def setUp(self):
        self.factory = RequestFactory()
        self.user = UserProfile.objects.get(email='del@icio.us')

    def test_responses(self):
        view = SwitchToDRF('Language')
        request = self.factory.get(reverse('api.language', args=['1.5']))
        request.APP = Mock(id=1)
        request.user = AnonymousUser()
        eq_(view(request, api_version=1.5).__module__, 'django.http')
        piston_response = view(request, api_version=1.5).content
        self.create_switch('drf', db=True)
        eq_(view(request, api_version=1.5).__module__,
            'rest_framework.response')
        drf_response = view(request, api_version=1.5).render().content
        eq_(piston_response, drf_response)

    def test_responses_with_handler(self):
        view = SwitchToDRF('User', with_handler=True)
        request = self.factory.get(reverse('api.language', args=['2']))
        class App():
            id = 1
            def __str__(self):
                return str(self.id)
        request.APP = App()
        request.user = AnonymousUser()
        request.amo_user = self.user
        eq_(view(request, api_version=2).__module__, 'django.http')
        self.create_switch('drf', db=True)
        eq_(view(request, api_version=2).__module__, 'rest_framework.response')

    def test_wrong_format_exceptions(self):
        view = SwitchToDRF('Language')
        request = self.factory.get(reverse('api.language', args=['1.5']))
        request.APP = Mock(id=1)
        request.GET = {'format': 'foo'}
        request.user = AnonymousUser()
        response = view(request, api_version=1.5)
        eq_(response.content, '{"msg": "Not implemented yet."}')
        eq_(response.status_code, 200)
        self.create_switch('drf', db=True)
        response = view(request, api_version=1.5)
        self.assertTrue('<error>Not found</error>'
                        in response.render().content)
        eq_(response.status_code, 404)
