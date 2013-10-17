import hashlib
from datetime import datetime
from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

import amo
from access.models import Group, GroupUser
from apps.users.models import UserProfile
from mkt.api.models import Access


@transaction.commit_on_success
def create_user(email, password, group_name=None, overwrite=False):
    """Create an user if he doesn't exist already, assign him to a group and
    create a token for him.

    On token creation, we generate the token key and the token secret. Each of
    them are generated in a predictible way: sha512(password + email + 'key')
    or sha512(password + email + 'secret').
    """
    # Create the user.
    profile, created = UserProfile.objects.get_or_create(
        username=email, email=email, source=amo.LOGIN_SOURCE_UNKNOWN,
        display_name=email)

    if created:
        profile.create_django_user()

    if not profile.read_dev_agreement:
        profile.read_dev_agreement = datetime.now()
        profile.save()

    # Now, find the group we want.
    if (group_name and not
        profile.groups.filter(groupuser__group__name=group_name).exists()):
            group = Group.objects.get(name=group_name)
            GroupUser.objects.create(group=group, user=profile)

    # We also want to grant these users access, so let's create tokens for
    # them.
    if overwrite:
        Access.objects.filter(user=profile.user).delete()

    if not Access.objects.filter(user=profile.user).exists():
        key = hashlib.sha512(password + email + 'key').hexdigest()
        secret = hashlib.sha512(password + email + 'secret').hexdigest()
        Access.objects.create(key=key, secret=secret, user=profile.user)


class Command(BaseCommand):
    help = """Create users with different profiles (App Review, Admin,
              Developer, End User)
           """
    option_list = BaseCommand.option_list + (
        make_option(
            '--clear', action='store_true', dest='clear', default=False,
            help='Clear the user access tokens before recreating them'),)

    def handle(self, *args, **kw):
        options = {'password': settings.API_PASSWORD}

        if kw['clear']:
            options['overwrite'] = True

        create_user('appreviewer@mozilla.com', group_name='App Reviewers',
                    **options)
        create_user('admin@mozilla.com', group_name='Admins', **options)
        create_user('developer@mozilla.com', **options)
        create_user('enduser@mozilla.com', **options)
