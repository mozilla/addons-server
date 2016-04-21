from olympia.amo.tests import TestCase

from olympia.access.acl import action_allowed_user
from olympia.users.models import UserProfile
from olympia.zadmin.management.commands.addusertogroup import do_adduser
from olympia.zadmin.management.commands.removeuserfromgroup import do_removeuser  # noqa


class TestCommand(TestCase):
    fixtures = ['zadmin/group_admin', 'zadmin/users']

    def test_group_management(self):
        user = UserProfile.objects.get(pk=10968)
        assert not action_allowed_user(user, 'Admin', '%')

        do_adduser('10968', '1')
        del user.groups_list
        assert action_allowed_user(user, 'Admin', '%')

        do_removeuser('10968', '1')
        del user.groups_list
        assert not action_allowed_user(user, 'Admin', '%')
