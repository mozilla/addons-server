import random

from datetime import datetime

from olympia import amo
from olympia.amo.utils import slugify
from olympia.bandwagon.models import (
    Collection, CollectionAddon, FeaturedCollection)

from .translations import generate_translations


def create_collection(application, **kwargs):
    """Create a Collection for the given `application`."""
    data = {
        'type': amo.COLLECTION_NORMAL,
        'application': application,
        'name': 'Collection %s' % abs(hash(datetime.now())),
        'addon_count': random.randint(200, 2000),
        'listed': True,
    }
    data.update(kwargs)
    c = Collection(**data)
    c.slug = slugify(data['name'])
    c.created = c.modified = datetime(2014, 10, 27, random.randint(0, 23),
                                      random.randint(0, 59))
    c.save()
    return c


def generate_collection(addon, app=None, **kwargs):
    """
    Generate a Collection, a CollectionAddon and a FeaturedCollection
    for the given `addon` related to the optional `app`.
    """
    if app is None:  # This is a theme.
        application = None
    else:
        application = app.id

    c = create_collection(application=application, **kwargs)
    generate_translations(c)
    CollectionAddon.objects.create(addon=addon, collection=c)
    if app is not None:  # Useless for themes.
        FeaturedCollection.objects.create(application=application,
                                          collection=c)
