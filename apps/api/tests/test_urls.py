from mock import Mock
from nose.tools import eq_

from amo.tests import TestCase

from ..urls import SwitchToDRF


class TestDRFSwitch(TestCase):

    def test_piston_view(self):
        view = SwitchToDRF('LanguageView')
        eq_(view(Mock(), 1).__module__, 'django.http.response')
        self.create_switch('drf', db=True)
        eq_(view(Mock()).__module__, 'rest_framework.response')
from mock import Mock
from nose.tools import eq_
from test_utils import RequestFactory

from django.contrib.auth.models import AnonymousUser

from amo.tests import TestCase
from amo.urlresolvers import reverse

from ..urls import SwitchToDRF


class TestDRFSwitch(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def test_responses(self):
        view = SwitchToDRF('LanguageView')
        request = self.factory.get(reverse('api.language', args=['1.5']))
        request.APP = Mock(id=1)
        request.user = AnonymousUser()
        eq_(view(request, api_version=1.5).__module__, 'django.http.response')
        piston_response = view(request, api_version=1.5).content
        self.create_switch('drf', db=True)
        eq_(view(request, api_version=1.5).__module__,
            'rest_framework.response')
        drf_response = view(request, api_version=1.5).render().content
        eq_(piston_response, drf_response)

    def test_wrong_format_exceptions(self):
        view = SwitchToDRF('LanguageView')
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
