from django.conf import settings
from django.core import management

from olympia import amo
from olympia.access.acl import action_allowed_user
from olympia.amo.tests import TestCase, addon_factory
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

    def test_fix_langpack_summary(self):
        """What happened on our production system:

        The `zadmin.tasks.fetch_langpack` task set `summary` to the
        same translation instance of `name` for add-ons without a
        summary set.

        This meant that changing `name` or `summary` automatically
        changed the other one.
        """
        owner = UserProfile.objects.get(email=settings.LANGPACK_OWNER_EMAIL)
        a1 = addon_factory(name='addon 1', users=[owner])
        a1.summary = a1.name
        a1.save()

        # We won't touch this add-on, wrong owner
        a2 = addon_factory(name='addon 2', users=[owner])
        a2.summary = a2.name
        a2.save()

        assert a1.summary.id == a1.name.id
        assert a2.summary.id == a2.summary.id

        # Now, let's fix this mess.
        management.call_command('fix_langpack_summary')

        a1.refresh_from_db()
        a2.refresh_from_db()

        assert a1.summary_id != a1.name_id

        # Didn't touch wrong owner add-on
        assert a2.summary_id == a2.summary_id
