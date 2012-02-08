import fudge
from nose.tools import eq_, raises

import amo
import amo.tests
from payments.models import InappConfig, TooManyKeyGenAttempts
from webapps.models import Webapp


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

    def test_any_active_excludes_config_under_edit(self):
        c = InappConfig.objects.create(addon=self.app,
                                       status=amo.INAPP_STATUS_ACTIVE,
                                       private_key='asd-1', public_key='asd-1')
        assert not InappConfig.any_active(self.app, exclude_config=c.pk)
        c.save()  # no exception

    def test_any_active(self):
        assert not InappConfig.any_active(self.app)
        InappConfig.objects.create(addon=self.app,
                                   status=amo.INAPP_STATUS_ACTIVE,
                                   private_key='asd-1', public_key='asd-1')
        assert InappConfig.any_active(self.app)
        self.assertRaises(ValueError, InappConfig.objects.create,
                          addon=self.app, status=amo.INAPP_STATUS_ACTIVE,
                          private_key='asd-2', public_key='asd-2')

    def test_generate_public_key(self):
        key = InappConfig.generate_public_key()
        assert key

    def test_generate_private_key(self):
        key = InappConfig.generate_private_key()
        assert key

    @raises(TooManyKeyGenAttempts)
    @fudge.patch('payments.models.InappConfig.objects.filter')
    def test_exhaust_private_keygen_attempts(self, fake_filter):
        fake_filter.expects_call().returns_fake().expects('count').returns(1)
        InappConfig.generate_private_key(max_tries=5)

    @raises(TooManyKeyGenAttempts)
    @fudge.patch('payments.models.InappConfig.objects.filter')
    def test_exhaust_public_keygen_attempts(self, fake_filter):
        fake_filter.expects_call().returns_fake().expects('count').returns(1)
        InappConfig.generate_public_key(max_tries=5)

    @fudge.patch('payments.models.InappConfig.objects.filter')
    def test_retry_private_keygen_until_unique(self, fake_filter):
        (fake_filter.expects_call().returns_fake().expects('count').returns(1)
                                                  .next_call().returns(1)
                                                  .next_call().returns(0))
        assert InappConfig.generate_private_key(max_tries=5)

    @fudge.patch('payments.models.InappConfig.objects.filter')
    def test_retry_public_keygen_until_unique(self, fake_filter):
        (fake_filter.expects_call().returns_fake().expects('count').returns(1)
                                                  .next_call().returns(1)
                                                  .next_call().returns(0))
        assert InappConfig.generate_public_key(max_tries=5)
