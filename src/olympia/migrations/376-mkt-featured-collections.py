from bandwagon.models import Collection
from users.models import UserProfile

from olympia import amo


def run():
    a, created = UserProfile.objects.get_or_create(username="mozilla")
    Collection.objects.get_or_create(
        author=a,
        slug="webapps_home",
        type=amo.COLLECTION_FEATURED,
        listed=False,
    )
    Collection.objects.get_or_create(
        author=a,
        slug="webapps_featured",
        type=amo.COLLECTION_FEATURED,
        listed=False,
    )
