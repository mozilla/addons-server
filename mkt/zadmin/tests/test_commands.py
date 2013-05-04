import os
import shutil
import tempfile

from django.conf import settings
from django.core.management.base import CommandError

from nose.tools import eq_, raises

import amo.tests

from apps.access.acl import action_allowed_user
from apps.users.models import UserProfile
from mkt.site.fixtures import fixture
from mkt.zadmin.management.commands.genkey import Command
from mkt.zadmin.management.commands.addusertogroup import do_adduser
from mkt.zadmin.management.commands.removeuserfromgroup import do_removeuser


class TestCommand(amo.tests.TestCase):
    fixtures = fixture('group_admin', 'user_10482')

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

    def test_group_management(self):
        x = UserProfile.objects.get(pk=10482)
        assert not action_allowed_user(x, 'Admin', '%')
        do_adduser('10482', '1')
        assert action_allowed_user(x, 'Admin', '%')
        do_removeuser('10482', '1')
        assert not action_allowed_user(x, 'Admin', '%')
