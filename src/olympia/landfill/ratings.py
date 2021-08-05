import random

from django.utils.crypto import get_random_string

from olympia.addons.models import Rating
from olympia.users.models import UserProfile


def generate_ratings(addon, num):
    """Given an `addon`, generate `num` random ratings."""
    for n in range(1, num + 1):
        username = f'testuser-{get_random_string(12)}'
        email = f'{username}@example.com'
        user, _created = UserProfile.objects.get_or_create(
            username=email, email=email, defaults={'display_name': email}
        )
        Rating.objects.create(
            addon=addon,
            user=user,
            rating=random.randrange(0, 6),
            body=f'Test Review {n}',
        )
