import random

from olympia.addons.models import Review
from olympia.users.models import UserProfile


def generate_ratings(addon, num):
    """Given an `addon`, generate `num` random ratings."""
    for n in range(1, num + 1):
        email = 'testuser{n}@example.com'.format(n=n)
        user, _created = UserProfile.objects.get_or_create(
            username=email, email=email, display_name=email)
        Review.objects.create(
            addon=addon, user=user, rating=random.randrange(0, 6),
            title='Test Review {n}'.format(n=n), body='review text')
