import logging
import random
import uuid
from itertools import cycle, islice, product

from addons.models import AddonCategory, AddonUser, Category
from addons.tasks import save_theme
from amo.tests import (addon_factory, collection_factory, theme_images_factory,
                       ratings_factory, translations_factory)
from amo.utils import slugify
from bandwagon.models import CollectionAddon
from constants.base import ADDON_PERSONA
from users.models import UserProfile

addongenerator_log = logging.getLogger('z.addongenerator')


adjectives = ['Exquisite', 'Delicious', 'Elegant', 'Swanky', 'Spicy',
              'Food Truck', 'Artisanal', 'Tasty']
nouns = ['Sandwich', 'Pizza', 'Curry', 'Pierogi', 'Sushi', 'Salad', 'Stew',
         'Pasta', 'Barbeque', 'Bacon', 'Pancake', 'Waffle', 'Chocolate',
         'Gyro', 'Cookie', 'Burrito', 'Pie']
fake_addon_names = [' '.join(parts) for parts in product(adjectives, nouns)]

# Based on production categories.
categories_choices = (
    (u'Abstract', u'abstract'),
    (u'Causes', u'causes'),
    (u'Fashion', u'fashion'),
    (u'Film and TV', u'film-and-tv'),
    (u'Firefox', u'firefox'),
    (u'Foxkeh', u'foxkeh'),
    (u'Holiday', u'holiday'),
    (u'Music', u'music'),
    (u'Nature', u'nature'),
    (u'Other', u'other'),
    (u'Scenery', u'scenery'),
    (u'Seasonal', u'seasonal'),
    (u'Solid', u'solid'),
    (u'Sports', u'sports'),
    (u'Websites', u'websites'),
)


def generate_categories(num):
    categories = []
    for i, category_choice in enumerate(categories_choices):
        category, created = Category.objects.get_or_create(
            slug=category_choice[1],
            type=ADDON_PERSONA,
            defaults={
                'name': category_choice[0],
                'weight': i,
            })
        if created:
            translations_factory(category)
        categories.append(category)
    return categories


def generate_theme_data(num):
    categories = generate_categories(num)
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


def generate_theme_images(theme):
    header_hash = uuid.uuid4().hex
    footer_hash = uuid.uuid4().hex
    theme_images_factory(theme, 'header', header_hash)
    theme_images_factory(theme, 'footer', footer_hash)
    persona = theme.persona
    persona.header = header_hash
    persona.footer = footer_hash
    persona.save()
    save_theme(header_hash, footer_hash, theme)


def generate_theme(name, category, user):
    theme = addon_factory(name=name, type=ADDON_PERSONA, persona_id=0)
    AddonUser.objects.create(addon=theme, user=user)
    AddonCategory.objects.create(addon=theme, category=category, feature=True)
    return theme


def generate_collections(addon):
    c = collection_factory()
    translations_factory(c)
    CollectionAddon.objects.create(addon=addon, collection=c)


def generate_user(email):
    username = slugify(email)
    user, _created = UserProfile.objects.get_or_create(
        email=email, defaults={'username': username})
    return user


def generate_themes(num, owner=None):
    user = generate_user(owner)
    for themename, category in generate_theme_data(num):
        theme = generate_theme(themename, category, user)
        generate_theme_images(theme)
        translations_factory(theme)
        generate_collections(theme)
        ratings_factory(theme, 5)
