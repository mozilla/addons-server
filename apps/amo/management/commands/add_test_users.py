import hashlib

from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings

import amo
from access.models import GroupUser, Group
from apps.users.models import UserProfile
from mkt.api.models import Access


@transaction.commit_on_success
def create_user(email, group_name, salt):
    """Create an user if he doesn't exist already, assign him to a group and
    create a token for him.

    On token creation, we generate the token key and the token secret. Each of
    them are generated in a predictible way: md5(salt + email + 'key') or
    md5(salt + email + 'secret').
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

    # We also want to grant these users access, so let's create tokens for
    # them.
    if not Access.objects.filter(user=profile.user).exists():
        key = hashlib.md5(salt + email + 'key').hexdigest()
        secret = hashlib.md5(salt + email + 'secret').hexdigest()
        consumer = Access(key=key, secret=secret, user=profile.user)
        consumer.save()


class Command(BaseCommand):
    help = """Create three users with different profiles (App Review, Admin,
              Developer)
           """

    def handle(self, *args, **kw):
        options = {'salt': settings.API_SALT}

        create_user('appreviewer@mozilla.com', 'App Reviewers', **options)
        create_user('admin@mozilla.com', 'Admins', **options)
        create_user('developer@mozilla.com', 'Developers', **options)
