from django.conf import settings
from django.core.management.base import CommandError

import mock
from nose import SkipTest
from nose.tools import eq_, raises

import amo.tests

from mkt.inapp_pay.models import InappConfig
from mkt.inapp_pay.management.commands.rotate_inapp_key import Command
from mkt.inapp_pay.tests import resource


class TestCommand(amo.tests.TestCase):

    @raises(CommandError)
    def test_missing_old(self):
        Command().handle(new_timestamp='2012-05-10')

    @raises(CommandError)
    def test_missing_new(self):
        Command().handle(old_timestamp='2012-05-10')

    @raises(CommandError)
    @mock.patch.object(settings, 'INAPP_KEY_PATHS', {})
    def test_empty_key_paths(self):
        Command().handle(old_timestamp='2012-05-10',
                         new_timestamp='2012-05-11')

    @mock.patch.object(settings, 'DEBUG', True)
    def test_migrate(self):
        raise SkipTest('about to be deleted')
        with mock.patch.object(settings, 'INAPP_KEY_PATHS',
                {'2012-05-10': resource('inapp-sample-pay.key')}):
            cfg = create_inapp_config()
            old_key = cfg.get_private_key()
            old_raw_key = cfg._encrypted_private_key
            cfg = InappConfig.uncached.get(pk=cfg.pk)
            eq_(cfg.key_timestamp, '2012-05-10')

        with mock.patch.object(settings, 'INAPP_KEY_PATHS',
                {'2012-05-10': resource('inapp-sample-pay.key'),
                 '2012-05-11': resource('inapp-sample-pay-alt.key')}):
            Command().handle(old_timestamp='2012-05-10',
                             new_timestamp='2012-05-11')
            cfg = InappConfig.uncached.get(pk=cfg.pk)
            eq_(cfg.get_private_key(), old_key)
            new_raw_key = cfg._encrypted_private_key
            assert new_raw_key != old_raw_key, ('raw keys were changed')
            eq_(cfg.key_timestamp, '2012-05-11')
