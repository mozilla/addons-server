import amo
import amo.tests
from payments.models import InappConfig
from webapps.models import Webapp

from nose.tools import eq_


class TestInapp(amo.tests.TestCase):

    def setUp(self):
        self.app = Webapp.objects.create(manifest_url='http://foo.ca')
        self.inapp = InappConfig.objects.create(addon=self.app,
                                                private_key='asd',
                                                public_key='asd')

    def test_active(self):
        eq_(self.inapp.is_active(), False)
        self.inapp.update(status=amo.INAPP_STATUS_ACTIVE)
        eq_(self.inapp.is_active(), True)

    def test_any_active(self):
        assert not InappConfig.any_active(self.app)
        InappConfig.objects.create(addon=self.app,
                                   status=amo.INAPP_STATUS_ACTIVE,
                                   private_key='asd-1', public_key='asd-1')
        assert InappConfig.any_active(self.app)
        self.assertRaises(ValueError, InappConfig.objects.create,
                          addon=self.app, status=amo.INAPP_STATUS_ACTIVE,
                          private_key='asd-2', public_key='asd-2')
