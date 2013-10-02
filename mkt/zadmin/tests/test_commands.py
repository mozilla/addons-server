from nose.exc import SkipTest

import amo.tests

from apps.access.acl import action_allowed_user
from apps.users.models import UserProfile
from mkt.site.fixtures import fixture
from mkt.zadmin.management.commands.addusertogroup import do_adduser
from mkt.zadmin.management.commands.removeuserfromgroup import do_removeuser


class TestCommand(amo.tests.TestCase):
    fixtures = fixture('group_admin', 'user_10482')

    def test_group_management(self):
        #TODO. I don't know how to override caching in tests --clouserw
        raise SkipTest('Fails due to caching of groups.all()')

        x = UserProfile.objects.get(pk=10482)
        assert not action_allowed_user(x, 'Admin', '%')
        do_adduser('10482', '1')
        assert action_allowed_user(x, 'Admin', '%')
        do_removeuser('10482', '1')
        assert not action_allowed_user(x, 'Admin', '%')
