import amo.tests

from apps.access.acl import action_allowed_user
from apps.users.models import UserProfile
from zadmin.management.commands.addusertogroup import do_adduser
from zadmin.management.commands.removeuserfromgroup import do_removeuser


class TestCommand(amo.tests.TestCase):
    fixtures = ['zadmin/group_admin', 'zadmin/users']

    def test_group_management(self):
        x = UserProfile.objects.get(pk=10968)
        assert not action_allowed_user(x, 'Admin', '%')
        do_adduser('10968', '1')
        assert action_allowed_user(x, 'Admin', '%')
        do_removeuser('10968', '1')
        assert not action_allowed_user(x, 'Admin', '%')
