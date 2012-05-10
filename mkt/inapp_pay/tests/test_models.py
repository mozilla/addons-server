import inspect
import os

from django.conf import settings

import fudge
import mock
from nose.tools import eq_, raises

import amo
import amo.tests
from mkt.inapp_pay.models import (InappConfig, TooManyKeyGenAttempts,
                                  InappPayLog)
from mkt.inapp_pay import verify
from mkt.inapp_pay.tests import resource
from mkt.inapp_pay.verify import InappPaymentError
from mkt.webapps.models import Webapp


class TestInapp(amo.tests.TestCase):

    def setUp(self):
        self.app = Webapp.objects.create(manifest_url='http://foo.ca')
        self.inapp = InappConfig.objects.create(addon=self.app,
                                                public_key='asd')

    def test_active(self):
        eq_(self.inapp.is_active(), False)
        self.inapp.update(status=amo.INAPP_STATUS_ACTIVE)
        eq_(self.inapp.is_active(), True)

    def test_any_active_excludes_config_under_edit(self):
        c = InappConfig.objects.create(addon=self.app,
                                       status=amo.INAPP_STATUS_ACTIVE,
                                       public_key='asd-1')
        assert not InappConfig.any_active(self.app, exclude_config=c.pk)
        c.save()  # no exception

    def test_any_active(self):
        assert not InappConfig.any_active(self.app)
        InappConfig.objects.create(addon=self.app,
                                   status=amo.INAPP_STATUS_ACTIVE,
                                   public_key='asd-1')
        assert InappConfig.any_active(self.app)
        self.assertRaises(ValueError, InappConfig.objects.create,
                          addon=self.app, status=amo.INAPP_STATUS_ACTIVE,
                          public_key='asd-2')

    def test_generate_public_key(self):
        key = InappConfig.generate_public_key()
        assert key

    @mock.patch.object(settings, 'DEBUG', True)
    def test_generate_private_key(self):
        key = InappConfig.generate_private_key()
        assert key

    @raises(TooManyKeyGenAttempts)
    @mock.patch.object(settings, 'DEBUG', True)
    @fudge.patch('mkt.inapp_pay.models.connection')
    def test_exhaust_private_keygen_attempts(self, fake_conn):
        (fake_conn.expects('cursor').returns_fake()
                  .expects('execute').expects('fetchone').returns([1]))
        InappConfig.generate_private_key(max_tries=5)

    @raises(TooManyKeyGenAttempts)
    @fudge.patch('mkt.inapp_pay.models.InappConfig.objects.filter')
    def test_exhaust_public_keygen_attempts(self, fake_filter):
        fake_filter.expects_call().returns_fake().expects('count').returns(1)
        InappConfig.generate_public_key(max_tries=5)

    @mock.patch.object(settings, 'DEBUG', True)
    @fudge.patch('mkt.inapp_pay.models.connection')
    def test_retry_private_keygen_until_unique(self, fake_conn):
        (fake_conn.expects('cursor').returns_fake()
                  .expects('execute')
                  .expects('fetchone').returns([1])
                  .next_call().returns([1])
                  .next_call().returns([0]))
        assert InappConfig.generate_private_key(max_tries=5)

    @fudge.patch('mkt.inapp_pay.models.InappConfig.objects.filter')
    def test_retry_public_keygen_until_unique(self, fake_filter):
        (fake_filter.expects_call().returns_fake()
                                   .expects('count').returns(1)
                                   .next_call().returns(1)
                                   .next_call().returns(0))
        assert InappConfig.generate_public_key(max_tries=5)

    @raises(EnvironmentError)
    @mock.patch.object(settings, 'DEBUG', False)
    def test_key_path_cannot_match_sample(self):
        self.inapp.set_private_key('sekret')

    @mock.patch.object(settings, 'DEBUG', True)
    def test_encrypted_key_storage(self):
        sk = 'this is the secret'
        self.inapp.set_private_key(sk)
        eq_(self.inapp.get_private_key(), sk)
        cfg = InappConfig.objects.get(pk=self.inapp.pk)
        assert cfg._encrypted_private_key != sk, (
                        'secret was not encrypted: %s'
                        % cfg._encrypted_private_key)

    @raises(ValueError)
    @mock.patch.object(settings, 'DEBUG', True)
    def test_wrong_key(self):
        sk = 'your coat is hidden under the stairs'
        self.inapp.set_private_key(sk)
        altkey = resource('inapp-sample-pay-alt.key')
        with mock.patch.object(settings, 'INAPP_KEY_PATHS',
                               {'2012-05-09': altkey}):
            self.inapp.get_private_key()

    @mock.patch.object(settings, 'DEBUG', True)
    def test_encrypt_with_latest_key(self):
        badkey = resource('__nonexistant__.key')
        goodkey = resource('inapp-sample-pay.key')
        with mock.patch.object(settings, 'INAPP_KEY_PATHS',
                               {'2012-05-09': badkey,
                                '2012-05-10': goodkey}):
            sk = 'your coat is hidden under the stairs'
            self.inapp.set_private_key(sk)
            eq_(self.inapp.get_private_key(), sk)

    @mock.patch.object(settings, 'DEBUG', True)
    def test_pin_to_corect_key(self):
        sk = 'your coat is hidden under the stairs'
        altkey = resource('inapp-sample-pay-alt.key')
        goodkey = resource('inapp-sample-pay.key')
        with mock.patch.object(settings, 'INAPP_KEY_PATHS',
                               {'2012-05-09': altkey}):
            self.inapp.set_private_key(sk)
            eq_(self.inapp.get_private_key(), sk)
        self.inapp = InappConfig.objects.get(pk=self.inapp.pk)
        with mock.patch.object(settings, 'INAPP_KEY_PATHS',
                               {'2012-05-09': altkey,
                                '2012-05-10': goodkey}):
            eq_(self.inapp.get_private_key(), sk)

    @raises(IndexError)
    @mock.patch.object(settings, 'DEBUG', True)
    def test_missing_date_str(self):
        sk = 'your coat is hidden under the stairs'
        altkey = resource('inapp-sample-pay-alt.key')
        with mock.patch.object(settings, 'INAPP_KEY_PATHS',
                               {'2012-05-09': altkey}):
            self.inapp.set_private_key(sk)
            eq_(self.inapp.get_private_key(), sk)
        with mock.patch.object(settings, 'INAPP_KEY_PATHS', {}):
            eq_(self.inapp.get_private_key(), sk)


def test_exception_mapping():
    at_least_one = False
    for name in dir(verify):
        ob = getattr(verify, name)
        if (inspect.isclass(ob) and (issubclass(ob, InappPaymentError)
                                     or ob is InappPaymentError)):
            at_least_one = True
            assert ob.__name__ in InappPayLog._exceptions, (
                                    '%r is not mapped' % ob.__name__)
    assert at_least_one
