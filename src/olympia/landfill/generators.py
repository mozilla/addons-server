import collections
import random

from datetime import datetime
from itertools import cycle, islice

from django.db.models.signals import post_save

from olympia.addons.models import Addon, update_search_index
from olympia.amo.utils import slugify
from olympia.constants.applications import APPS
from olympia.constants.base import ADDON_EXTENSION, ADDON_STATICTHEME, STATUS_APPROVED
from olympia.constants.categories import CATEGORIES

from .collection import generate_collection
from .images import generate_addon_preview
from .names import generate_names
from .ratings import generate_ratings
from .translations import generate_translations
from .user import generate_addon_user_and_category, generate_user
from .version import generate_version


def _yield_name_and_cat(num, app=None, type=None):
    """
    Yield `num` tuples of (addon_name, category) for the given `app`
    and `type`.
    """
    categories = list(CATEGORIES[app.id][type].values())
    if num > len(generate_names()):
        base_names = islice(cycle(generate_names()), num)
        addons = [
            '{name} {i}'.format(name=name, i=i) for i, name in enumerate(base_names)
        ]
    else:
        addons = random.sample(generate_names(), num)
    num_cats = len(categories)
    for i, addon_name in enumerate(addons):
        cat = categories[i % num_cats]
        yield (addon_name, cat)


def create_addon(name, application, **extra_kwargs):
    """Create an addon with the given `name` and his version."""
    kwargs = {
        'status': STATUS_APPROVED,
        'name': name,
        'slug': slugify(name),
        'bayesian_rating': random.uniform(1, 5),
        'average_daily_users': random.randint(200, 2000),
        'weekly_downloads': random.randint(200, 2000),
        'created': datetime.now(),
        'last_updated': datetime.now(),
        'type': ADDON_EXTENSION,
    }
    kwargs.update(extra_kwargs)

    addon = Addon.objects.create(**kwargs)
    generate_version(addon=addon, app=application)
    addon.update_version()
    addon.status = STATUS_APPROVED
    addon.guid = '@%s' % addon.slug
    addon.save()
    return addon


def generate_addons(num, owner, app_name, addon_type=ADDON_EXTENSION):
    """Generate `num` addons for the given `owner` and `app_name`."""
    # Disconnect this signal given that we issue a reindex at the end.
    post_save.disconnect(
        update_search_index, sender=Addon, dispatch_uid='addons.search.index'
    )

    featured_categories = collections.defaultdict(int)
    user = generate_user(owner)
    app = APPS[app_name]
    for name, category in _yield_name_and_cat(num, app=app, type=addon_type):
        addon = create_addon(name=name, application=app, type=addon_type)
        generate_addon_user_and_category(addon, user, category)
        generate_addon_preview(addon)
        generate_translations(addon)
        # Only feature 5 addons per category at max.
        if featured_categories[category] < 5:
            generate_collection(addon, app)
            featured_categories[category] += 1
        generate_ratings(addon, 5)


def generate_themes(num, owner, **kwargs):
    """Generate `num` themes for the given `owner`."""
    generate_addons(num, owner, 'firefox', addon_type=ADDON_STATICTHEME)
