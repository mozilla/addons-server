from django.core import management

from olympia import amo
from olympia.access.acl import action_allowed_user
from olympia.amo.tests import TestCase
from olympia.users.models import UserProfile


class TestCommand(TestCase):
    fixtures = ['zadmin/group_admin', 'zadmin/users']

    def test_group_management(self):
        user = UserProfile.objects.get(pk=10968)
        assert not action_allowed_user(user, amo.permissions.ADMIN_TOOLS)

        management.call_command('addusertogroup', '10968', '1')
        del user.groups_list
        assert action_allowed_user(user, amo.permissions.ADMIN_TOOLS)

        management.call_command('removeuserfromgroup', '10968', '1')
        del user.groups_list
        assert not action_allowed_user(user, amo.permissions.ADMIN_TOOLS)
