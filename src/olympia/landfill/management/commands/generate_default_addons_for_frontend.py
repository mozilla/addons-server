# -*- coding: utf-8 -*-

from django.core.management.base import BaseCommand
from django.utils import translation
from django.test.utils import override_settings
from django.db.models.signals import post_save

from olympia.landfill.serializers import GenerateAddonsSerializer
from olympia.addons.models import Addon, update_search_index


#  Featured collections on the homepage.
#  Needs to be updated as the homepage is updated
featured_collections = [
    'social-media-customization',
    'dynamic-media-downloaders',
    'summer-themes',
    'must-have-media',
]

#  Featured collections on the homepage.
base_collections = [
    u'bookmark-managers',
    u'password-managers',
    u'ad-blockers',
    u'smarter-shopping',
    u'be-more-productive',
    u'watching-videos',
]

#  Addons that exist in the carousel.
#  Needs to be updated as the homepage is updated
hero_addons = [
    u'facebook-container'
    u'midnight-lizard-quantum'
    u'turbo-download-manager'
    u'auth-helper'
    u'ip-address-and-domain-info'
    u'ublock-origin'
    u'ghostery'
    u'multi-account-containers'
    u'transparent-standalone-image'
    u'tabliss'
    u'share-backported'
    u'view-page-archive'
    u'privacy-possum'
    u'page-translate'
    u'textmarkerpro'
    u'forget_me_not'
    u'groupspeeddial'
    u'styl-us'
]


class Command(BaseCommand):
    """
    Generate addons used specifically for the Integration Tests.

    This will generate 10 addons with the name Ui-Addon, 1 Addon named
    Ui-Addon-Test, 1 Featured theme, 4 featured collections, and 6 themes that
    will not be marked as featured.

    Usage:

        python manage.py generate_default_addons_for_frontend

    """

    def handle(self, *args, **kwargs):
        # Disconnect reindexing for every save, we'll reindex
        # once all addons were generated
        post_save.disconnect(update_search_index, sender=Addon,
                             dispatch_uid='addons.search.index')

        with override_settings(CELERY_ALWAYS_EAGER=True):
            translation.activate('en-US')
            serializer = GenerateAddonsSerializer()
            serializer.create_generic_featured_addons()
            serializer.create_featured_addon_with_version()
            serializer.create_featured_theme()
            serializer.create_featured_collections()
            serializer.create_featured_themes()
            for addon in featured_collections:
                serializer.create_a_named_collection_and_addon(
                    addon, author='mozilla')
            for addon in base_collections:
                serializer.create_a_named_collection_and_addon(
                    addon, author='mozilla')
            for addon in hero_addons:
                serializer.create_named_addon_with_author(addon)
            serializer.create_installable_addon()
