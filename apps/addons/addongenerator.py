# -*- coding: utf-8 -*-
import collections
import logging
import random
import tempfile
from itertools import cycle, islice, product

from PIL import Image, ImageColor

from addons.models import AddonCategory, AddonUser, Category, Preview
from amo.tests import addon_factory, collection_factory
from amo.utils import slugify
from bandwagon.models import Collection, CollectionAddon, FeaturedCollection
from constants.applications import APPS
from constants.base import ADDON_EXTENSION
from devhub.tasks import resize_preview
from reviews.models import Review
from users.models import UserProfile

addongenerator_log = logging.getLogger('z.addongenerator')


adjectives = ['Exquisite', 'Delicious', 'Elegant', 'Swanky', 'Spicy',
              'Food Truck', 'Artisanal', 'Tasty']
nouns = ['Sandwich', 'Pizza', 'Curry', 'Pierogi', 'Sushi', 'Salad', 'Stew',
         'Pasta', 'Barbeque', 'Bacon', 'Pancake', 'Waffle', 'Chocolate',
         'Gyro', 'Cookie', 'Burrito', 'Pie']
fake_addon_names = [' '.join(parts) for parts in product(adjectives, nouns)]

# Based on production categories.
categories_choices = {
    'firefox': (
        # (Label in production, Default icon name),
        (u'Alerts & Updates', u'alerts'),
        (u'Appearance', u'appearance'),
        (u'Bookmarks', u'bookmarks'),
        (u'Download Management', u'downloads'),
        (u'Feeds, News & Blogging', u'feeds'),
        (u'Games & Entertainment', u'games'),
        (u'Language Support', u'dictionary'),
        (u'Photos, Music & Videos', u'photos'),
        (u'Privacy & Security', u'security'),
        (u'Search Tools', u'search'),
        (u'Shopping', u'shopping'),
        (u'Social & Communication', u'social'),
        (u'Tabs', u'tabs'),
        (u'Web Development', u'webdev'),
        (u'Other', u'default'),
    ),
    'thunderbird': (
        # (Label in production, Default icon name),
        (u'Appearance and Customization', u'appearance'),
        (u'Calendar and Date/Time', u'video'),
        (u'Chat and IM', u'social'),
        (u'Contacts', u'music'),
        (u'Folders and Filters', u'shopping'),
        (u'Import/Export', u'downloads'),
        (u'Language Support', u'dictionary'),
        (u'Message Composition', u'posts'),
        (u'Message and News Reading', u'feeds'),
        (u'Miscellaneous', u'default'),
        (u'Privacy and Security', u'alerts'),
        (u'Tags', u'bookmarks'),
    ),
}


def generate_categories(num, app):
    categories = []
    for i, category_choice in enumerate(categories_choices[app.short]):
        category, created = Category.objects.get_or_create(
            slug=category_choice[1],
            type=ADDON_EXTENSION,
            application=app.id,
            defaults={
                'name': category_choice[0],
                'weight': i,
            })
        if created:
            generate_translations(category)
        categories.append(category)
    return categories


def generate_addon_data(num, app):
    categories = generate_categories(num, app)
    if num > len(fake_addon_names):
        base_names = islice(cycle(fake_addon_names), num)
        addons = ['{name} {i}'.format(name=name, i=i)
                  for i, name in enumerate(base_names)]
    else:
        addons = random.sample(fake_addon_names, num)
    num_cats = len(categories)
    for i, addon_name in enumerate(addons):
        cat = categories[i % num_cats]
        yield (addon_name, cat)


def generate_preview(addon, n=1):
    color = random.choice(ImageColor.colormap.keys())
    im = Image.new('RGB', (320, 480), color)
    p = Preview.objects.create(addon=addon, filetype='image/png',
                               thumbtype='image/png',
                               caption='Screenshot {n}'.format(n=n),
                               position=n)
    f = tempfile.NamedTemporaryFile()
    im.save(f, 'png')
    resize_preview(f.name, p)


def generate_translations(item):
    fr_prefix = u'(français) '
    es_prefix = u'(español) '
    oldname = unicode(item.name)
    item.name = {'en': oldname,
                 'fr': fr_prefix + oldname,
                 'es': es_prefix + oldname}
    item.save()


def generate_ratings(addon, num):
    for n in range(num):
        email = 'testuser{num}@example.com'.format(num=num)
        user, _ = UserProfile.objects.get_or_create(
            username=email, email=email, display_name=email)
        Review.objects.create(
            addon=addon, user=user, rating=random.randrange(0, 6),
            title='Test Review {n}'.format(n=n), body='review text')


def generate_addon(name, category, user, app):
    # Use default icons from the filesystem given the category.
    icon_type = 'icon/{slug}'.format(slug=category.slug)
    addon = addon_factory(name=name, icon_type=icon_type,
                          version_kw={'application': app.id})
    AddonUser.objects.create(addon=addon, user=user)
    AddonCategory.objects.create(addon=addon, category=category, feature=True)
    return addon


def generate_collections(addon, app, num):
    c = collection_factory(application=app.id)
    generate_translations(c)
    CollectionAddon.objects.create(addon=addon, collection=c)
    FeaturedCollection.objects.create(application=app.id, collection=c)


def generate_user(email):
    email = email or 'nobody@mozilla.org'
    username = slugify(email)
    user, _ = UserProfile.objects.get_or_create(
        email=email, defaults={'username': username})
    return user


def generate_addons(num, owner=None, app_name='firefox'):
    featured_categories = collections.defaultdict(int)
    user = generate_user(owner)
    app = APPS[app_name]
    for addonname, category in generate_addon_data(num, app):
        addon = generate_addon(addonname, category, user, app)
        generate_preview(addon)
        generate_translations(addon)
        # Only feature 5 addons per category at max.
        if featured_categories[category] < 5:
            generate_collections(addon, app, num)
            featured_categories[category] += 1
        generate_ratings(addon, 5)
