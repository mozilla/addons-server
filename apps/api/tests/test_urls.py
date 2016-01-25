from django.contrib.auth.models import AnonymousUser
from django.test.client import RequestFactory

from mock import Mock

from amo.tests import TestCase
from amo.urlresolvers import reverse
from users.models import UserProfile

from ..urls import SwitchToDRF


class TestDRFSwitch(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestDRFSwitch, self).setUp()
        self.factory = RequestFactory()
        self.user = UserProfile.objects.get(email='del@icio.us')

    def test_responses(self):
        view = SwitchToDRF('Language')
        request = self.factory.get(reverse('api.language', args=['1.5']))
        request.APP = Mock(id=1)
        request.user = AnonymousUser()
        assert view(request, api_version=1.5).__module__ == 'django.http.response'
        piston_response = view(request, api_version=1.5).content

        self.create_switch('drf')
        assert view(request, api_version=1.5).__module__ == 'rest_framework.response'

        drf_response = view(request, api_version=1.5).render().content
        assert piston_response == drf_response

    def test_responses_with_handler(self):
        view = SwitchToDRF('Addons', with_handler=True, with_viewset=True)
        request = self.factory.get(reverse('api.addons'))

        class App():
            id = 1

            def __str__(self):
                return str(self.id)

        request.APP = App()
        request.user = AnonymousUser()

        assert view(request).__module__ == 'django.http.response'
        self.create_switch('drf')
        assert view(request).__module__ == 'rest_framework.response'

    def test_wrong_format_exceptions(self):
        view = SwitchToDRF('Language')
        request = self.factory.get(reverse('api.language', args=['1.5']))
        request.APP = Mock(id=1)
        request.GET = {'format': 'foo'}
        request.user = AnonymousUser()
        response = view(request, api_version=1.5)
        assert response.content == '{"msg": "Not implemented yet."}'
        assert response.status_code == 200

        self.create_switch('drf')
        response = view(request, api_version=1.5)
        assert '<error>Not found</error>' in response.render().content
        assert response.status_code == 404
