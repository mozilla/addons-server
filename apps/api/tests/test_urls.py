from mock import Mock
from nose.tools import eq_

from amo.tests import TestCase

from ..urls import SwitchToDRF


class TestDRFSwitch(TestCase):

    def test_piston_view(self):
        view = SwitchToDRF('LanguageView')
        eq_(view(Mock(), 1).__module__, 'django.http')
        self.create_switch('drf', db=True)
        eq_(view(Mock()).__module__, 'rest_framework.response')
