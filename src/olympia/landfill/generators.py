import collections
import random
from datetime import datetime
from itertools import cycle, islice

from django.db.models.signals import post_save

from amo.utils import slugify
from addons.models import Addon, Persona, update_search_index
from constants.applications import APPS
from constants.base import ADDON_EXTENSION, ADDON_PERSONA, STATUS_PUBLIC

from .categories import generate_categories
from .collection import generate_collection
from .images import generate_addon_preview, generate_theme_images
from .names import generate_names
from .translations import generate_translations
from .ratings import generate_ratings
from .user import generate_addon_user_and_category, generate_user
from .version import generate_version


def _yield_name_and_cat(num, app=None):
    """
    Yield `num` tuples of (addon_name, category) for the optional `app`.
    If the `app` is not provided, it will yield categories for themes.

    """
    categories = generate_categories(app)
    if num > len(generate_names()):
        base_names = islice(cycle(generate_names()), num)
        addons = ['{name} {i}'.format(name=name, i=i)
                  for i, name in enumerate(base_names)]
    else:
        addons = random.sample(generate_names(), num)
    num_cats = len(categories)
    for i, addon_name in enumerate(addons):
        cat = categories[i % num_cats]
        yield (addon_name, cat)


def create_addon(name, icon_type, application):
    """Create an addon with the given `name` and his version."""
    kwargs = {
        'status': STATUS_PUBLIC,
        'name': name,
        'slug': slugify(name),
        'bayesian_rating': random.uniform(1, 5),
        'average_daily_users': random.randint(200, 2000),
        'weekly_downloads': random.randint(200, 2000),
        'created': datetime.now(),
        'last_updated': datetime.now(),
        'icon_type': icon_type,
    }

    addon = Addon.objects.create(type=ADDON_EXTENSION, **kwargs)
    generate_version(addon=addon, app=application)
    addon.update_version()
    addon.status = STATUS_PUBLIC
    addon.save()
    return addon


def generate_addons(num, owner, app_name):
    """Generate `num` addons for the given `owner` and `app_name`."""
    # Disconnect this signal given that we issue a reindex at the end.
    post_save.disconnect(update_search_index, sender=Addon,
                         dispatch_uid='addons.search.index')

    featured_categories = collections.defaultdict(int)
    user = generate_user(owner)
    app = APPS[app_name]
    for name, category in _yield_name_and_cat(num, app):
        # Use default icons from the filesystem given the category.
        icon_type = 'icon/{slug}'.format(slug=category.slug)
        addon = create_addon(name=name, icon_type=icon_type,
                             application=app)
        generate_addon_user_and_category(addon, user, category)
        generate_addon_preview(addon)
        generate_translations(addon)
        # Only feature 5 addons per category at max.
        if featured_categories[category] < 5:
            generate_collection(addon, app)
            featured_categories[category] += 1
        generate_ratings(addon, 5)


def create_theme(name):
    """
    Create a theme with the given `name`, his version and Persona
    instance.

    """
    kwargs = {
        'status': STATUS_PUBLIC,
        'name': name,
        'slug': slugify(name),
        'bayesian_rating': random.uniform(1, 5),
        'average_daily_users': random.randint(200, 2000),
        'weekly_downloads': random.randint(200, 2000),
        'created': datetime.now(),
        'last_updated': datetime.now(),
    }

    # Themes need to start life as an extension for versioning.
    theme = Addon.objects.create(type=ADDON_EXTENSION, **kwargs)
    generate_version(addon=theme)
    theme.update_version()
    theme.status = STATUS_PUBLIC
    theme.type = ADDON_PERSONA
    Persona.objects.create(addon=theme, popularity=theme.weekly_downloads,
                           persona_id=0)
    theme.save()
    return theme


def generate_themes(num, owner):
    """Generate `num` themes for the given `owner`."""
    # Disconnect this signal given that we issue a reindex at the end.
    post_save.disconnect(update_search_index, sender=Addon,
                         dispatch_uid='addons.search.index')

    user = generate_user(owner)
    for name, category in _yield_name_and_cat(num):
        theme = create_theme(name=name)
        generate_addon_user_and_category(theme, user, category)
        generate_theme_images(theme)
        generate_translations(theme)
        generate_collection(theme)
        generate_ratings(theme, 5)
