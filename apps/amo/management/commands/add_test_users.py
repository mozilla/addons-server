from django.core.management.base import BaseCommand

import amo
from access.models import GroupUser, Group
from apps.users.models import UserProfile


def create_user(email, group_name):
    """Create an user if he doesn't exist already, and assign him to a group.
    """

    # Create the user.
    profile, created = UserProfile.objects.get_or_create(
                username=email, email=email, source=amo.LOGIN_SOURCE_UNKNOWN,
                display_name=email)

    if created:
        profile.create_django_user()

    # Now, find the group we want.
    if not profile.groups.filter(groupuser__group__name=group_name).exists():
        group = Group.objects.get(name=group_name)
        GroupUser.objects.create(group=group, user=profile)


class Command(BaseCommand):
    help = """Create three users with different rights (App Review, Admin,
              Developer)
           """

    def handle(self, *args, **kw):
        create_user('appreviewer@mozilla.com', 'App Reviewers')
        create_user('admin@mozilla.com', 'Admins')
        create_user('developer@mozilla.com', 'Developers')
