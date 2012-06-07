import os
import shutil
import tempfile

from django.conf import settings
from django.core.management.base import CommandError

from nose.tools import eq_, raises

import amo.tests

from mkt.zadmin.management.commands.genkey import Command


class TestCommand(amo.tests.TestCase):

    def test_gen_key_with_length(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp))
        tmp_key = os.path.join(tmp, 'inapp.key')
        Command().handle(dest=tmp_key, length=256)
        with open(tmp_key, 'r') as fp:
            eq_(len(fp.read()), 512)

    @raises(CommandError)
    def test_gen_key_existing(self):
        Command().handle(dest=settings.INAPP_KEY_PATHS.values()[0])
